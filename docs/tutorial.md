# Tutorial

A start-to-finish walkthrough of the goldilocks-core Python API.

## Quick start

```python
from goldilocks_core import recommend

result = recommend("path/to/structure.cif")

print(result.analysis.reduced_formula)         # e.g. "Si"
print(result.advice.k_points.provenance.source) # "default"
print(result.selection.k_points.grid)          # e.g. (8, 8, 8)
print(result.to_dict())                        # full JSON-safe dict
```

## Overriding defaults with hints

```python
from goldilocks_core import CalculationHints, recommend

result = recommend(
    "structure.cif",
    hints=CalculationHints(
        k_grid=(4, 4, 4),
        spin_polarized=True,
        smearing_type="cold",
        smearing_width_ry=0.01,
    ),
)

# Check provenance: these should be user_hint
print(result.advice.k_points.provenance.source)      # "user_hint"
print(result.advice.magnetism.provenance.source)      # "user_hint"
print(result.advice.smearing.provenance.source)        # "user_hint"

# Convergence was not hinted, so it's default
print(result.advice.convergence.provenance.source)    # "default"
```

## Inspecting intermediate stages

For notebooks or interactive exploration, run the stages individually through
`Pipeline` fields. Swappable stages live on `Pipeline`; Load is stable
request-boundary I/O handled by `load_structure`:

```python
from goldilocks_core import CalculationIntent, CalculationHints, Pipeline
from goldilocks_core.io.structures import load_structure

intent = CalculationIntent()
hints = CalculationHints()
pipeline = Pipeline()

structure = load_structure("structure.cif")
analysis = pipeline.analyze(structure)
print(analysis.elements)                   # ("Fe", "O")
print(analysis.electronic_character)       # "unknown"
print(analysis.heavy_elements)             # ()

advice = pipeline.advise(analysis, intent, hints)
print(advice.spin_orbit.consider)          # False
print(advice.k_points.spacing)             # 0.2

k_points = pipeline.kmesh(structure, hints, advice.k_points)
selection = pipeline.select(structure, advice, k_points, ())
print(selection.k_points.grid)             # (8, 8, 8)
```

## Pseudopotential selection

```python
from goldilocks_core import CalculationHints, recommend
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata

pseudo_metadata = load_pseudo_metadata("path/to/pseudopotentials")

result = recommend(
    "structure.cif",
    hints=CalculationHints(k_grid=(4, 4, 4), pseudo_type="NC"),
    pseudo_metadata=pseudo_metadata,
)

for pseudo in result.selection.pseudopotentials:
    print(f"{pseudo.element}: {pseudo.filename}")
    if pseudo.ecutwfc_ry is not None:
        print(f"  ecutwfc = {pseudo.ecutwfc_ry} Ry")
```

## Generating input files

```python
from goldilocks_core import CalculationHints, generate
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata

pseudo_metadata = load_pseudo_metadata("path/to/pseudopotentials")

result = generate(
    "structure.cif",
    hints=CalculationHints(k_grid=(4, 4, 4), pseudo_type="NC"),
    pseudo_metadata=pseudo_metadata,
)

for generated_file in result.generated_files:
    print(generated_file.path)     # "inputs/qe.in"
    print(generated_file.content)  # full QE input text
```

## Writing a portable bundle

```python
from goldilocks_core import CalculationHints, write_bundle
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata

pseudo_metadata = load_pseudo_metadata("path/to/pseudopotentials")

result = write_bundle(
    "structure.cif",
    "run/",
    hints=CalculationHints(k_grid=(4, 4, 4), pseudo_type="NC"),
    pseudo_metadata=pseudo_metadata,
)

print(result.bundle.path)          # "run/"
print(result.bundle.manifest)     # dict with manifest content
# run/manifest.json and run/inputs/qe.in are now on disk
```

## Using the shared job runner

The job runner is the same internal path that the CLI uses:

```python
from goldilocks_core import CoreJobRequest, CalculationHints, run_core_job

result = run_core_job(
    CoreJobRequest(
        structure="structure.cif",
        hints=CalculationHints(k_spacing=0.2),
        mode="recommend",
    )
)

print(result.stages)              # stage execution records
print(result.to_dict())           # full JSON-safe output
```

## Error handling

- **Missing pseudopotentials**: selection records have `filename=None` and carry warnings. Generation raises `ValueError`.
- **Invalid hints**: `advise_parameters()` raises `ValueError` for non-positive k_spacing, conv_thr, etc. before recording provenance.
- **Disordered structures**: analysis reports `disorder_warnings`. Generation raises `ValueError` — disordered occupancies require manual resolution.
- **Unsupported codes/tasks**: generation raises `ValueError` for anything other than QE SCF.

## ML k-mesh backend

Use `ml_kmesh_advisor(spec)` to plug model-backed k-point selection into the staged pipeline:

```python
from goldilocks_core import Pipeline, recommend
from goldilocks_core.advisors import ml_kmesh_advisor
from goldilocks_core.contracts import ModelSpec

spec = ModelSpec(
    name="local-kmesh-model",
    version="v0",
    model_type="random_forest",
    target="k_index",
    feature_set="cslr",
    source="local",
    location="path/to/model.joblib",
)

pipeline = Pipeline(kmesh=ml_kmesh_advisor(spec))
result = recommend("structure.cif", pipeline=pipeline)

print(result.selection.k_points.grid)
print(result.selection.k_points.provenance.source)       # "model"
print(result.selection.k_points.provenance.data_source)  # spec.name
```

The request remains data-only. The model is not stored on `CoreJobRequest`; it is executable backend configuration carried by `Pipeline`.

Operator hints still take precedence:

```python
from goldilocks_core import CalculationHints

result = recommend(
    "structure.cif",
    hints=CalculationHints(k_grid=(4, 4, 4)),
    pipeline=pipeline,
)

print(result.selection.k_points.provenance.source)  # "user_hint"
```

The standalone advisor remains available when you only need a `KPointSelection`:

```python
from goldilocks_core.advisors import advise_kpoints
from goldilocks_core.io.structures import load_structure

selection = advise_kpoints(load_structure("structure.cif"), spec)
```

## Common patterns

**I just need a k-grid:**

```python
from goldilocks_core import recommend
result = recommend("structure.cif")
print(result.selection.k_points.grid)
```

**I want JSON for an HTTP service:**

```python
from goldilocks_core import recommend
result = recommend("structure.cif")
return result.to_dict()
```

**I want SOC on for a heavy-element compound:**

```python
from goldilocks_core import CalculationHints, recommend
result = recommend(
    "structure.cif",
    hints=CalculationHints(
        spin_orbit_coupling=True,
        relativistic_mode="full",
    ),
)
```