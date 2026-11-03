# Workbench

Upload a CIF or POSCAR, choose settings, and generate Quantum ESPRESSO inputs in
your browser. Review the recommendations, then download the input bundle. The
[quickstart](../docs/quickstart.md#4-run-quantum-espresso) explains how to run
the extracted calculation.

## Run locally

From the repository root, with
[uv](https://docs.astral.sh/uv/getting-started/installation/) and Node.js 24 or
newer installed:

```bash
uv sync --extra http
npm --prefix web ci
uv run goldilocks assets install workbench
uv run --extra http poe workbench
```

The asset step installs the models and pseudopotential tables. The final command
starts the backend on port 8000 and the frontend on port 5173.
Open **http://127.0.0.1:5173**.

To serve a built frontend instead, stop those servers and run:

```bash
uv run --extra http poe stage
```

Then open **http://127.0.0.1:8000**.

### Troubleshooting

- **Running more than one instance at once (port 8000 already in use)**:
  `poe serve`/`poe stage`/`poe workbench` all hardcode port 8000 and refuse to
  start a second time. To run an extra instance alongside another one, bypass
  `poe` and call the CLI directly with a different port:

  ```bash
  uv run goldilocks assets install workbench
  uv run goldilocks serve http --host 127.0.0.1 --port 8001 --static-root web/dist
  ```

- **"Request failed" / a 502 in the browser**: the frontend is up but the
  backend (`goldilocks serve http`) isn't — it was never started, crashed, or
  got stopped separately from the frontend dev server. Restart it (see above)
  and retry.

- **Page doesn't load, or shows the wrong app, on port 5173**: another local
  project's dev server can already be bound to 5173 on a different IP family
  (for example IPv6-only `::1`), so it won't collide loudly with Vite's own
  `127.0.0.1:5173` bind at startup — but `http://localhost:5173` can resolve
  to _either_ one depending on your OS's IPv6/IPv4 preference. Always open
  **http://127.0.0.1:5173** explicitly (not `localhost`) to be sure you're
  reaching this project's Workbench.

## Enable mMACE-based magnetism features

Two Workbench features (the ML `is_magnetic` classification and the
"Run mMACE" magnetic-ordering ranking button) run on the ~80.5 MB mMACE
backbone, which `goldilocks assets install workbench` above installs with the
`is_magnetic` classifier (see [mMACE setup](../docs/mmace-setup.md)).

Load a magnetic structure and check the **Analysis** column's "is magnetic"
field: its caption reads **"Goldilocks-ML prediction"** once the `ml` tier is
live. Without the asset both features still work, just at a lower tier
(LLM/heuristic classification, unranked ordering list) — never a failure.

"Run mMACE" ranks in a separate backend process, so you can keep editing
settings while it runs; a ranking can take minutes. Opening another structure
abandons the ranking in the Workbench, but the backend still finishes it.

## Run in Docker

Alternatively, build and run from the repository root:

```bash
docker build --tag goldilocks-workbench .
docker run --rm --publish 127.0.0.1:8000:8000 goldilocks-workbench
```

Open **http://127.0.0.1:8000**. The image includes the frontend and runtime
assets. See [HTTP security](../docs/cli.md#http-security) before exposing it
beyond localhost.

## Development

```bash
npm --prefix web run check
```

This runs formatting, lint, tests, and the build. With the built frontend served
on port 8000, run `npm --prefix web run test:e2e` for real-browser checks.
`web/openapi.json` and `web/src/api/schema.d.ts` are ignored build products.
The frontend `dev`, `lint`, `test`, `test:e2e`, `build`, and `check` commands
regenerate them from the local Python package before running. Install the Python
HTTP dependencies first with `uv sync --frozen --extra http`; schema export needs
neither a running server nor installed model assets.

After changing the HTTP contract, use `npm --prefix web run generate:api` if you
only need to refresh the generated files.
