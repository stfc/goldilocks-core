# Architecture

Goldilocks Core turns a structure and calculation intent into DFT input files.
The built-in workflow currently generates Quantum ESPRESSO SCF input. The data
flow is staged so later calculation types can reuse analysis, advice, resource
selection, and output handling.

```text
Load -> Analyze -> Advise -> Kmesh -> Select -> Generate -> Bundle
```

This is the default workflow, not a workflow engine. Core has no DAG scheduler,
plugin registry, service container, or stage base classes.

## Modules

| Module | Responsibility |
| --- | --- |
| `contracts.py` | Data records shared between stages. |
| `jobs.py` | `Pipeline`, `run_core_job`, and convenience functions. |
| `io/structures.py` | Structure loading. |
| `analysis.py` | Structure facts. |
| `advice.py` | Scientific and numerical recommendations. |
| `kmesh.py`, `advisors/` | Concrete k-point selection. |
| `selection.py` | Pseudopotentials and cutoffs. |
| `generation.py` | Calculation-specific file generation. |
| `bundle.py` | Generated files and manifest output. |

Stages communicate through dataclasses. They do not need to inherit from a Core
class, and callers can invoke any stage function directly.

## Standard workflow

`CoreJobRequest` contains job data. `Pipeline` contains the callables used to
process it. Keeping these separate allows requests to be serialized while
Python callers replace implementations.

```python
request = CoreJobRequest(structure="Fe.cif", mode="generate")
result = run_core_job(request, pipeline=Pipeline())
```

`mode` controls where the standard workflow stops:

- `recommend`: after Select
- `generate`: after Generate
- `bundle`: after Bundle

`CalculationIntent.task` describes the calculation. Task names are not closed
in the shared contract. The built-in generator currently accepts only
`scf_single_point`; another generator may support additional tasks and emit
multiple `GeneratedFile` records.

## Flexible Python use

The pipeline is optional convenience, not an access restriction. Advanced
callers can import stage functions and compose them themselves:

```python
from goldilocks_core.advice import advise_parameters
from goldilocks_core.analysis import analyze_structure
from goldilocks_core.generation import generate_inputs
from goldilocks_core.io.structures import load_structure
from goldilocks_core.kmesh import resolve_kpoints_from_advice
from goldilocks_core.selection import select_parameters

structure = load_structure("Fe.cif")
analysis = analyze_structure(structure)
advice = advise_parameters(analysis, intent, hints)
kpoints = resolve_kpoints_from_advice(structure, hints, advice.k_points)
selection = select_parameters(structure, advice, kpoints, metadata)
files = generate_inputs(structure, intent, advice, selection)
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
completed choices to calculation syntax. Bundle writes files but does not run
calculations or copy pseudopotential libraries.

Runner/AiiDA workflows, schedulers, auth, HTTP transport, frontend state, and
completed-output analysis are outside this package.
