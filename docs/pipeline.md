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

## Request and pipeline

Use `CoreJobRequest` when an application needs one serializable job object.
Use `Pipeline` to replace stage implementations without putting Python
callables in that request.

```python
from goldilocks_core import CoreJobRequest, Pipeline, run_core_job

request = CoreJobRequest(
    structure="Fe.cif",
    mode="generate",
    pseudo_metadata=tuple(metadata),
)
result = run_core_job(request, pipeline=Pipeline())
```

`Pipeline()` supplies the built-in Analyze, Advise, Kmesh, Select, Generate,
and Bundle functions. Its fields are plain callables.

## Replace a stage

K-point selection is the common replacement point:

```python
from goldilocks_core import Pipeline, recommend
from goldilocks_core.kmesh import resolve_kpoints_from_advice

result = recommend(
    "Fe.cif",
    pipeline=Pipeline(kmesh=resolve_kpoints_from_advice),
)
```

A local model can be supplied the same way:

```python
from goldilocks_core.advisors import ml_kmesh_advisor
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

pipeline = Pipeline(kmesh=ml_kmesh_advisor(spec))
```

## Add a calculation task

The shared intent accepts task names beyond the built-in SCF task. A custom
Generate callable can implement one while reusing the earlier stages:

```python
from goldilocks_core import CalculationIntent, Pipeline, generate
from goldilocks_core.contracts import GeneratedFile


def generate_magnetic_nscf(structure, intent, advice, selection):
    if intent.task != "magnetic_nscf":
        raise ValueError(f"unsupported task: {intent.task}")
    return (
        GeneratedFile(path="inputs/scf.in", content=render_scf(...)),
        GeneratedFile(path="inputs/nscf.in", content=render_nscf(...)),
    )


result = generate(
    "Fe.cif",
    intent=CalculationIntent(task="magnetic_nscf"),
    pipeline=Pipeline(generate=generate_magnetic_nscf),
    pseudo_metadata=metadata,
)
```

The built-in `generate_inputs` remains explicit: it supports Quantum ESPRESSO
`scf_single_point` and rejects other target/task combinations.

## Compose stages directly

Callers are not required to use `Pipeline` or `run_core_job`:

```python
from goldilocks_core.advice import advise_parameters
from goldilocks_core.analysis import analyze_structure
from goldilocks_core.io.structures import load_structure
from goldilocks_core.kmesh import resolve_kpoints_from_advice
from goldilocks_core.selection import select_parameters

structure = load_structure("Fe.cif")
analysis = analyze_structure(structure)
advice = advise_parameters(analysis, intent, hints)
kpoints = resolve_kpoints_from_advice(structure, hints, advice.k_points)
selection = select_parameters(structure, advice, kpoints, metadata)
```

Use this form to inspect intermediate records, insert project-specific work,
reuse only part of the pipeline, or drive a calculation family with a different
sequence.

## Stage responsibilities

- **Load** reads a `pymatgen.Structure` or structure file.
- **Analyze** reports structure facts.
- **Advise** recommends physics and numerical settings with provenance.
- **Kmesh** resolves k-point advice to a concrete grid.
- **Select** chooses pseudopotentials and cutoffs.
- **Generate** creates one or more calculation input files.
- **Bundle** writes generated files and a manifest to a new directory.

The standard graph is intentionally simple. More complex workflows belong in
calling Python code or Runner rather than a DAG system inside Core.
