# Architecture

This page is for contributors changing Core or its transports. For using the
library, start with the [Python tutorial](tutorial.md); for browser development,
use the [Workbench guide](../web/README.md).

## Set up a contribution

From the repository root:

```bash
uv sync --group dev
uv run pre-commit install
uv run poe check
```

`poe check` runs Ruff lint, format, and complexity checks, then pytest. Use
`uv run poe fmt` to apply Python formatting. The commit hooks run the same checks
and pytest with branch coverage. For frontend checks and API-schema refresh, follow the
[Workbench guide](../web/README.md).

## Cut a release

One version covers the repository: `pyproject.toml` owns it, and the Workbench
frontend ships inside the same image rather than carrying its own version.
Treat API/schema changes (the OpenAPI export) as at least a minor bump during
`0.x`; frontend-only fixes can be patches.

To publish, merge a PR that bumps `pyproject.toml` to the release version, then
from `main`:

```bash
git tag -a v0.1.0 -m "v0.1.0"
git push origin v0.1.0
```

CI runs the full suite on the tagged commit, then pushes
`ghcr.io/stfc/goldilocks-workbench` with `X.Y.Z`, `X.Y`, `X`, and `latest` tags,
and creates a GitHub Release containing the sdist and wheel. Nightly builds of
`main` publish `nightly` and `nightly-<date>` image tags at 03:00 UTC; PRs and
plain `main` pushes publish nothing. Keep the tag and `pyproject.toml` version
identical — nothing else validates the pairing.

## Follow a request

`Service` exposes three operations: `capabilities`, `inspect_structure`, and
`compute`. It reuses a `Runtime` containing model backends and an asset store.
The top-level `compute(ComputeRequest)` convenience creates and closes a service
for one call unless a caller-owned runtime is supplied.

A compute request follows this path:

1. `CalculationDraft` holds the structure source, calculation intent, optional
   overrides, and asset choices. `ComputeRequest` pairs it with a preset or
   explicit record selection.
2. `Dispatcher` finds the task handler by `intent.task` and resolves the
   requested outputs.
3. `io/structures.py` normalizes the source through the same path used by
   inspection. The handler builds a request-local context from that structure,
   request, and runtime.
4. The graph executor runs the stages needed to produce the requested records,
   once per stage and in dependency order.
5. `Dispatcher` creates a `ComputationResult` with the requested records,
   normalized draft, task revision, and warnings from all executed stages.
6. If an output target is supplied, `Service` publishes complete input data
   through `Publisher` and attaches publication metadata.

Python compute defaults to no publication. CLI and MCP adapters choose automatic
directory publication by default. HTTP computes without an output target and
builds ZIP response bytes separately from the same result.

## Understand the built-in workflow

`runtime/scf.py` declares the `scf_single_point` graph:

```text
Load -> Analyze -> Advise
Load -> Kmesh
Load + Advice -> Select
Load + Advice + Select + Kmesh -> Generate
Analysis + Advice + Kmesh + Select + Generate -> DFT Input Data
```

`recommend` selects analysis, advice, k-points, and pseudopotential selection.
`generate` adds generated files and complete input data. They are presets within
a task, not separate service operations.

Stages are ordinary functions. Their outputs are keyed by types in a
request-local dictionary; scientific records are plain dictionaries described by
domain-owned `TypedDict` shapes. These types and named tuple aliases key the
record map. The load stage supplies a pymatgen `Structure`. The result contains
only selected records; warning collection can inspect intermediate outputs.

Keep scientific decisions in their owning stages:

- **Analyze** reports structure facts and estimated electronic character.
- **Advise** recommends parameters with reasons and provenance.
- **Kmesh** resolves an explicit grid, spacing, or model recommendation.
- **Select** chooses concrete pseudopotentials satisfying the requirements.
- **Generate** translates completed choices into target-code syntax.
- **DFT Input Data** combines the records and immutable byte snapshots of
  structures, generated files, and selected assets needed for publication.

## Find the code to change

Paths below are relative to `src/goldilocks_core/` unless stated otherwise.

