# Backend authoring guide

A backend is a plain function used as one field of `Pipeline`.

Backends are not subclasses. They do not register themselves. They do not use string names inside Core. The stage signature is the interface.

## Backend checklist

Every backend should:

- satisfy the exact stage signature
- return the exact contract object expected by the stage
- set provenance accurately
- preserve stage ownership boundaries
- raise clear `ValueError` exceptions for unsupported inputs
- avoid hidden I/O unless the stage owns I/O
- be tested through `run_core_job()` or the public wrapper that uses it

## Kmesh backends

Signature:

```python
from goldilocks_core.contracts import KMeshAdvisor

KMeshAdvisor = Callable[[Structure, CalculationHints, KPointAdvice], KPointSelection]
```

Inputs:

- `Structure`: needed for reciprocal-lattice conversion or ML feature extraction.
- `CalculationHints`: operator overrides. `k_grid` and `k_spacing` take precedence over strategy output.
- `KPointAdvice`: default/advised k-point intent from Advise.

Output:

- `KPointSelection`

### Minimal backend

```python
from goldilocks_core.contracts import KPointSelection, Provenance


def fixed_kmesh(structure, hints, kpoint_advice):
    if hints.k_grid is not None:
        return KPointSelection(
            grid=hints.k_grid,
            shift=(0, 0, 0),
            mesh_type=kpoint_advice.mesh_type,
            provenance=Provenance(
                source="user_hint",
                reason="Use the operator-provided explicit k-point grid.",
            ),
        )

    return KPointSelection(
        grid=(4, 4, 4),
        shift=(0, 0, 0),
        mesh_type=kpoint_advice.mesh_type,
        provenance=Provenance(
            source="default",
            reason="Use a fixed test k-point mesh.",
        ),
    )
```

### Built-in default backend

`Pipeline()` installs `default_kmesh_advisor()`. It checks operator hints first,
then lazily resolves the QRF model and its supporting artifacts from the model
registry. Loading or inference failures use `resolve_kpoints_from_advice()` and
append an actionable provenance warning.

Constructing the pipeline does not load models or access the network. The first
call without a k-point hint validates the extractor schema and exact configured
runtime, then loads and caches either the configured models or the load failure.
Successful selections carry the complete configuration digest and structured
runtime/artifact identities in `provenance.details.qrf_inference`; local
artifacts use SHA-256 content identities.

For reuse across jobs, put the composition in one `CoreRuntime`. Direct
`pipeline=` is the explicit one-call path only for stateless composition. A
stateful backend implements `RuntimeResource` (`reset()` and `close()`), is
registered by `Pipeline`, and must be owned by one `CoreRuntime`; direct
execution is rejected. `CoreRuntime` resets and closes it with the rest of the
composition.

### Explicit heuristic backend

```python
from goldilocks_core import Pipeline
from goldilocks_core.kmesh import resolve_kpoints_from_advice

pipeline = Pipeline(kmesh=resolve_kpoints_from_advice)
```

`resolve_kpoints_from_advice()` uses this order:

1. `hints.k_grid` → explicit grid, `source="user_hint"`
2. `hints.k_spacing` → converted grid, `source="user_hint"`
3. `KPointAdvice.explicit_grid` → explicit advised grid
4. `KPointAdvice.spacing` → converted grid, source inherited from advice
5. no grid or spacing → `ValueError`

### Custom ML backend

```python
from goldilocks_core.advisors import ml_kmesh_advisor

pipeline = Pipeline(kmesh=ml_kmesh_advisor(spec))
```

`ml_kmesh_advisor(spec)` returns a callable lifecycle resource. It checks hints
first. On the first hint-free call it loads the model once; concurrent calls
share that initialization. It caches either the loaded model or a load failure.
When composed in `CoreRuntime`, `reset()` clears that cache for lazy retry and
`close()` releases the model reference. It returns a model-backed
`KPointSelection` when initialization succeeds.

Expected provenance:

```python
selection.provenance.source == "model"
selection.provenance.data_source == spec.name
```

## Generate backends

Signature:

