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
| `ml/models.py` | Model identities, registry loading, feature settings, and asset declarations. |
| `pseudo/registry.py`, `pseudo/import_*` | Complete pseudopotential table declarations and provider-specific normalization. |
| `pseudo/metadata.py` | The pseudopotential metadata record and its cutoffs. |
| `pseudo/source.py` | Request-local pseudo resolution, selection, and deferred verified publication material. |
| `provenance.py`, `types.py`, `validation.py` | Shared provenance record, shared type vocabulary, and operator-input validators. |
| `calculation.py` | `CalculationIntent` and `CalculationHints` with validating constructors. |
| `request.py` | Native drafts, requests, selections, local request construction, and request-scoped resource binding. |
| `result.py` | `ComputationResult`, publication, and preparation of portable output with its exact optional archive. |
| `serialization.py` | `to_jsonable` (complete form) and `to_portable` (publication/CLI projection). |
| `runtime/graph.py` | Stage-agnostic, type-keyed DAG executor (`TaskGraph`/`Stage`/`Preset`/`execute`) and its task-description documents. |
| `runtime/scf.py` | The SCF stage graph, Presets, and warning collection; no resource cache or registry configuration. |
| `runtime/models.py` | Shared model lifecycle and request-local model choice, identity, and legal-material snapshots. |
| `runtime/dispatch.py` | `Dispatcher` and `GraphHandler`: registration, context construction, and execution by `intent.task`. |
| `runtime/registry.py` | Stable record-ID registry and output-type resolution shared by transports. |
| `runtime/capabilities.py` | The `capabilities` document assembly (tasks, models, pseudopotential sets, defaults). |
| `runtime/service.py` | Native and document operations, resource ownership, explicit acquisition retries, and expected-failure classification. |
| `io/structures.py` | One Structure Source normalization path for Inspection and Compute. |
| `analysis.py` | The `StructureAnalysisRecord` shape and structure-fact analysis. |
| `advice/parameters.py` | Coupled scientific parameter policy and its domain-owned shapes; scalar decisions are private. |
| `advice/kdistance.py`, `advice/kindex.py` | Substantive model-backed k-point advisors. |
| `kmesh/` | K-point resolution and mesh mathematics. |
| `selection.py` | Pseudopotential selection, its domain shape, and portable projection. |
| `generation/` | Calculation-specific file generation. |
| `generation/files.py` | Generated text and snapshotted binary artifact contracts. |
| `input_data.py` | Combines completed scientific records and verified resource material into DFT Input Data. |
| `publication.py` | Publishes assembled bytes as directories or ZIPs; validates output paths. |
| `failures.py` | Expected-failure protocol with domain categories and safe public descriptions; no transport dependencies. |
| `server/documents.py` | Strict native request conversion and mechanically derived portable response schemas. |
| `server/http.py` | Optional HTTP lifecycle, routes, multipart encoding, and protocol-level errors. |
| `server/mcp.py` | Optional local stdio MCP adapter. |

Stages communicate through ordinary dictionaries described by domain-owned
`TypedDict` shapes. These types and named tuple aliases key the request-local
record map. Callers can invoke stages directly; operator-facing constructors
remain validating dataclasses.

## Standard workflow

`ComputeRequest` carries a `CalculationDraft` and exactly one
`PresetSelection` or `RecordSelection`. `Service.compute` dispatches it
concurrently over a process-owned `Runtime`; shared model backends
synchronize only their first lazy load, so model state is safe to reuse.
Publication in `runtime/models.py` uses the identity and legal references cached
with each loaded model, rather than re-reading a changed registry. The QRF feature
classifier and the standalone metallicity classifier retain separate snapshots;
unused models are not loaded for publication.
`recommend` and `generate` are DAG Preset IDs only.

