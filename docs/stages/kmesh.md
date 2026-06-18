# Kmesh stage

Owner: `kmesh.py` and `advisors/kmesh_advisor.py`

The Kmesh stage resolves k-point intent into a concrete k-point grid.

It sits between Advise and Select:

```text
Analyze -> Advise -> Kmesh -> Select
```

## Why Kmesh is a stage

K-point selection has two distinct parts:

1. **Intent**: should Core use an explicit grid or a reciprocal-space spacing? This belongs to Advise and is represented by `KPointAdvice`.
2. **Concrete resolution**: what grid should be written into the final selection record? This belongs to Kmesh and is represented by `KPointSelection`.

Before Kmesh existed, concrete grid resolution lived inside Select. That made ML k-point prediction awkward because the ML advisor produces a concrete `KPointSelection`, not a `KPointAdvice`.

Kmesh is the backend seam. The default backend converts advice to a grid. The ML backend predicts a grid when no operator hint is set.

## Input

A Kmesh backend has this signature:

```python
KMeshAdvisor = Callable[[Structure, CalculationHints, KPointAdvice], KPointSelection]
```

Inputs:

- `Structure`: loaded structure with lattice information.
- `CalculationHints`: operator overrides. `k_grid` and `k_spacing` always take precedence.
- `KPointAdvice`: k-point intent from Advise.

## Output

- `KPointSelection`

Fields:

- `grid`: `(nk1, nk2, nk3)`
- `shift`: currently `(0, 0, 0)`
- `mesh_type`: currently `"monkhorst-pack"`
- `provenance`: source, reason, optional data source, confidence, warnings

## Default backend

```python
from goldilocks_core.kmesh import resolve_kpoints_from_advice
```

Decision order:

1. If `hints.k_grid` is set, use it directly.
2. Else if `hints.k_spacing` is set, convert it with `k_distance_to_mesh()`.
3. Else if `KPointAdvice.explicit_grid` is set, use it.
4. Else if `KPointAdvice.spacing` is set, convert it with `k_distance_to_mesh()`.
5. Else raise `ValueError`.

The conversion follows the VASP `KSPACING` convention using solid-state reciprocal lattice lengths that include the `2π` factor.

## Hint precedence

Hints beat every backend strategy.

This means a model-backed Kmesh backend must still respect operator hints:

```text
hints.k_grid    -> use explicit grid, source="user_hint"
hints.k_spacing -> convert spacing, source="user_hint"
otherwise       -> use backend strategy
```

This rule lets operators override a model without changing the pipeline object.

## ML backend

```python
from goldilocks_core.advisors import ml_kmesh_advisor
```

`ml_kmesh_advisor(spec)` returns a `KMeshAdvisor` callable.

Usage:

```python
from goldilocks_core import CoreJobRequest, Pipeline, run_core_job
from goldilocks_core.advisors import ml_kmesh_advisor
from goldilocks_core.contracts import ModelSpec

spec = ModelSpec(
    name="local-kmesh-model",
    version="v1",
    model_type="random_forest",
    target="k_index",
    feature_set="cslr",
    source="local",
    location="models/kmesh.joblib",
)

pipeline = Pipeline(kmesh=ml_kmesh_advisor(spec))
result = run_core_job(CoreJobRequest(structure="Si.cif"), pipeline=pipeline)
```

If no k-point hint is present, the ML backend calls:

```python
advise_kpoints(structure, spec)
```

That path performs:

```text
structure -> CSLR features -> model prediction -> nearest k-index -> KPointSelection
```

The resulting selection has model provenance:

```python
selection.provenance.source == "model"
selection.provenance.data_source == spec.name
```

## Provenance

Expected provenance sources:

| Path | Source |
| --- | --- |
| `hints.k_grid` | `user_hint` |
| `hints.k_spacing` | `user_hint` |
| default/advised spacing | inherited from `KPointAdvice.provenance.source` |
| ML model prediction | `model` |

Kmesh warnings are recorded on the `StageRecord(name="kmesh")` and included in the top-level recommendation warnings.

## Select interaction

Select receives the Kmesh output:

```python
selection = select_parameters(
    structure,
    advice,
    k_points,
    metadata_list,
)
```

Select no longer converts k-spacing to grids. It carries the provided `KPointSelection` into the `SelectionRecord` and resolves pseudopotentials/cutoffs around it.

## Error cases

`resolve_kpoints_from_advice()` raises `ValueError` when no hint is set and advice contains neither `explicit_grid` nor `spacing`.

`advise_kpoints()` may also raise through model loading, feature extraction, or inference if the supplied `ModelSpec` cannot be used.