```python
GenerateStage = Callable[
    [Structure, CalculationIntent, ParameterAdvice, SelectionRecord],
    tuple[GeneratedFile, ...],
]
```

A generator translates completed Core records into files. The current `SelectionRecord` contains QE UPF selections and Ry cutoffs, so this seam supports alternate rendering of the current QE-shaped result; it is not sufficient to add another DFT code.

A generator must not decide scientific defaults or select resources. It reads values from `intent`, `advice`, and `selection`. A second target needs the coordinated validation, resource selection, target-data, and generation boundary described in [target-code adapters](target-code-adapters.md).

### Minimal generator

```python
from goldilocks_core.contracts import GeneratedFile


def generate_custom_input(structure, intent, advice, selection):
    grid = selection.k_points.grid
    content = f"k_grid = {grid[0]} {grid[1]} {grid[2]}\n"
    return (GeneratedFile(path="inputs/custom.in", content=content),)
```

Use it:

```python

pipeline = Pipeline(generate=generate_custom_input)
result = run_core_job(
    CoreJobRequest(structure="Si.cif", mode="generate"),
    pipeline=pipeline,
)
```

## Select backends

Signature:

```python
SelectStage = Callable[
    [Structure, ParameterAdvice, KPointSelection, Sequence[PseudoMetadata]],
    SelectionRecord,
]
```

Select receives k-points from Kmesh. It should not recalculate the k-point grid.

A custom Select backend is appropriate for the current QE resource model when it needs:

- different UPF pseudopotential ranking
- different SSSP/Ry cutoff extraction
- additional selection warnings
- specialized pseudo metadata formats already converted to `PseudoMetadata`

It is not appropriate for:

- ML k-point prediction (use Kmesh)
- target-code text rendering (use Generate)
- structure facts (use Analyze)

A future target adapter does own target resource selection and target-specific numerical materialization at the Select boundary. That work must be paired with the same adapter's Generate behavior rather than implemented as independent ad hoc overrides.

## Advise backends

Signature:

```python
AdviseStage = Callable[
    [StructureAnalysisRecord, CalculationIntent, CalculationHints],
    ParameterAdvice,
]
```

A custom Advise backend changes scientific intent. Use this for new advice logic such as:

- different smearing policy
- different SOC policy
- different convergence defaults
- project-specific pseudo intent

Advice should remain intent-level. Concrete k-point grids belong to Kmesh. Concrete pseudo filenames and cutoffs belong to Select.

## Analyze backends

Signature:

```python
AnalyzeStage = Callable[[Structure], StructureAnalysisRecord]
```

Analyze backends report facts. They should not recommend parameters.

Use a custom Analyze backend when a project needs additional facts or different conservative classifications. If new facts are public, add them to `StructureAnalysisRecord` instead of returning an ad-hoc object.

## Bundle backends

Signature:

```python
BundleStage = Callable[[CoreResult, str | Path], BundleRecord]
```

A Bundle backend writes generated files and a manifest. It should be deterministic and reject path traversal. It should not run calculations, submit jobs, download pseudopotentials, or inspect completed outputs.

## Testing a backend

Preferred test shape:

```python


def test_custom_kmesh_backend_is_used():
    pipeline = Pipeline(kmesh=custom_kmesh)

    result = run_core_job(
        CoreJobRequest(structure=make_structure()),
        pipeline=pipeline,
    )

    assert result.selection.k_points.grid == expected_grid
```

Test both the backend itself and the integration point through `run_core_job()`.

## Common mistakes

### Putting backend choice on `CoreJobRequest`

Do not add fields such as `model`, `generator`, or `backend` to `CoreJobRequest`. The request must remain serializable data about the job. Backend choice is executable behavior and belongs in `Pipeline`.

### Returning raw values

Bad:

```python
def my_kmesh(...):
    return (4, 4, 4)
```

Good:

```python
def my_kmesh(...):
    return KPointSelection(...)
```

### Bypassing provenance

Every backend output must explain why it was selected. Missing provenance makes results difficult to audit and compare.

### Adding a registry to Core

Core should not maintain global mutable mappings from strings to backends. If a CLI or HTTP layer needs names, it resolves them outside Core and passes callables in `Pipeline`.
