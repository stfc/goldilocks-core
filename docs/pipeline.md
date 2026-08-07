# Pipeline

Goldilocks provides a standard staged workflow and public functions for using
each stage independently.

## Standard use

```python
from goldilocks_core import CalculationHints, generate

result = generate(
    "Fe.cif",
    hints=CalculationHints(k_grid=(6, 6, 6), spin_polarized=True),
    pseudo_metadata=metadata,
)

for generated_file in result.generated_files:
    print(generated_file.path)
```

The convenience functions are:

- `recommend(...)`: analyze, advise, resolve k-points, and select resources;
- `generate(...)`: also generate input files;
- `write_bundle(...)`: also write files and `manifest.json`.

All return `CoreResult`.

## Request and dispatch

Use `CoreJobRequest` when an application needs one serializable job object.
`run_core_job` dispatches on `intent.task` to a path function that composes the
stages for that calculation. The SCF path (`scf_single_point`) is built in;
future paths (magnetic, NSCF, phonons) are added the same way.

```python
from goldilocks_core import CoreJobRequest, run_core_job

request = CoreJobRequest(
    structure="Fe.cif",
    mode="generate",
    pseudo_metadata=tuple(metadata),
)
result = run_core_job(request)
```

`mode` controls how far the SCF path runs: `recommend` stops after Select,
`generate` after Generate, `bundle` after Bundle.

## K-point backends

K-points are resolved by `resolve_kpoints(structure, hints, backend)`:
explicit `k_grid` wins over `k_spacing`, and both beat the model backend. The
default backend is the built-in QRF k-distance model; explicit hints bypass
model loading entirely.

To use a local k-index model instead of the default, put a `ModelSpec` on the
request:

```python
from goldilocks_core import CoreJobRequest, run_core_job
from goldilocks_core.contracts import ModelSpec

spec = ModelSpec(
    name="local-kmesh",
    version="1",
    model_type="random_forest",
    target="k_index",
    feature_set="cslr",
    source="local",
    location="model.joblib",
)

result = run_core_job(
    CoreJobRequest(structure="Fe.cif", mode="recommend", kmesh_model=spec)
)
```

The model spec is request data, so it serializes alongside the rest of the job.

## Adding calculation tasks

`run_core_job` dispatches `intent.task` through a `_PATHS` table in `jobs.py`,
mapping each task to a path function. The built-in entry is
`scf_single_point` -> `run_scf`. A new task (magnetic, NSCF, phonons) is added
by registering another path function that composes the shared stages. For
one-off or experimental sequences, compose the stage functions directly
instead.

## Compose stages directly

Callers are not required to use `run_core_job`:

```python
from goldilocks_core.advice import advise_parameters
from goldilocks_core.analysis import analyze_structure
from goldilocks_core.advisors import default_kmesh_advisor
from goldilocks_core.io.structures import load_structure
from goldilocks_core.kmesh import resolve_kpoints
from goldilocks_core.selection import select_parameters

structure = load_structure("Fe.cif")
analysis = analyze_structure(structure)
advice = advise_parameters(analysis, intent, hints)
kpoints = resolve_kpoints(structure, hints, default_kmesh_advisor())
selection = select_parameters(structure, advice, metadata)
```

Use this form to inspect intermediate records, insert project-specific work,
reuse only part of the pipeline, or drive a calculation family with a different
sequence.

## Stage responsibilities

- **Load** reads a `pymatgen.Structure` or structure file.
- **Analyze** reports structure facts.
- **Advise** recommends physics and numerical settings with provenance.
- **Kmesh** resolves operator hints or a model into a concrete grid.
- **Select** chooses pseudopotentials and cutoffs.
- **Generate** creates one or more calculation input files.
- **Bundle** writes generated files and a manifest to a new directory.

The standard graph is intentionally simple. More complex workflows belong in
calling Python code or Runner rather than a DAG system inside Core.