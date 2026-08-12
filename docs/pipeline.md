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
- `generate(...)`: also generate input files and, when `output_dir` is given,
  publish them with `manifest.json`.

Both return `CoreResult`.

## Request and dispatch

Use `CoreJobRequest` when an application needs one serializable job object.
`run_core_job` delegates to a fresh `CoreRuntime`, or reuses a caller-supplied
runtime. The runtime owns model lifecycle and executes the registered SCF task
graph.

```python
from goldilocks_core import CoreJobRequest, run_core_job

request = CoreJobRequest(
    structure="Fe.cif",
    mode="generate",
    pseudo_metadata=tuple(metadata),
)
result = run_core_job(request)
```

`mode` controls how far the SCF graph runs: `recommend` stops after Select;
`generate` runs through Generate and publishes a bundle when `output_dir` is
set.

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

## Task graph

`SCF_TASK` declares each stage's input and output record types and the
`recommend` and `generate` presets. `CoreRuntime.compute(...)` asks the
executor for arbitrary output types; the executor resolves and runs only their
prerequisites. New calculation tasks use another `TaskSpec` rather than a
hand-coded dispatch path.

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
- **Generate** creates one or more calculation input files from Advice,
  Kmesh, and Select records.

Analyze and Kmesh are parallel dependencies of the SCF task. Select depends on
Load and Advise, not Kmesh. Bundle publication is an optional side effect of
the `generate` preset rather than a separate mode.
