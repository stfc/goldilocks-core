# Architecture

Goldilocks Core turns a structure and calculation intent into DFT input files.
The built-in workflow currently generates Quantum ESPRESSO SCF input. The data
flow is staged so later calculation types can reuse analysis, advice, resource
selection, and output handling.

```text
Load -> Analyze -> Advise -> Select
Load -> Kmesh
Load + Advice + Select + Kmesh -> Generate
```

The executor resolves this dependency graph from typed stage inputs and
outputs. Stages remain pure functions with no stage base classes.

## Modules

| Module | Responsibility |
| --- | --- |
| `contracts/` | Data records and serialization shared between stages. |
| `graph.py` | Frozen task specifications and type-keyed DAG execution. |
| `runtime.py` | SCF task registration and model lifecycle. |
| `jobs.py` | `run_core_job` and public convenience functions. |
| `io/structures.py` | Structure loading. |
| `analysis.py` | Structure facts. |
| `advice/` | Scientific and numerical recommendations. |
| `kmesh/`, `advisors/` | Concrete k-point selection. |
| `selection.py` | Pseudopotentials and cutoffs. |
| `generation/` | Calculation-specific file generation. |
| `bundle.py` | Generated files and manifest output. |

Stages communicate through dataclasses. They do not need to inherit from a Core
class, and callers can invoke any stage function directly.

## Standard workflow

`CoreJobRequest` carries serializable job data. `run_core_job` delegates to a
fresh `CoreRuntime` unless the caller supplies one for model reuse. The runtime
executes the registered `scf_single_point` task.

```python
request = CoreJobRequest(structure="Fe.cif", mode="generate")
result = run_core_job(request)
```

`mode` selects a task preset:

- `recommend`: request Analyze, Advise, Kmesh, and Select records
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
from goldilocks_core.advisors import default_kmesh_advisor
from goldilocks_core.generation import generate_inputs
from goldilocks_core.io.structures import load_structure
from goldilocks_core.kmesh import resolve_kpoints
from goldilocks_core.selection import select_parameters

structure = load_structure("Fe.cif")
analysis = analyze_structure(structure)
advice = advise_parameters(analysis, intent, hints)
kpoints = resolve_kpoints(structure, hints, default_kmesh_advisor())
selection = select_parameters(structure, advice, metadata)
files = generate_inputs(structure, intent, advice, selection, kpoints)
```

This supports custom ordering, extra project-specific steps, intermediate
inspection, and calculation-specific generation without extending a framework.

## Boundaries

Validate where data enters or causes side effects:

- request records validate operator controls;
- pseudopotential selection treats metadata as untrusted;
- generators reject unsupported or incomplete inputs before rendering;
- bundle writing confines paths to a new output directory.

Intermediate records remain ordinary Python data. Custom stage authors are
responsible for returning coherent records; Core does not defensively re-check
every possible malformed internal object.

Scientific choices belong in Analyze, Advise, Kmesh, and Select. Generate maps
completed choices to calculation syntax. Optional bundle publication writes
files but does not run calculations or copy pseudopotential libraries.

Runner/AiiDA workflows, schedulers, auth, HTTP transport, frontend state, and
completed-output analysis are outside this package.
