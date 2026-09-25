# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e

FROM python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7 AS core-build
COPY --from=ghcr.io/astral-sh/uv:0.12.3@sha256:2d890623d310b57771ce840f0da5eed5fc6d657da05ffaa45d82797b53fa3abc /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    GOLDILOCKS_ASSET_ROOT=/opt/goldilocks/assets

# Build toolchain for this stage: gfortran/make/git build enumlib (below); g++ lets
# uv sync compile dscribe from its sdist on platforms with no prebuilt wheel -- dscribe
# 2.1.2 ships linux wheels for x86_64 only (confirmed against PyPI's own file list), so
# arm64 (e.g. a plain `docker build .` on Apple Silicon) always needs to build it from
# source; pybind11/Eigen are already resolved by that build itself (build-isolation
# installs pybind11, Eigen is vendored in the sdist), g++ was the only missing piece.
#
# enumlib (external dependency for AFM species-splitting -- see
# advisors/magnetic_config.py's shutil.which("enum.x")/("multienum.x") check): built here
# from source, the same way ci.yml's "Build enumlib" step does, so the shipped image
# supports magnetic_ordering=afm out of the box instead of silently degrading to FM.
RUN rm -f /etc/apt/sources.list.d/debian.sources \
    && printf '%s\n' 'deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/20260801T000000Z bookworm main' > /etc/apt/sources.list \
    && apt-get update \
    && apt-get install --no-install-recommends -y g++ git gfortran make \
    && rm -rf /var/lib/apt/lists/* \
    && git clone --recursive --depth 1 https://github.com/msg-byu/enumlib.git /tmp/enumlib \
    && make -C /tmp/enumlib/symlib/src F90=gfortran \
    && make -C /tmp/enumlib/src F90=gfortran \
    && make -C /tmp/enumlib/src F90=gfortran enum.x \
    && install -d /build/enumlib-bin \
    && install /tmp/enumlib/src/enum.x /build/enumlib-bin/enum.x \
    && sed '1s|.*|#!/app/.venv/bin/python3|' /tmp/enumlib/aux_src/makeStr.py > /build/enumlib-bin/makeStr.py \
    && chmod +x /build/enumlib-bin/makeStr.py \
    && rm -rf /tmp/enumlib

WORKDIR /build/core
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra http --no-editable
COPY scripts/export_workbench_openapi.py ./scripts/export_workbench_openapi.py
RUN /app/.venv/bin/python scripts/export_workbench_openapi.py --output /build/openapi.json
RUN /app/.venv/bin/goldilocks assets install workbench \
    && /app/.venv/bin/goldilocks assets verify workbench

FROM node:24.19.0-bookworm-slim@sha256:3638d9a6fe4030bd716be989438248074489337ba3275657f93595428be4fc03 AS workbench-build
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY web/ ./
COPY --from=core-build /build/openapi.json ./openapi.json
RUN npm run generate:schema && npm --ignore-scripts run build

FROM python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7 AS runtime
LABEL org.opencontainers.image.title="Goldilocks Workbench" \
      org.opencontainers.image.description="Guided DFT input recommendation with bundled runtime assets" \
      org.opencontainers.image.source="https://github.com/stfc/goldilocks-core" \
      org.opencontainers.image.licenses="BSD-3-Clause AND CC-BY-3.0 AND CC-BY-4.0 AND CC-BY-SA-4.0 AND GPL-2.0-or-later AND GPL-3.0-only" \
      org.opencontainers.image.license-notice="See /usr/share/licenses/goldilocks-core and /opt/goldilocks/assets"

RUN rm -f /etc/apt/sources.list.d/debian.sources \
    && printf '%s\n' 'deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/20260801T000000Z bookworm main' > /etc/apt/sources.list \
    && apt-get update \
    && apt-get install --no-install-recommends -y \
       libgomp1=12.2.0-14+deb12u1 libgfortran5=12.2.0-14+deb12u1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system goldilocks \
    && useradd --system --gid goldilocks --home-dir /app goldilocks

ENV PATH=/opt/goldilocks/enumlib-bin:/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/app/.cache/matplotlib \
    GOLDILOCKS_ASSET_ROOT=/opt/goldilocks/assets \
    GOLDILOCKS_WORKBENCH_STATIC_ROOT=/app/workbench

WORKDIR /app
# /app itself (not just the files copied into it below) must be writable by
# goldilocks: pymatgen's enumlib caller (monty.tempfile.ScratchDir(".")) creates its
# scratch directory as a subdirectory of the process's cwd, not of $TMPDIR/tempfile's
# system default -- so AFM magnetic-ordering enumeration fails with a permission error
# at runtime otherwise, even with enum.x itself present and working.
RUN chown goldilocks:goldilocks /app
COPY --from=core-build --chown=goldilocks:goldilocks /app/.venv ./.venv
RUN mkdir -p "$MPLCONFIGDIR" \
    && /app/.venv/bin/python -c "import matplotlib.font_manager" \
    && chown -R goldilocks:goldilocks /app/.cache
COPY --from=core-build --chown=goldilocks:goldilocks /opt/goldilocks/assets /opt/goldilocks/assets
COPY --from=core-build --chown=goldilocks:goldilocks /build/enumlib-bin /opt/goldilocks/enumlib-bin
COPY --from=workbench-build --chown=goldilocks:goldilocks /build/web/dist ./workbench
COPY --chown=goldilocks:goldilocks LICENSE /usr/share/licenses/goldilocks-core/LICENSE

USER goldilocks
EXPOSE 8000
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3)"]

CMD ["goldilocks", "serve", "http", "--host", "0.0.0.0", "--port", "8000"]
