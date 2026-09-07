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

This runs formatting, lint, tests, and the build. See the contributor guide for
[browser tests](../docs/architecture.md#run-browser-tests) and
[API schema updates](../docs/architecture.md#change-the-http-or-browser-contract).
