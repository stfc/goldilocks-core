# Workbench (web/)

The Goldilocks Workbench is a React single-page client of the Core HTTP
transport. It owns no state the server keeps: capabilities load once, the
calculation draft lives in the browser, and each compute response's result
and archive bytes are held only for the current view.

## Run it

One task does the backend steps and starts both processes — assets install,
Core HTTP backend on :8000, Vite dev server on :5173 (assumes `npm ci` has
run once in `web/`):

```bash
uv sync --all-extras
uv run poe workbench
```

Or run the two processes by hand:

```bash
uv sync --all-extras
uv run goldilocks assets install workbench
uv run goldilocks serve http --host 127.0.0.1 --port 8000
```

```bash
cd web
npm ci
npm run dev
```

The dev server runs on `http://127.0.0.1:5173` and proxies `/capabilities`,
`/inspect`, `/compute`, `/health`, `/ready`, and `/openapi.json` to the
backend on port 8000 (see `vite.config.ts`).

To exercise the compiled bundle against the backend without the Vite dev
server (builds the bundle, then serves it via `serve http --static-root`):

```bash
uv run poe stage
```

## Checks

```bash
npm run lint        # eslint, zero warnings allowed
npm run test        # vitest unit tests
npm run build       # tsc -b && vite build
npm run check       # lint + tests + build
npm run test:e2e    # Playwright against a real server
```

The API contract is generated, never hand-edited. Regenerate both artifacts
from the running package and commit them together with backend changes:

```bash
npm run generate:api
```

`npm run check:api` regenerates and fails on any drift between the exported
OpenAPI document, the generated TypeScript types, and the committed files.
CI enforces the same drift check.