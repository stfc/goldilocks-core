# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e

FROM python:3.12.16-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS core-build
COPY --from=ghcr.io/astral-sh/uv:0.12.3@sha256:2d890623d310b57771ce840f0da5eed5fc6d657da05ffaa45d82797b53fa3abc /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    GOLDILOCKS_ASSET_ROOT=/opt/goldilocks/assets
# A C++ compiler for the sdists the lock has no wheel for on this platform
# (dscribe ships x86_64 Linux wheels only, so arm64 builds it from source),
# and gfortran, make and git for enumlib.
RUN rm -f /etc/apt/sources.list.d/debian.sources \
    && printf '%s\n' 'deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/20260801T000000Z bookworm main' > /etc/apt/sources.list \
    && apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install --no-install-recommends -y \
        g++=4:12.2.0-3 \
        gfortran=4:12.2.0-3 \
        make=4.3-4.1 \
        git=1:2.39.5-0+deb12u3 \
    && rm -rf /var/lib/apt/lists/*
# enumlib's enum.x and makeStr.py, which list antiferromagnetic orderings.
# The same commit as .github/actions/core-setup, so CI tests this build.
ARG ENUMLIB_COMMIT=67217859c1cfe6e1d8cfe25b76a1d14a28c6030e
RUN git clone --quiet https://github.com/msg-byu/enumlib.git /build/enumlib \
    && git -C /build/enumlib checkout --quiet "$ENUMLIB_COMMIT" \
    && git -C /build/enumlib submodule update --quiet --init --recursive \
    && make -C /build/enumlib/symlib/src F90=gfortran \
    && make -C /build/enumlib/src F90=gfortran \
    && make -C /build/enumlib/src F90=gfortran enum.x \
    && install -d /build/enumlib-bin /build/enumlib-licenses/enumlib /build/enumlib-licenses/symlib \
    && install /build/enumlib/src/enum.x /build/enumlib-bin/enum.x \
    && sed '1s|.*|#!/app/.venv/bin/python3|' /build/enumlib/aux_src/makeStr.py > /build/enumlib-bin/makeStr.py \
    && chmod +x /build/enumlib-bin/makeStr.py \
    && install -m 644 /build/enumlib/LICENSE /build/enumlib-licenses/enumlib/LICENSE \
    && install -m 644 /build/enumlib/symlib/LICENSE /build/enumlib-licenses/symlib/LICENSE
WORKDIR /build/core
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra http --no-editable
COPY scripts/export_workbench_openapi.py ./scripts/export_workbench_openapi.py
RUN /app/.venv/bin/python scripts/export_workbench_openapi.py --output /build/openapi.json
RUN /app/.venv/bin/goldilocks assets install all \
    && /app/.venv/bin/goldilocks assets verify all

FROM node:26.13.0-bookworm-slim@sha256:add5c17c14752c54d2f3d519ec46a3815684d41c33f198bcb09fb998f7dcbf68 AS workbench-build
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY web/ ./
COPY --from=core-build /build/openapi.json ./openapi.json
RUN npm run generate:schema && npm --ignore-scripts run build

FROM python:3.12.16-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS runtime
LABEL org.opencontainers.image.title="goldilocks-core" \
      org.opencontainers.image.description="Guided DFT input recommendation with bundled runtime assets" \
      org.opencontainers.image.source="https://github.com/stfc/goldilocks-core" \
      org.opencontainers.image.licenses="BSD-3-Clause AND CC-BY-3.0 AND CC-BY-4.0 AND CC-BY-SA-4.0 AND GPL-2.0-or-later AND GPL-3.0-only AND MIT" \
      org.opencontainers.image.license-notice="See /usr/share/licenses/goldilocks-core and /opt/goldilocks/assets"

RUN rm -f /etc/apt/sources.list.d/debian.sources \
    && printf '%s\n' 'deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/20260801T000000Z bookworm main' > /etc/apt/sources.list \
    && apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install --no-install-recommends -y \
        libgomp1=12.2.0-14+deb12u1 \
        libgfortran5=12.2.0-14+deb12u1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system goldilocks \
    && useradd --system --gid goldilocks --home-dir /app goldilocks

ENV PATH=/opt/goldilocks/enumlib-bin:/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/app/.cache/matplotlib \
    GOLDILOCKS_ASSET_ROOT=/opt/goldilocks/assets \
    GOLDILOCKS_WORKBENCH_STATIC_ROOT=/app/workbench

WORKDIR /app
COPY --from=core-build --chown=goldilocks:goldilocks /app/.venv ./.venv
RUN mkdir -p "$MPLCONFIGDIR" \
    && /app/.venv/bin/python -c "import matplotlib.font_manager" \
    && chown -R goldilocks:goldilocks /app/.cache
COPY --from=core-build --chown=goldilocks:goldilocks /opt/goldilocks/assets /opt/goldilocks/assets
COPY --from=workbench-build --chown=goldilocks:goldilocks /build/web/dist ./workbench
COPY --chown=goldilocks:goldilocks LICENSE /usr/share/licenses/goldilocks-core/LICENSE
COPY --from=core-build /build/enumlib-bin /opt/goldilocks/enumlib-bin
COPY --from=core-build /build/enumlib-licenses /usr/share/licenses

USER goldilocks
EXPOSE 8000
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3)"]

CMD ["goldilocks", "serve", "http", "--host", "0.0.0.0", "--port", "8000"]
