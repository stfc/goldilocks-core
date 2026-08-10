# syntax=docker/dockerfile:1
#
# Goldilocks Workbench container: one stateless image serving the Vite build
# and Core's HTTP transport under a single origin (no CORS).
#
# Build and run:
#   docker build -t goldilocks-core:workbench .
#   docker run -p 8000:8000 \
#     -v /host/pseudos:/data/pseudos:ro \
#     -e GOLDILOCKS_PSEUDO_ROOT=/data/pseudos \
#     goldilocks-core:workbench
#
# The operator mounts administrator-owned pseudo metadata under /data; the
# browser never supplies server paths. Without a mount, recommendations still
# run and report "no matching pseudo" fallback selections.

# ---- Frontend: build the Workbench bundle -------------------------------
FROM node:22-alpine AS workbench-build
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build
# Emits /src/web/dist

# ---- Core: build the Python environment with the http extra -------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS core-env
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv sync --frozen --no-dev --extra http

# ---- Runtime -------------------------------------------------------------
FROM python:3.12-slim AS runtime
RUN groupadd --system --gid 10001 goldilocks && \
    useradd --system --uid 10001 --gid 10001 --home /app goldilocks && \
    mkdir -p /data/pseudos && \
    chown -R goldilocks:goldilocks /data
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    GOLDILOCKS_WEB_DIST="/app/web/dist"
COPY --from=core-env /app /app
COPY --from=workbench-build /src/web/dist ./web/dist
EXPOSE 8000
USER goldilocks
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1
# Core serves both API routes and the Workbench build on one process.
CMD ["uvicorn", "goldilocks_core.server.main:app", "--host", "0.0.0.0", "--port", "8000"]