```python
from goldilocks_core.io.structures import PathStructureSource
from goldilocks_core.publication import DirectoryOutput
from goldilocks_core.request import CalculationDraft, ComputeRequest, PresetSelection
from goldilocks_core.runtime.service import Service

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
Compute. `server/documents.py` converts strict transport shapes into Core
Records; Core constructors validate domain values once. Responses serialize
Core record documents through the portable projection; the selection and
input-data documents carry explicit portable projections that strip
generated artifact content and host file paths.

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
OpenAPI is exported from the application as the transport contract.

Adapters use the shared document operations rather than inspect native scientific
record types or maintain separate exception inventories. Native operations retain
their original exceptions. Expected failures carry a domain category and a safe
public description; the document interface classifies them once. Unexpected
execution defects propagate.

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
to the same installed table manifest. `PseudoResolution` owns source precedence,
compatibility, exact selected metadata, and deferred byte snapshots. Selection-only
computations do not materialize publication content. Model resolution binds the
request's advisor and captures identity and legal material only for models used.
Input assembly receives these completed values, not registry paths, default-model
flags, or another module's cache. Model loaders perform no network access.

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

Validate where data enters or causes side effects — types validate the
operator boundary, dicts flow inside:

- request records validate operator controls and external pseudopotential
  metadata;
- source adapters validate provider data before producing internal documents;
- generators reject unsupported or incomplete inputs before rendering;
- publication writes atomically to new destinations and confines logical paths.

Intermediate stage currency is plain dict documents trusted by construction.
Custom stage authors are responsible for returning coherent documents; Core
does not defensively re-check every possible malformed internal object.

Scientific choices belong in Analyze, Advise, Kmesh, and Select. Select
resolves the configured source and chooses a concrete pseudopotential per
element without making scientific policy beyond the stated requirements.
Generate maps completed choices to calculation syntax. Optional publication
writes complete DFT Input Data but does not run calculations.

Runner/AiiDA workflows, schedulers, authentication, and completed-output
analysis are outside this repository. HTTP and MCP do not add queues,
persistence, sessions, or pod management.

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
  projection for publication and CLI output, omitting artifact content,
  host-local pseudopotential paths, and licence text. Serialize the complete
  `ComputationResult` to retain stable Record IDs; serializing its raw dict
  alone does not apply those record-specific projections. CLI Results retain
  the operator's source and publication paths.
- Types validate the operator boundary; dicts flow inside. Operator input
  (`CalculationHints`, `CalculationIntent`, drafts, requests, selections,
  structure sources, output targets, `PseudoMetadata`, `Provenance`,
  `ModelSpec`) gets validating constructors; internal stage currency is
  plain dictionaries described by domain-owned shapes, trusted by construction.
  `Portable` annotations declare exclusions and serialized field shapes.
  Serializers and `server/documents.py` share these declarations; generated OpenAPI
  and TypeScript are build products, not checked-in copies of the contract.
- `Service` executes Computations concurrently over one process-owned
  `Runtime`. Model backends synchronize resource acquisition, not inference;
  `Dispatcher` synchronizes lazy default-task registration. Model configuration
  is cached for the backend's lifetime; reset releases loaded model resources.
- The top-level `compute` convenience reuses a caller-owned runtime when given
  one and otherwise closes its owned runtime after one call.
- The runtime imports no task-specific code. New tasks bring their own
  context and stage graph; they do not edit the generic executor.
- Importing `goldilocks_core` never imports FastAPI or the MCP SDK.
  The `[http]` and `[mcp]` extras are lazy boundaries.
- Two lazy-import patterns are deliberate: heavy ML dependencies (torch,
  matminer, dscribe) load at first model use, and optional transport extras
  import inside their serve paths with `ImportError` guidance.
- `server/documents.py` rejects unknown fields, bad types, and remote paths while
  constructing native Core inputs. Handlers serialize trusted Records directly.
- Named domain failures preserve their native exception identities and implement
  `ExpectedFailure`; HTTP/MCP do not import an inventory of scientific exceptions.
- MCP maps only known stage errors to `ToolError`; internal defects
  remain unhandled.
- `scripts/check_complexity.py` enforces AST import ceilings across all
  production owners, including new modules. It counts local and type-only imports,
  resolves re-exports, and counts members accessed through module aliases.
  The global ceiling is 12 project origin modules and 24 imported symbols, with
  stricter limits for the adapters, assembly, and SCF. Pure package export files
  are transparent to consumer counts; executable package modules are checked.
  Import limits are a backstop, not a substitute for coherent ownership: moving
  coordination into another oversized module is not a valid reduction.
  The same gate runs Ruff's McCabe check with a maximum cyclomatic complexity of
  10 per production function, ignoring `noqa` suppressions. Reduce decision logic
  and duplication rather than extracting branches into shallow helper fleets.