# Contract reference

`contracts.py` defines the public records that cross Core stage boundaries.

Contracts are dataclasses or type aliases. They are intentionally explicit so Python, CLI, and future HTTP callers can share the same request/result shape.

## Data-only contracts

These objects are safe to serialize with `to_dict()`:

- `CalculationIntent`
- `CalculationHints`
- `Provenance`
- `StructureAnalysisRecord`
- `ParameterAdvice`
- `KPointSelection`
- `SelectionRecord`
- `GeneratedFile`
- `CoreResult`
- `CoreJobRequest`
- `StageRecord`
- `CoreResult`
- model and k-mesh records such as `ModelSpec`, `StructureFeatureVector`, and `KMeshEntry`

`CoreJobRequest` is the request boundary. It contains only serializable job data:

```text
structure
intent
hints
mode
pseudo_metadata
output_dir
```

It does not contain backend functions, model objects, registry keys, or generator objects.

## Behavior contracts

`Pipeline` is the behavior boundary. It contains callables:

```python
Pipeline(
    analyze=...,
    advise=...,
    kmesh=...,
    select=...,
    generate=...,
    bundle=...,
)
```

A `Pipeline` is not part of `CoreJobRequest.to_dict()`. It is executable configuration for Python callers.

## Stage type aliases

### `AnalyzeStage`

```python
Callable[[Structure], StructureAnalysisRecord]
```

Reports facts about a loaded structure.

### `AdviseStage`

```python
Callable[
    [StructureAnalysisRecord, CalculationIntent, CalculationHints],
    ParameterAdvice,
]
```

Produces provenance-backed scientific and numerical intent.

### `KMeshAdvisor`

```python
Callable[[Structure, CalculationHints, KPointAdvice], KPointSelection]
```

Resolves a concrete k-point grid. This is the extension point for model-backed k-point selection.

### `SelectStage`

```python
Callable[
    [Structure, ParameterAdvice, KPointSelection, Sequence[PseudoMetadata]],
    SelectionRecord,
]
```

Produces the final concrete selection record. K-points are provided by Kmesh; Select resolves pseudopotentials and cutoffs.

### `GenerateStage`

```python
Callable[
    [Structure, CalculationIntent, ParameterAdvice, SelectionRecord],
    tuple[GeneratedFile, ...],
]
```

Generates target-code files from completed Core records.

### `BundleStage`

```python
Callable[[CoreResult, str | Path], JsonDict]
```

Writes generated files and manifest output.

## Pipeline stage names

`StageName` values are:

```text
load
analyze
advise
kmesh
select
generate
bundle
```

`Load` is represented in `StageRecord`, but it is not a field on `Pipeline`. Loading is stable request-boundary I/O. Swappable computational backends start at Analyze.

## Job modes

`JobMode` values are:

```text
recommend
generate
bundle
```

Mode controls how far the fixed graph runs:

```text
recommend -> Load -> Analyze -> Advise -> Kmesh -> Select
generate  -> Load -> Analyze -> Advise -> Kmesh -> Select -> Generate
bundle    -> Load -> Analyze -> Advise -> Kmesh -> Select -> Generate -> Bundle
```

## Serialization

`to_dict()` uses `to_jsonable()` recursively:

- dataclasses become dictionaries
- tuples and lists become lists
- `Path` becomes `str`
- `pymatgen.Structure` becomes `Structure.as_dict()`
- numpy arrays become lists
- numpy scalars become Python scalars

Callable fields in `Pipeline` are not serialized. If a service needs to expose backend names over HTTP, that service owns name-to-callable resolution outside Core.

## Provenance contract

Every scientific advice or selection record has `Provenance`.

Allowed `Provenance.source` values:

| Source | Meaning |
| --- | --- |
| `analysis` | derived from structure analysis facts |
| `user_hint` | explicitly provided by the operator |
| `default` | package default |
| `model` | ML model prediction |
| `lookup` | resolved from supplied metadata |
| `fallback` | incomplete placeholder because data was unavailable |

Backends must preserve this contract. A custom backend that cannot explain its output should not be used in the Core pipeline.
