# Architecture

Goldilocks Core turns a structure and calculation intent into DFT input files.
The built-in workflow currently generates Quantum ESPRESSO SCF input. The data
flow is staged so later calculation types can reuse analysis, advice, resource
selection, and output handling.

```text
Load -> Analyze -> Advise
Load -> Kmesh
Load + Advice -> Select
Load + Advice + Select + Kmesh -> Generate
Analysis + Advice + Kmesh + Select + Generate -> DFT Input Data
```

The executor resolves this dependency graph from typed stage inputs and
outputs. Stages are functions with no stage base classes; only source and asset
resolution, input rendering, and publication touch the filesystem.

## Modules

| Module | Responsibility |
| --- | --- |
| `assets/` | Immutable asset records, profiles, download integrity, transactional installation, and verification. |
| `ml/model_registry.py` | Complete model runtime configuration and model asset declarations. |
| `ml/models.py` | `ModelSpec` and feature-vector records for registered models. |
| `pseudo/registry.py`, `pseudo/import_*` | Complete pseudopotential table declarations and provider-specific normalization. |
| `pseudo/metadata.py` | The pseudopotential metadata record and its cutoffs. |
| `pseudo/source.py` | One source-resolution interface for request metadata, operator roots, and installed tables. |
| `provenance.py`, `types.py`, `validation.py` | Shared provenance record, shared type vocabulary, and operator-input validators. |
| `calculation.py` | `CalculationIntent`, `CalculationHints`, and the per-stage hint views. |
| `request.py` | `CalculationDraft`, `ComputeRequest`, and selection records. |
| `result.py` | `ComputationResult` and the `Records` mapping. |
| `serialization.py` | `to_jsonable` (complete form) and `to_portable` (publication/CLI projection). |
| `runtime/graph.py` | Stage-agnostic, type-keyed DAG executor (`TaskGraph`/`Stage`/`Preset`/`execute`) and its capability records. |
| `runtime/task.py` | `GraphHandler`: a task graph, context builder, and factual warning collector. |
| `runtime/scf.py` | The SCF Calculation Task, stage graph, Presets, context, and warning collection. |
| `runtime/models.py` | `Runtime`: kmesh/metallicity model lifecycle (load/reset/close), exposed as read-only services. |
| `runtime/dispatch.py` | `Dispatcher`: task registry and dispatch by `intent.task` through `GraphHandler`s. |
| `runtime/registry.py` | Stable record-ID registry and output-type resolution shared by transports. |
| `runtime/capabilities.py` | Discovery records and the `Capabilities` assembly. |
| `runtime/jobs.py` | Short-lived `compute` convenience entry point. |
| `runtime/service.py` | `Service`: process-owned lifecycle, locking, Capabilities, Structure Inspection, Compute, and publication. |
| `io/structures.py` | One Structure Source normalization path for Inspection and Compute. |
| `analysis.py` | Structure facts. |
| `advice/` | Scientific and numerical recommendations. |
| `kmesh/` | K-point resolution and mesh mathematics. |
| `selection.py` | Pseudopotentials and cutoffs. |
| `generation/` | Calculation-specific file generation. |
| `generation/files.py` | The `GeneratedFile` record shared by writers and the registry. |
| `input_data.py` | Assembly of complete DFT Input Data from trusted Records and asset references. |
| `publication.py` | One deterministic Ready-to-run Output layout for directories and ZIP archives. |
| `server/request.py` | Shared HTTP/MCP conversion into Core Records. |
| `server/wire.py` | Strict request shapes and mechanically derived Core response schemas. |
| `server/http.py`, `server/http_contract.py` | Optional HTTP lifecycle, errors, and scientific route adapter. |
| `server/mcp.py` | Optional local stdio MCP adapter. |
| `server/readiness.py` | Cached asset readiness for the Workbench profile. |
| `web/` | React structure workspace, generated OpenAPI types, and browser-owned transient UI state. |
| `Dockerfile` | One production image containing matching Core, Workbench, and pinned runtime assets. |

Stages communicate through dataclasses. They do not need to inherit from a Core
class, and callers can invoke any stage function directly.

## Standard workflow

`ComputeRequest` carries a `CalculationDraft` and exactly one
`PresetSelection` or `RecordSelection`. `Service.compute` dispatches it
concurrently over a process-owned `Runtime`; shared model backends
synchronize only their first lazy load, so model state is safe to reuse.
`recommend` and `generate` are DAG Preset IDs only.

```python
request = ComputeRequest(
    CalculationDraft(PathStructureSource("Fe.cif")),
    PresetSelection("generate"),
)
with Service() as core:
    result = core.compute(request, output=DirectoryOutput("run"))
```

The built-in `scf_single_point` Calculation Task provides `recommend` and
`generate` Presets. Explicit Record selection executes only the required
subgraph. The generic dispatcher constructs every `ComputationResult`; Task
Handlers supply context and collect factual warnings.

## Transport adapters

Python, CLI, HTTP, and MCP expose Capabilities, Structure Inspection, and
Compute. `server/request.py` converts strict transport shapes into Core
Records; Core constructors validate domain values once. Responses serialize
Core Records mechanically through the portable projection.

HTTP accepts inline structures and stable Pseudopotential Set IDs. Compute
returns one multipart response containing the canonical `ComputationResult`
and, when the Result contains complete DFT Input Data, ZIP bytes produced from
that same execution. HTTP never accepts or creates a server output directory.
HTTP Compute handlers execute concurrently over one process-owned Runtime.
Task Graph declarations are immutable, execution state is request-local, and
shared models synchronize only their first lazy load.

