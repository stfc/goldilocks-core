# Architecture

Goldilocks Core turns a structure and calculation intent into DFT input files.
The built-in workflow currently generates Quantum ESPRESSO SCF input. The data
flow is staged so later calculation types can reuse analysis, advice, resource
selection, and output handling.

```text
Load -> Analyze -> Advise -> Kmesh
Load + Advice + Kmesh -> Select
Load + Advice + Select + Kmesh -> Generate
```

The executor resolves this dependency graph from typed stage inputs and
outputs. Stages are functions with no stage base classes; only source
resolution and bundle publication touch the filesystem.

## Modules

| Module | Responsibility |
| --- | --- |
| `assets/` | Immutable asset records, profiles, download integrity, transactional installation, and verification. |
| `ml/model_registry.py` | Complete model runtime configuration and model asset declarations. |
| `pseudo/registry.py`, `pseudo/import_*` | Complete pseudopotential table declarations and provider-specific normalization. |
| `pseudo/source.py` | One source-resolution interface for request metadata, operator roots, and installed tables. |
| `contracts/` | Data records and serialization shared between stages. |
| `runtime/graph.py` | Stage-agnostic, type-keyed DAG executor (`TaskGraph`/`Stage`/`Preset`/`execute`). |
| `runtime/task.py` | `GraphHandler`: a task's graph plus its context-builder and result-assembler hooks. |
| `runtime/scf.py` | The SCF task: run context, stage graph, and result assembly. |
| `runtime/models.py` | `Runtime`: kmesh/metallicity model lifecycle (load/reset/close), exposed as read-only services. |
| `runtime/dispatch.py` | `Dispatcher`: task registry and dispatch by `intent.task` through `GraphHandler`s. |
| `runtime/jobs.py` | `run_core_job` (preset) and `query_records` (query) entrypoints. |
| `runtime/service.py` | `Service`: process-owned lifecycle, locking, operations, and discovery shared by every entry point. |
| `io/structures.py` | Structure loading. |
| `analysis.py` | Structure facts. |
| `advice/` | Scientific and numerical recommendations. |
| `kmesh/`, `advice/` | Concrete k-point selection. |
| `selection.py` | Pseudopotentials and cutoffs. |
| `generation/` | Calculation-specific file generation. |
| `bundle.py` | Generated files and manifest output. |
| `server/request.py` | Canonical JSON request deserialization shared by transports. |
| `server/http.py`, `server/mcp.py` | Thin optional HTTP and MCP adapters over one `Service`. |

Stages communicate through dataclasses. They do not need to inherit from a Core
class, and callers can invoke any stage function directly.

## Standard workflow

`PresetRequest` carries a preset run (`mode` = `recommend`/`generate`);
`QueryRequest` carries an explicit record query (`outputs`). `Service`
exposes `recommend`, `generate`, and `compute` over a process-owned
`Runtime` and `Dispatcher`, serializing dispatch so lazy model state is
safe to reuse. `run_core_job` and `query_records` are short-lived convenience
entry points. The dispatcher runs the registered `scf_single_point` task.

```python
with Service() as core:
    request = PresetRequest(structure="Fe.cif")
    result = core.generate(request, output_dir="run")
```

`mode` selects a task preset:

- `recommend`: request Analyze, Advise, Kmesh, and Select
  records
- `generate`: additionally request GeneratedFiles and optionally publish them
  when `output_dir` is set

`CalculationIntent.task` describes the calculation. The built-in runtime
currently accepts only `scf_single_point`.

## Flexible Python use

`run_core_job` is optional convenience, not an access restriction. Advanced
callers can import stage functions and compose them themselves:

```python
from goldilocks_core.advice import advise_parameters
from goldilocks_core.analysis import analyze_structure
from goldilocks_core.advice.kdistance import QrfBackend
from goldilocks_core.generation import generate_inputs
from goldilocks_core.io.structures import load_structure
from goldilocks_core.kmesh import resolve_kpoints
from goldilocks_core.selection import select_pseudopotentials

structure = load_structure("Fe.cif")
analysis = analyze_structure(structure)
advice = advise_parameters(analysis, intent, hints)
kpoints = resolve_kpoints(structure, hints, QrfBackend())
selection = select_pseudopotentials(
    structure, advice.pseudopotential_requirements, metadata
)
files = generate_inputs(structure, intent, advice, selection, kpoints)
```

This supports custom ordering, extra project-specific steps, intermediate
inspection, and calculation-specific generation without extending a framework.

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
deserialization performs no asset-store I/O. The CLI installs assets only
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
- bundle writing confines paths to a new output directory.

Intermediate records remain ordinary Python data. Custom stage authors are
responsible for returning coherent records; Core does not defensively re-check
every possible malformed internal object.

Scientific choices belong in Analyze, Advise, Kmesh, and Select. Select
resolves the configured source and chooses a concrete pseudopotential per
element without making scientific policy beyond the stated requirements.
Generate maps completed choices to calculation syntax. Optional bundle
publication writes files but does not run calculations or copy
pseudopotential libraries.

Runner/AiiDA workflows, schedulers, auth, frontend state, and completed-output
analysis are outside this package. HTTP and MCP are optional thin transports;
they do not add queues, persistence, sessions, or pod management.
