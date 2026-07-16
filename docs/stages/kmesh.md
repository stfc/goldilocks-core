# Kmesh stage

Owner: `kmesh.py` and `advisors/`

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

Kmesh is the backend seam. The configured default lazily predicts a grid with
the QRF model when no operator hint is set and falls back to advice-based
resolution when ML is unavailable.

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

- `grid`: `(nk1, nk2, nk3)`, exactly three positive integers; a list input is normalized to an immutable tuple
- `shift`: exactly three `0`/`1` integer flags; a list input is normalized to an immutable tuple; currently `(0, 0, 0)`
- `mesh_type`: currently `"monkhorst-pack"`
- `provenance`: source, reason, optional data source, confidence, warnings; confidence is finite and in `[0, 1]` when present

`KPointSelection` enforces these invariants at construction, including for custom Kmesh backends, before Select is called.

## Default backend

`Pipeline()` uses `default_kmesh_advisor()`. The advisor reads the QRF model,
supporting metallicity artifacts, immutable revisions, compatible runtime
versions, confidence, and interval calibration from `model_registry.toml`. Set
`GOLDILOCKS_MODEL_REGISTRY` to a replacement TOML file to hot-swap that
configuration.

Registry parsing, model imports, artifact resolution, and inference are all
deferred until the first call without an explicit k-point hint. Loaded models
or a load failure are cached safely for subsequent or concurrent structures.
Failures resolve from advice and add the failure reason to provenance warnings.

The explicit heuristic backend is:

```python
from goldilocks_core.kmesh import resolve_kpoints_from_advice
```

Its decision order is:

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

## Custom ML backend

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

The default QRF backend catches model loading, feature extraction, invalid
prediction, and inference errors, then falls back with a provenance warning.
The custom `ml_kmesh_advisor()` may raise if its supplied `ModelSpec` cannot be
used.
