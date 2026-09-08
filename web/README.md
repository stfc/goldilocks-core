# Workbench

Upload a CIF or POSCAR, choose settings, and generate Quantum ESPRESSO inputs in
your browser. Review the recommendations, then download the input bundle.
Run Quantum ESPRESSO from the extracted archive root with `pw.x -in inputs/qe.in`.

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

## Run in Docker

Alternatively, build and run from the repository root:

```bash
docker build --tag goldilocks-workbench .
docker run --rm --publish 127.0.0.1:8000:8000 goldilocks-workbench
```

Open **http://127.0.0.1:8000**. The image includes the frontend and runtime
assets. The anonymous HTTP server is intended for trusted networks.

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
