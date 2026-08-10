# Architecture

Goldilocks Core turns a structure and calculation intent into typed recommendation records and DFT input files. The built-in calculation task generates Quantum ESPRESSO SCF input.

## Modules

| Module | Responsibility |
| --- | --- |
| `contracts/` | Boundary dataclasses, query output registry, and serialization. |
| `graph.py` | Stage, task, and preset specifications; type-keyed DAG execution. |
| `runtime.py` | SCF task registration, run-context construction, and model lifecycle. |
| `jobs.py` | `run_core_job` dispatch and `recommend`/`generate` convenience functions. |
| `io/structures.py` | Structure loading. |
| `analysis.py` | Structure facts and metallicity fallback. |
| `advice/` | Scientific and numerical recommendations. |
| `kmesh/`, `advisors/` | Concrete k-point selection. |
| `selection.py` | Pseudopotential and cutoff selection. |
| `generation/` | Calculation-specific file generation. |
| `bundle.py` | Optional publication of generated files and a manifest. |
| `server/` | Shared request deserialization and optional HTTP/MCP transports. |
| `cli/` | Thin command-line transport. |

## DAG executor

`StageSpec` declares three things:

- the record type it produces;
- the upstream record types it consumes;
- the pure callable that produces it.

The callable receives upstream records as positional arguments and a `RunContext` as `ctx`. Stages do not inherit from a framework class. Their dependency structure is inferred from declared input and output types.

`TaskSpec` groups the stages for one calculation type and its named `Preset` output sets. To execute a task, `execute()`:

1. indexes each stage by its output type;
2. recursively visits the producers required by the requested output types;
3. detects missing producers and dependency cycles;
4. orders prerequisites before consumers;
5. executes each required stage once and memoizes its output by type;
6. returns only the explicitly requested records in `CoreRecords`.

Memoization is per execution. Shared prerequisites such as `Structure` or `ParameterAdvice` are computed once even when several requested records depend on them. Unrelated stages are not run.

## CoreRuntime

`CoreRuntime` is the stateful owner around the otherwise pure graph:

- owns the default QRF k-mesh backend and optional metallicity model;
- lazily loads model artifacts and reuses them across jobs;
- validates that a request has a registered task;
- builds a fresh `RunContext` for each request;
- delegates minimal-subgraph execution to the graph executor;
- assembles preset outputs into `CoreResult`;
- resets or closes runtime-owned model resources.

The run context separates request data from runtime services:

- request data: structure input, calculation intent, hints, and pseudopotential metadata;
- services: k-mesh backend and metallicity classifier.

A request-level `kmesh_model` replaces the default k-mesh service for that run. `CoreRuntime.reset()` discards cached model state. `close()` releases owned resources and prevents further computation.

Runtime entrypoints are:

- `recommend(request) -> CoreResult` for the `recommend` preset;
- `generate(request, output_dir=...) -> CoreResult` for the `generate` preset;
- `compute(outputs, request) -> CoreRecords` for an arbitrary record query.

`run_core_job()` dispatches a `CoreJobRequest` to one of these operations. It creates and closes a runtime when none is supplied. Long-lived CLI servers, HTTP applications, and MCP servers retain one runtime per process.

## SCF task

The only registered task is `scf_single_point`. Its graph is:

```text
Structure input -> Structure
Structure -> StructureAnalysisRecord
Structure -> KPointSelection
StructureAnalysisRecord -> ParameterAdvice
Structure + ParameterAdvice -> SelectionRecord
Structure + ParameterAdvice + SelectionRecord + KPointSelection -> GeneratedFiles
```

In dependency terms:

- **Load** produces `pymatgen.Structure` from the run context.
- **Analyze** consumes `Structure` and produces `StructureAnalysisRecord`.
- **Kmesh** consumes `Structure` and produces `KPointSelection`.
- **Advise** consumes `StructureAnalysisRecord` and produces `ParameterAdvice`.
- **Select** consumes `Structure` and `ParameterAdvice`; it produces `SelectionRecord` without depending on Kmesh.
- **Generate** consumes `Structure`, `ParameterAdvice`, `SelectionRecord`, and `KPointSelection`; it produces `GeneratedFiles`.

Analyze and Kmesh are sibling roots after Load. A `SelectionRecord` query does not execute Kmesh. A `GeneratedFiles` query resolves every scientific branch.

The task has two named presets:

- `recommend`: analysis, advice, k-points, and selection;
- `generate`: the recommendation records plus generated files.

Preset entrypoints compose these records into `CoreResult`. Queries return the requested type-keyed `CoreRecords` without filling a result accumulator.

## Metallicity service

Analyze receives metallicity classification through `RunContext` rather than loading a model itself. This keeps the stage pure and gives `CoreRuntime` ownership of model lifecycle.

When both `GOLDILOCKS_METALLICITY_CHECKPOINT` and `GOLDILOCKS_METALLICITY_ATOM_INIT` are configured, the runtime lazily loads the CGCNN classifier and returns its electronic character and confidence. Without both artifacts, it uses the structure heuristic. `StructureAnalysisRecord` records:

- `electronic_character`;
- `electronic_character_source` (`model` or `heuristic`);
- `electronic_character_confidence` when the model supplies one;
- analysis warnings describing limitations.

