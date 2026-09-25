# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e

FROM python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 AS core-build
COPY --from=ghcr.io/astral-sh/uv:0.12.3@sha256:2d890623d310b57771ce840f0da5eed5fc6d657da05ffaa45d82797b53fa3abc /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    GOLDILOCKS_ASSET_ROOT=/opt/goldilocks/assets
WORKDIR /build/core
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src/ ./src/
# dscribe ships no linux/arm64 wheel, so the arm64 build compiles its sdist.
RUN apt-get update \
    && apt-get install --no-install-recommends -y g++ \
    && rm -rf /var/lib/apt/lists/*
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra http --no-editable
COPY scripts/export_workbench_openapi.py ./scripts/export_workbench_openapi.py
RUN /app/.venv/bin/python scripts/export_workbench_openapi.py --output /build/openapi.json
RUN /app/.venv/bin/goldilocks assets install workbench \
    && /app/.venv/bin/goldilocks assets verify workbench

FROM node:26.9.0-bookworm-slim@sha256:582460f614631b59b824ac6020533b9bf339c7fdf3a6d7db31abb6b4065f0212 AS workbench-build
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY web/ ./
COPY --from=core-build /build/openapi.json ./openapi.json
RUN npm run generate:schema && npm --ignore-scripts run build

FROM python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 AS runtime
LABEL org.opencontainers.image.title="Goldilocks Workbench" \
      org.opencontainers.image.description="Guided DFT input recommendation with bundled runtime assets" \
      org.opencontainers.image.source="https://github.com/stfc/goldilocks-core" \
      org.opencontainers.image.licenses="BSD-3-Clause AND CC-BY-3.0 AND CC-BY-4.0 AND CC-BY-SA-4.0 AND GPL-2.0-or-later AND GPL-3.0-only" \
      org.opencontainers.image.license-notice="See /usr/share/licenses/goldilocks-core and /opt/goldilocks/assets"

RUN rm -f /etc/apt/sources.list.d/debian.sources \
    && printf '%s\n' 'deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/20260801T000000Z bookworm main' > /etc/apt/sources.list \
    && apt-get update \
    && apt-get install --no-install-recommends -y libgomp1=12.2.0-14+deb12u1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system goldilocks \
    && useradd --system --gid goldilocks --home-dir /app goldilocks

ENV PATH=/app/.venv/bin:$PATH \
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

USER goldilocks
EXPOSE 8000
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3)"]

CMD ["goldilocks", "serve", "http", "--host", "0.0.0.0", "--port", "8000"]
