# Workbench (web/)

The Goldilocks Workbench is a React single-page client of the Core HTTP
transport. It owns no state the server keeps: capabilities load once, the
calculation draft lives in the browser, and each compute response's result
and archive bytes are held only for the current view.

Scientific record cards show labelled values, units, decision reasons, and
provenance.
The pseudopotential dropdown follows the selected functional and accuracy;
changing either resets an explicit table to Automatic. Core validates the
selected table when computing.

Mantine owns component appearance and layout primitives. The gold theme and
responsive two-panel workflow remain; custom CSS is limited to panel/input
resizing and accessibility rules. Scientific records and workspace operations
remain independent of component styling.

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
npm run format      # apply Prettier formatting
npm run format:check # verify formatting without edits
npm run lint        # strict type-aware ESLint, zero warnings allowed
npm run test        # Vitest unit and integration tests
npm run build       # tsc -b && vite build
npm run check       # formatting + lint + tests + build
npm run test:e2e    # Playwright against a real server
```

Tests live under `tests/`: `unit/` for isolated scientific presentation,
`integration/` for UI, workspace, and HTTP contracts, `e2e/` for real-server
browser workflows, and `support/` for shared fixtures and setup.

Mantine owns interactive components and the shared theme. ESLint enforces
cyclomatic and cognitive complexity limits of 15, nesting depth of 3,
no nested ternaries, React Hooks correctness, and static accessibility.
Focusable ARIA window splitters have a documented exception to the accessibility
plugin's non-interactive-element rule; browser tests exercise their keyboard behavior.
ESLint is pinned to version 9 because the accessibility plugin's peer range
does not yet include version 10; npm currently marks that ESLint release unsupported.

The API contract is generated, never hand-edited. Regenerate both artifacts
from the running package and commit them together with backend changes:

```bash
npm run generate:api
```

`npm run check:api` regenerates and fails on any drift between the exported
OpenAPI document, the generated TypeScript types, and the committed files.
CI enforces the same drift check.