The same model can be configured through `CoreRuntime` constructor arguments. Graph settings come from the QRF model registry.

## Contracts

The public contracts reflect independent graph outputs:

- `KPointSelection` is a sibling record, not part of `SelectionRecord`.
- `CoreResult.k_points` holds the concrete grid for presets.
- `SelectionRecord` contains pseudopotential selections and their warnings.
- `CoreRecords` is a mapping keyed by record type and serializes with type names as JSON keys.
- `CoreJobRequest.outputs` selects a query; when it is `None`, `mode` selects `recommend` or `generate`.
- `StructureAnalysisRecord` carries electronic-character source and confidence alongside the value.
- standalone bundle mode was removed; publication is an optional side effect of `generate` when `output_dir` is set.

Supported query output names are `StructureAnalysisRecord`, `ParameterAdvice`, `KPointSelection`, `SelectionRecord`, and `GeneratedFiles`.

## Boundaries

Validate where data enters or causes side effects:

- request records and shared transport deserialization validate operator input;
- pseudopotential selection treats metadata as untrusted;
- generators reject unsupported or incomplete inputs before rendering;
- bundle publication confines paths to a new output directory.

Intermediate records remain ordinary Python data. Stage authors are responsible for returning coherent records; Core does not revalidate deliberately corrupted internal values.

Scientific choices belong in Analyze, Advise, Kmesh, and Select. Generate maps completed choices to calculation syntax. Publication writes generated files but does not run calculations or copy pseudopotential libraries.

Runner/AiiDA workflows, schedulers, auth, frontend state, and completed-output analysis are outside this package.

The **Goldilocks Workbench** (`web/`) is a separate React module that consumes Core only through the browser-safe HTTP transport. Core never imports or depends on it. See the Workbench section below.

## Workbench

`web/` is an independently built React application. It is not a Core module: Core cannot import or depend on it. The Workbench crosses into Core only through one transport adapter (`CoreClient`), and Core is the sole authority for structures, task graphs, records, validation, and provenance.

### Deep modules

The frontend keeps scientific interaction logic in modules with narrow interfaces, each behind its own seam:

| Module | Responsibility | Seam |
| --- | --- | --- |
| `client/CoreClient` | The single entry point to Core: health, tasks, structure load, recommend, compute, generate. | Hides HTTP paths, generated schemas, status codes, and serialisation; failures cross as `CoreFailure`. |
| `client/HttpCoreClient` | The only module that knows `openapi-fetch`, the generated contract, routes, and status codes. | Maps every response to domain types and `CoreFailure`. |
| `store/workspace` | Vanilla Zustand store with narrow domain actions and selectors. | Owns transition rules, stale-state semantics, and operation-local failures; modules cannot call unrestricted `setState`. |
| `records/presenters` | Registry of record-specific presenters returning semantic sections, values, units, provenance, warnings, and raw data. | Guided and Graph views reuse the same presentations. |
| `structure/StructureViewer` | Consumes `StructureDocument` behind a library-neutral interface. | No 3D-library object or event type crosses the seam; a lazy 3Dmol.js adapter backs it, with a textual `StructureSummary` fallback. |
| `archive/InputArchive` | Turns generated inputs, the original structure, and a reproducibility manifest into one named ZIP blob with `fflate`. | Never touches server paths. |
| `errors/ErrorReport` | Presents typed failures and diagnostics. | Does not own operation state. |

Mantine is used directly for generic controls; local modules exist only where Goldilocks contributes substantial behaviour or semantics. The two views — Guided (load → recommend → override → ZIP) and Graph (inspect the backend-owned Task Graph, select records, run the selection) — share one tab-lifetime workspace.

### Typed transport seam

Backend-owned Pydantic schemas (`server/schemas.py`) define typed request/response bodies and produce useful OpenAPI. `web/scripts/export_openapi.py` and `web/scripts/api.mjs` generate committed TypeScript (`web/src/client/generated/dto.ts`) with `openapi-typescript`, consumed through `openapi-fetch` inside the HTTP adapter. The generated code is committed and never hand-edited; `npm run verify:api` fails if regeneration produces a diff.

### Backend-owned truth

Core owns canonical Structure Documents, stable Task/Stage/Record identifiers, graph dependencies and presets, selectable output records, semantic names and descriptions, transport validation, scientific results, and provenance. The Workbench owns layout, interaction, and presentation; task descriptions carry no Python callables/class names or React concepts.

### Deployment

Production serves the Vite build (`web/dist`) from FastAPI under the same origin (`server/static.py`), registered after every API route so the SPA fallback never shadows `/health` or `/tasks`. No CORS is configured. Development uses a Vite proxy to a local FastAPI app. `server/config.py` is the single deployment seam: `GOLDILOCKS_COMPUTE_LIMIT`/`_WAIT_SECONDS` bound expensive computation, and administrator-owned pseudopotential metadata (`GOLDILOCKS_PSEUDO_METADATA` or `GOLDILOCKS_PSEUDO_ROOT`) is injected into Workbench requests that supply none. A multi-stage `Dockerfile` composes matching Core and Workbench builds into one non-root container.