| Area                | Files and responsibility                                                                                                                                                                                                               |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Python contracts    | `calculation.py`, `request.py`, `result.py`: validating input dataclasses and computation results.                                                                                                                                     |
| Execution           | `runtime/graph.py`: dependency traversal; `runtime/dispatch.py`: `GraphHandler`, registration, and result assembly; `runtime/scf.py`: built-in graph.                                                                                  |
| Service lifecycle   | `runtime/service.py`: reusable native and document operations, one-call convenience, and expected-failure classification; `runtime/models.py`: shared model lifecycle and request-local model resolution.                              |
| Input and discovery | `io/structures.py`: source normalization and inspection; `runtime/capabilities.py`: available tasks, models, tables, and defaults; `runtime/registry.py`: stable record IDs.                                                           |
| Scientific behavior | `analysis.py`, `advice/`, `kmesh/`, `selection.py`: facts, recommendations, grids, and pseudopotential selection.                                                                                                                      |
| Assets              | `assets/`: installation and integrity; `ml/models.py`: model declarations; `pseudo/registry.py` and `pseudo/import_*`: table declarations and provider normalization; `pseudo/source.py`: selection and deferred publication material. |
| Output              | `generation/`: target-code writers; `input_data.py`: complete input assembly; `publication.py`: directory and ZIP layout; `serialization.py`: JSON projections.                                                                        |
| Transports          | `cli/core.py`: local commands; `server/documents.py`: strict native request conversion and derived response schemas; `server/http.py` and `server/mcp.py`: adapters; `server/readiness.py`: cached asset checks.                       |
| Browser             | Repository `web/src/api/`: HTTP client and generated types; `web/src/workspace/`: draft, request, result, and download state.                                                                                                          |

## Extend a workflow

### Add a task or stage

Use `runtime/scf.py` as the working example. Define a `TaskGraph` with stages,
presets, selectable outputs, and stable IDs for new record types. Wrap it in a
`GraphHandler` providing `build_context` and `collect_warnings`, then pass it
through `Service(task_handlers=(handler,))`.

A stage declares its input types, output type, and callable. The executor passes
dependency values positionally and the task context as `ctx`. It rejects
duplicate producers when constructing a graph, and missing producers or cycles
when resolving requested outputs. Task registration also checks stage IDs,
preset names, and record IDs.

Add task-specific dependencies to the context, not the generic executor.
Explicit task registration takes precedence over the lazily registered SCF
default. Transport-facing records need domain-owned shapes and portable field
annotations; registering a record ID alone does not define its public schema.

### Add an input writer

Implement the writer in `generation/` and register its `(code, task, writer)`
entry in `generation/registry.py`. Writers receive the structure and completed
advice, selection, and k-point records, and return file documents with path,
content, and role. They should reject unsupported combinations before rendering,
rather than inventing scientific choices. The current registry contains the
Quantum ESPRESSO SCF writer.

### Add a model or pseudopotential table

Keep scientific metadata and provider-specific preparation in the model or
pseudopotential registry. `AssetStore` handles acquisition, integrity,
installation, and verified path resolution. `pseudo/source.py` resolves explicit
metadata, a local root, or a compatible installed table; the selection function
consumes the resulting metadata.

Model backends load installed files lazily. Missing optional metallicity assets
permit a heuristic fallback; missing required assets raise an asset error.
Scientific operations do not install assets. Installation is explicit through
asset commands or the CLI's `--fetch-missing` retry. See
[pseudopotential tables](pseudopotentials.md) for layout and licensing
requirements.

Independent assets install concurrently with at most eight workers. Results
retain profile order; each asset retains its own lock, checksum verification,
staging directory, and atomic publication.

`CalculationResources` binds request-local pseudo and model resolutions.
Selection-only computations do not read publication content. For complete input
data, resolvers supply verified byte snapshots and exact metadata; assembly
combines these with completed records rather than rediscovering sources.

## Preserve the boundaries

- **Validate at entry and side effects.** Input constructors validate domain
  controls; transport models reject unknown fields and incorrect types; provider
  adapters validate imported data. Internal stage documents are trusted, so
  custom stages must return coherent values.