Local MCP accepts inline structures and supports server-chosen automatic
publication or memory output. HTTP and MCP may carry a stable registered
Pseudopotential Set ID, but never structure paths, pseudopotential roots or
metadata payloads, model locations, or publication paths. Python and CLI own
trusted local filesystem controls. HTTP and MCP remain optional imports.
OpenAPI is exported from the application, and the Workbench imports generated
TypeScript declarations from that document.

## Runtime assets

Models and pseudopotential tables share one lifecycle, not one scientific
registry:

```text
domain registry -> download -> verify sources -> prepare -> inventory
                -> atomic publish -> resolve verified local paths
```

Each domain owns its complete declarations and interpretation. `AssetStore`
owns only acquisition, integrity, locking, installed manifests, and path
resolution. PseudoDojo and SSSP preparers convert different upstream layouts
to the same installed table manifest. `PseudoSource` owns source
precedence, verifies exact installed table identities against scientific
requirements, and returns metadata through one narrow interface. Select has no
registry or filesystem knowledge. Model loaders likewise receive verified
local paths and perform no network access.

The canonical store is external to the package. Its root is
`$GOLDILOCKS_ASSET_ROOT` when set, otherwise
`$XDG_DATA_HOME/goldilocks/assets`, falling back to
`~/.local/share/goldilocks/assets`. Immutable versions are published at
`<root>/<asset-id>/<version>/`; temporary downloads and source archives are
removed after installation. A shipped runtime profile pins exact asset IDs and
versions. Installed tables are resolved lazily by the SCF graph; transport
deserialization performs no asset-store I/O. Analyze uses the installed default
metallicity classifier when available and falls back to structure-only
heuristics when that asset is absent or the structure is disordered. The CLI installs assets only
through explicit lifecycle commands or `--fetch-missing`, which installs the
exact missing dependency Core reported. See
[Pseudopotential tables](pseudopotentials.md) for the normalized table layout
and licensing model.

## Boundaries

Validate where data enters or causes side effects:

- request records validate operator controls and external pseudopotential
  metadata;
- source adapters validate provider data before producing internal records;
- generators reject unsupported or incomplete inputs before rendering;
- publication writes atomically to new destinations and confines logical paths.

Intermediate records remain ordinary Python data. Custom stage authors are
responsible for returning coherent records; Core does not defensively re-check
every possible malformed internal object.

Scientific choices belong in Analyze, Advise, Kmesh, and Select. Select
resolves the configured source and chooses a concrete pseudopotential per
element without making scientific policy beyond the stated requirements.
Generate maps completed choices to calculation syntax. Optional publication
writes complete DFT Input Data but does not run calculations.

Runner/AiiDA workflows, schedulers, authentication, and completed-output
analysis are outside this repository. Browser state belongs in `web/` and does
not enter Core Records. HTTP and MCP do not add queues, persistence, sessions,
or pod management.

## Workbench and production image

Workbench loads Capabilities once, sends inline Structure Sources to Inspection,
and stores its mutable Calculation Draft in the browser. A successful Compute
stores the immutable Result and exact optional archive returned by that one
execution. Editing the Draft leaves the Result visible but out of date and
disables its archive. Download uses the already prepared bytes; the server stores
no Result or archive.

The production image builds Workbench assets, installs every registered runtime
asset, verifies that profile during the image build and readiness checks, then
runs as the unprivileged `goldilocks` user. FastAPI serves the static Workbench
and Core routes from one origin.

## Engineering invariants

These are load-bearing. Changing them without intent will break import
boundaries, concurrency safety, or the task extension model.

- The SCF handler registers lazily on first dispatch so importing
  `runtime.dispatch` does not pull in stage implementations or their
  `ml.*` dependencies. Explicit registration wins over the default.
- Code inside the package and the tests import from the module that
  defines a name — for example
  `from goldilocks_core.kmesh.resolve import resolve_kpoints` — not from
  a package `__init__`. Only library users import from `goldilocks_core`
  itself. This keeps each import cheap: it loads the module you asked
  for, not the whole package.
- Serialization has one policy and two serializers: `to_jsonable` is the
  complete form for tests and internals; `to_portable` is the portable
  projection for publication and CLI output, dropping host-local paths
  and licence text. The archive manifest and CLI `--json` serialize
  through `to_portable`, so identical computations produce identical
  bytes on any machine.
- `Service` executes Computations concurrently over one process-owned
  `Runtime`. Model backends synchronize only their first lazy load, and the
  `Dispatcher` synchronizes lazy default-task registration.
- The top-level `compute` convenience reuses a caller-owned runtime when given
  one and otherwise closes its owned runtime after one call.
- The runtime imports no task-specific code. New tasks bring their own
  context and stage graph; they do not edit the generic executor.
- Importing `goldilocks_core` never imports FastAPI or the MCP SDK.
  The `[http]` and `[mcp]` extras are lazy boundaries.
- `server/wire.py` rejects unknown fields and bad transport types;
  `server/request.py` constructs Core Records without revalidating them.
- `DimensionalityClassificationError` is an `Exception`, not a
  `ValueError`, so HTTP maps it explicitly to 422.
- MCP maps only known stage errors to `ToolError`; internal defects
  remain unhandled.