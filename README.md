# goldilocks-core

`goldilocks-core` recommends DFT parameters and generates Quantum ESPRESSO SCF inputs from crystal structures, calculation intent, operator hints, and pseudopotential metadata.

It provides:

- structure analysis and provenance-backed scientific advice;
- model- or hint-driven k-point selection;
- deterministic pseudopotential selection and QE input generation;
- a typed DAG runtime that computes only the records a caller requests;
- preset and query APIs exposed through Python, CLI, HTTP, and MCP;
- the Goldilocks Workbench browser application in `web/`.

## Install

This project uses [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

For development dependencies:

```bash
uv sync --group dev
```

The HTTP and MCP servers are optional:

```bash
uv sync --extra http
uv sync --extra mcp
```

## Runtime model

A **stage** is a pure function that produces one typed record from upstream records and a per-run context. A **task** selects the stages for a calculation type. The built-in `scf_single_point` task is a dependency graph rather than a fixed sequence:

```text
Structure ─┬─> Analyze ─> Advise ─> Select ─┐
           └─> Kmesh ───────────────────────┼─> Generate
Structure ──────────────────────────────────┘
```

Analyze and Kmesh can run as independent roots after structure loading. Select depends on Structure and Advice, not Kmesh. Generate depends on Structure, Advice, Select, and Kmesh.

The executor infers dependencies from stage input and output types, resolves the minimal subgraph for requested outputs, and memoizes each record within the run. `CoreRuntime` owns the executor and reusable model state, builds the run context from request data and runtime services, and exposes preset and query entrypoints.

## Python API

Named **presets** return a complete `CoreResult`:

```python
from goldilocks_core import CalculationHints, recommend

result = recommend(
    "structure.cif",
    hints=CalculationHints(k_grid=(4, 4, 4)),
)

print(result.analysis.reduced_formula)
print(result.k_points.grid)
print(result.k_points.provenance.source)
```

- `recommend(...)` computes analysis, advice, k-points, and pseudopotential selection.
- `generate(...)` adds generated files and can publish them when `output_dir` is set.

```python
from goldilocks_core import CalculationHints, generate
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata

result = generate(
    "structure.cif",
    hints=CalculationHints(k_grid=(4, 4, 4)),
    pseudo_metadata=load_pseudo_metadata("path/to/pseudopotentials"),
    output_dir="run/",
)

print(result.generated_files[0].path)
print(result.bundle.path)
```

A **query** requests any supported subset of records and returns `CoreRecords`:

```python
from goldilocks_core import CoreJobRequest, CoreRuntime
from goldilocks_core.contracts import KPointSelection, StructureAnalysisRecord

request = CoreJobRequest(structure="structure.cif")
with CoreRuntime() as runtime:
    records = runtime.compute(
        (StructureAnalysisRecord, KPointSelection),
        request,
    )

print(records[StructureAnalysisRecord].reduced_formula)
print(records[KPointSelection].grid)
```

`run_core_job(request, runtime=...)` provides one dispatch surface: `CoreJobRequest.mode` selects a preset, while `CoreJobRequest.outputs` selects a query. Reuse one `CoreRuntime` across jobs to reuse loaded models.

## CLI

The CLI exposes the same two presets and query operation:

```bash
uv run goldilocks-core recommend structure.cif --k-grid 4 4 4 --json
uv run goldilocks-core generate structure.cif \
    --pseudo-root path/to/pseudos --k-grid 4 4 4 --out run/ --json
uv run goldilocks-core compute structure.cif \
    --outputs StructureAnalysisRecord,KPointSelection --k-grid 4 4 4
```

Example structures are installed with the package:

```bash
uv run goldilocks-core recommend "$(uv run goldilocks-core examples path)/Si.cif" --json
```

The standalone model-oriented entrypoint remains available:

```bash
uv run goldilocks-kmesh structure.cif --model path/to/model.joblib
```

## Transports

All transports share `CoreJobRequest` deserialization and the same runtime behavior:

- CLI: `recommend`, `generate`, and `compute` subcommands.
- HTTP: `GET /health`, `GET /tasks`, `POST /structure/load`, `POST /recommend`, `POST /generate`, and `POST /compute`. The HTTP surface is browser-safe: it accepts only inline structure content and never server paths, `pseudo_root`, or `output_dir`.
- MCP: `recommend`, `generate`, and `compute` tools, which keep the Python/CLI path capabilities (`pseudo_root`, `output_dir`).

Each server process reuses one `CoreRuntime` so model state survives across requests. See the [transport reference](docs/transport.md).

## Workbench

This repository is a monorepo. `src/goldilocks_core/` is the independently installable Core package (this package); `web/` is the independently built **Goldilocks Workbench**, a browser application for loading structures, reviewing recommendations and provenance, overriding supported hints, and downloading a reproducible input archive. Core must never depend on the Workbench.

The Workbench has two views backed by one tab-lifetime workspace:

- **Guided view:** load structure → recommend → review/override → generate ZIP.
- **Graph view:** inspect the backend-owned Task Graph, select output records, and run the selection.

The browser sends inline structure content only; all scientific truth — structures, task graphs, records, validation, provenance — is owned by Core.

### Develop the Workbench

From `web/`, after `npm ci`:

```bash
npm run dev          # Vite dev server proxying Core on http://localhost:8000
npm run test:run     # Vitest (Workspace, presenters, archive, client)
npx playwright test  # browser workflows against a real backend
npm run lint         # ESLint
npm run typecheck    # strict TypeScript
npm run verify:api   # fail on generated-contract drift
npm run build        # production bundle
```

Run the Core HTTP transport for development in another terminal:

```bash
uv sync --extra http
uv run goldilocks-core serve http --host 127.0.0.1 --port 8000
```

The Vite dev server proxies `/health`, `/structure`, `/tasks`, `/recommend`, `/generate`, and `/compute` to the local FastAPI app. Production serves the Vite build from FastAPI under the same origin, so no CORS is configured.

### Run the container

Build one stateless container that serves both Core and the built Workbench under one origin:

```bash
docker build -t goldilocks-core:workbench .
docker run -p 8000:8000 \
    -v /host/pseudos:/data/pseudos:ro \
    -e GOLDILOCKS_PSEUDO_ROOT=/data/pseudos \
    goldilocks-core:workbench
```

Mount administrator-owned pseudopotential metadata under `/data`; the browser never supplies server paths. See the `Dockerfile` and the [transport reference](docs/transport.md) for configuration and deployment scope.

## Documentation

- [Tutorial](docs/tutorial.md)
- [DAG and stage behavior](docs/pipeline.md)
- [Scientific conventions](docs/conventions.md)
- [CLI reference](docs/cli.md)
- [HTTP and MCP transports](docs/transport.md)
- [Architecture and extension points](docs/architecture.md)

## Development

```bash
uv run pytest
uv run pytest -m integration
uv run pytest -m physics
uv run pytest --cov --cov-report=term-missing
uv run mutmut run --max-children 4
uv run pre-commit run --all-files
```

Tests use synthetic structures, temporary files, small UPF snippets, and fake models. They must not depend on private datasets or machine-specific paths.

## Licence

Code is licensed under the [BSD 3-Clause License](LICENSE).

Documentation under `docs/` and the example structures under `examples/` are licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

Bundled and user-supplied pseudopotentials carry their own upstream licences.