- **Keep execution state request-local.** Graph declarations are frozen
  dataclasses, but record dictionaries are mutable. Do not share or mutate a
  previous request's records. HTTP requests can overlap over one runtime;
  backend locks protect lazy initialization rather than serializing complete
  computations. Close or reset the runtime only after its callers have finished.
  Model configuration is cached for each backend's lifetime; reset releases
  loaded model resources without rereading configuration.
  Publication uses the identity and legal references cached with each loaded
  model, not a fresh registry read. The QRF feature classifier and standalone
  metallicity classifier retain separate snapshots. Unused models are not
  loaded for publication.
- **Respect resource ownership.** A service closes the runtime it creates, not a
  runtime supplied by its caller. Optional HTTP and MCP libraries load at their
  transport boundaries rather than on `import goldilocks_core`.
- **Preserve record IDs.** Python results use type keys; portable results use
  stable string IDs. `to_jsonable` provides the complete representation, while
  `to_portable` applies record-specific projections for publication and
  transport output.
- **Publish through one implementation.** Resource resolvers verify external
  files and snapshot their bytes; publication never rereads the asset store.
  `Publisher` validates logical paths, hashes each file once for `goldilocks.json`,
  and builds matching directory and ZIP contents. Private staging and a
  no-replace rename protect existing destinations, not against a hostile process
  controlling the destination parent. Generated input files alone are insufficient
  for publication.
- **Keep remote callers away from local paths.** HTTP and MCP accept inline
  structures and registered table IDs, not filesystem sources, model locations,
  or publication paths. Keep authentication and deployment controls explicit;
  see [CLI transport security](cli.md#http-security).
- **Keep imports direct.** Package code imports from the module defining a name.
  The top-level `goldilocks_core` exports are for library users.
- **Classify expected failures once.** Domain exceptions implement
  `ExpectedFailure` from `failures.py` with a category and safe public description.
  Native operations retain exception identities; document operations classify
  failures for adapters. Unexpected execution defects propagate.

## Complexity gates

`scripts/check_complexity.py` runs in contributor checks, hooks, and CI. Its AST
import ceiling applies to every production owner: 12 project origin modules and
24 imported symbols, with stricter limits for CLI, HTTP, MCP, assembly, and SCF.
It counts local and type-only imports, resolves re-exports, and counts accessed
module-alias members. Pure export packages are transparent to consumer counts.
The same gate runs Ruff's McCabe check: at most 10 per production function,
ignoring `noqa` suppressions. Reduce decisions and duplication; moving import
blocks or extracting shallow helper fleets does not deepen an interface.

## Change the HTTP or browser contract

`server/documents.py` converts strict request models directly into native Core
inputs and derives response schemas from domain-owned shapes and `Portable`
annotations. Document operations serialize trusted Core results without
reconstructing response models. HTTP packages result JSON and its optional ZIP;
MCP can request automatic directory publication or memory-only output.
Workbench reads file hashes and sizes from the ZIP's `goldilocks.json`.

Each transport owns one service unless a caller injects one. Loaded models and
cached asset-readiness reports are reused across requests.

Workbench keeps the editable draft and reviewed response in its browser store.
Editing a draft marks the existing result out of date and prevents downloading
its archive. Download uses the bytes returned with that result rather than
recomputing it.

After changing the wire contract, run these from the repository root with the
HTTP extra installed:

```bash
npm --prefix web run generate:api
```

`web/openapi.json` and `web/src/api/schema.d.ts` are ignored build products.
Frontend lifecycle commands regenerate them from the local Python package;
generation needs neither a running server nor installed model assets. Commit
the domain declarations, not generated copies. Docker exports OpenAPI in its
Python stage and generates TypeScript in its Node stage.

## Run browser tests

Start the [built Workbench](../web/README.md#run-locally) in another terminal,
then run:

```bash
npm --prefix web exec -- playwright install chromium
npm --prefix web run test:e2e
```

Tests use `http://127.0.0.1:8000`; they do not start a server.
`WORKBENCH_BASE_URL` selects another address.
`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` selects an existing Chromium installation.
