# Composable Core pipeline

The Core pipeline is a fixed graph with injectable stage backends.

```text
Load -> Analyze -> Advise -> Kmesh -> Select -> Generate -> Bundle
```

The graph order is fixed. The implementation behind each stage is configurable through a `Pipeline` object.

## Why this exists

Core has two separate concerns:

- **What to compute**: structure, intent, hints, mode, pseudo metadata, output directory.
- **How to compute it**: stage implementations for analysis, advice, k-point resolution, selection, generation, and bundle writing.

`CoreJobRequest` carries the first concern. It is data-only and JSON-safe.

`Pipeline` carries the second concern. It is a composition of callables and is not serialized as part of the request.

This split keeps HTTP/JSON boundaries clean while making Python callers able to swap backends directly.

## Core objects

```python
from goldilocks_core import CoreJobRequest, Pipeline, run_core_job
```

`Pipeline` is a frozen dataclass with one callable per stage:

```python
@dataclass(frozen=True, slots=True)
class Pipeline:
    analyze: AnalyzeStage = analyze_structure
    advise: AdviseStage = advise_parameters
    kmesh: KMeshAdvisor = field(default_factory=default_kmesh_advisor)
    select: SelectStage = select_parameters
    generate: GenerateStage = generate_inputs
    bundle: BundleStage = write_bundle_directory
```

The built-in composition is returned by `Pipeline()`:

```python
pipeline = Pipeline()
```

`run_core_job()` accepts an optional pipeline:

```python
result = run_core_job(request, pipeline=pipeline)
```

If no pipeline is passed, `run_core_job()` calls `Pipeline()` and uses the
built-in backends. The default Kmesh backend lazily loads the QRF configuration
from `model_registry.toml`; explicit k-point hints bypass model loading. Use
`Pipeline(kmesh=resolve_kpoints_from_advice)` for an explicitly heuristic path.

## Stage contracts

### Analyze

```python
AnalyzeStage = Callable[[Structure], StructureAnalysisRecord]
```

Input:

- loaded `pymatgen.core.Structure`

Output:

- `StructureAnalysisRecord`

Responsibility:

- report structure facts only
- no parameter recommendations
- no generated file logic

### Advise

```python
AdviseStage = Callable[
    [StructureAnalysisRecord, CalculationIntent, CalculationHints],
    ParameterAdvice,
]
```

Inputs:

- analysis facts
- operator intent
- operator hints

Output:

- `ParameterAdvice`

Responsibility:

- choose scientific/numerical intent
- record provenance on every advice record
- preserve uncertainty as warnings

Advise does not produce concrete k-point grids. It produces `KPointAdvice`, which is intent: explicit grid or spacing plus mesh type and provenance.

### Kmesh

```python
KMeshAdvisor = Callable[[Structure, CalculationHints, KPointAdvice], KPointSelection]
```

Inputs:

- loaded structure
- operator hints
- `KPointAdvice` from Advise

Output:

- `KPointSelection`

Responsibility:

- resolve concrete k-point grid and shift
- preserve hint precedence
- record whether the grid came from a hint, default/advice path, or model

Kmesh is a separate stage because k-point resolution is the natural backend
seam. The configured default predicts a grid from a QRF model when no hint is
set and falls back to advice-based resolution when ML is unavailable. A custom
backend can replace either strategy.

### Select

```python
SelectStage = Callable[
    [Structure, ParameterAdvice, KPointSelection, Sequence[PseudoMetadata]],
    SelectionRecord,
]
```

Inputs:

- loaded structure
- full parameter advice
- concrete k-point selection from Kmesh
- pseudopotential metadata

Output:

- `SelectionRecord`

Responsibility:

- carry the Kmesh result into the final selection record
- select pseudopotentials and cutoffs
- aggregate selection warnings

Select does not resolve k-points. That belongs to Kmesh.

### Generate

```python
GenerateStage = Callable[
    [Structure, CalculationIntent, ParameterAdvice, SelectionRecord],
    tuple[GeneratedFile, ...],
]
```

Inputs:

- loaded structure
- intent
- advice
- selection

Output:

- generated files

Responsibility:

- translate completed records into target-code syntax
- never choose scientific defaults

### Bundle

```python
BundleStage = Callable[[CoreResult, str | Path], BundleRecord]
```

Inputs:

- completed recommendation with generated files
- output directory

Output:

- `BundleRecord` with the bundle path and manifest dictionary

Responsibility:

- write generated files and manifest
- reject path traversal
- stay independent of Runner/AiiDA/frontend assumptions

## Execution by mode

```text
recommend -> Load -> Analyze -> Advise -> Kmesh -> Select
generate  -> Load -> Analyze -> Advise -> Kmesh -> Select -> Generate
bundle    -> Load -> Analyze -> Advise -> Kmesh -> Select -> Generate -> Bundle
```

`Load` is not a field on `Pipeline`. Structure loading is stable I/O at the request boundary. The swappable computational stages start after loading.

## Default behavior

Default recommendation:

```python
from goldilocks_core import CoreJobRequest, run_core_job

result = run_core_job(CoreJobRequest(structure="Si.cif"))
```

This is equivalent to:

```python
from goldilocks_core import CoreJobRequest, Pipeline, run_core_job

result = run_core_job(
    CoreJobRequest(structure="Si.cif"),
    pipeline=Pipeline(),
)
```

## Replacing one backend

Construct ``Pipeline`` with the field you want to swap; the remaining stages keep their default backends:

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

print(result.selection.k_points.provenance.source)  # "model"
```

The request contains no model field. The request says what to compute. The pipeline says how to compute it.

## Replacing multiple backends

```python

pipeline = Pipeline(
    kmesh=ml_kmesh_advisor(spec),
    generate=generate_vasp_inputs,
)
```

A backend is just a function with the right signature. No base class, registry, plugin loader, or string resolution is required inside Core.

## Provenance expectations

Backends must return the standard contract objects with correct provenance:

- hint-derived values use `source="user_hint"`
- model-derived values use `source="model"`
- metadata lookups use `source="lookup"`
- package defaults use `source="default"`
- analysis-derived choices use `source="analysis"`
- fallback/incomplete selections use `source="fallback"`

Provenance is part of the backend contract. A backend that returns a bare tuple or string is not a Core backend.

## HTTP and CLI mapping

Core does not resolve backend names. It accepts callables.

A CLI or HTTP layer may expose names such as `--model model.joblib` or JSON fields such as `"kmesh_backend": "cslr"`. That layer resolves the name to a callable and passes a `Pipeline` into `run_core_job()`.

Example CLI mapping:

```python

pipeline = Pipeline(kmesh=ml_kmesh_advisor(spec))
result = run_core_job(request, pipeline=pipeline)
```

Core never sees the string `"cslr"`; it sees the function returned by `ml_kmesh_advisor(spec)`.
