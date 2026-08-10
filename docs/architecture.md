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
