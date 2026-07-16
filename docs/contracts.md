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

It does not contain backend functions, model objects, registry keys, generator objects, or future target adapter objects. Target and resource metadata are request data; the executable implementation is Pipeline composition.

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

Produces the final concrete selection record. K-points are provided by Kmesh. The current implementation resolves QE UPF pseudopotentials and SSSP cutoffs in Ry, so `PseudoMetadata`, `PseudopotentialSelection`, and `SelectionRecord.pseudopotentials` are not target-neutral contracts.

### `GenerateStage`

```python
Callable[
    [Structure, CalculationIntent, ParameterAdvice, SelectionRecord],
    tuple[GeneratedFile, ...],
]
```

Generates files from completed Core records. The current input contract is QE-shaped; replacing this callable alone does not add another DFT target.

### `BundleStage`

```python
Callable[[CoreResult, str | Path], BundleRecord]
```

Publishes generated files and manifest output to a new destination. The default backend refuses existing destinations and does not provide destructive overwrite behavior.

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

Callable fields in `Pipeline` are not serialized. If a service needs to expose backend or target-adapter names over HTTP, that service owns name-to-callable resolution outside Core.

## Target-code contract direction

The current contracts support QE SCF only. Ry-valued smearing/convergence fields, UPF/SSSP metadata, and pseudopotential/cutoff selections must not be presented as universal target contracts.

The written multi-code design keeps shared physics records separate from typed target resource and selection records, while preserving JSON-safe requests/results and the fixed stage graph. It deliberately does not define an executable adapter API yet. See [target-code adapter boundary](target-code-adapters.md).

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

## Construction invariants

Public records reject invalid boundary values in dataclass `__post_init__` methods. The same checks therefore apply to built-in stages and custom `Pipeline` backends:

- `CalculationHints.k_spacing` and `KPointAdvice.spacing` are finite and positive.
- K-point grids contain exactly three positive integers. List inputs are accepted for ergonomic Python construction and normalized to immutable tuples. `KPointSelection.shift` likewise normalizes a three-item list of `0`/`1` integer flags.
- Boolean hint and advice controls accept only `bool` (or `None` for optional hints), never truthy values such as `1`.
- `KMeshEntry.k_distance_interval` uses `None` for an upper bound that is unbounded above, preserving the scientific interval without an `Infinity` JSON number.
- `Provenance.confidence`, when present, is finite and in the closed interval `[0, 1]`.
- Fixed occupations (`smearing_type=None` or `"fixed"`) have no width. Other smearing types require a finite positive width.
- Enabled `VdwAdvice` has one supported method; disabled advice has `method=None`.
- Present pseudopotential cutoffs and convergence controls are finite and positive; SCF step counts are positive integers.
- `GeneratedFile.path` is non-empty, relative, and contains no `..` traversal. `CoreResult` rejects duplicate generated paths before Bundle can consume them.
- `StructureFeatureVector.values` is one-dimensional, finite, and the same length as `feature_names`.

Errors identify the invalid record field so backend authors can repair the producing stage. Record construction is the enforcement boundary: an invalid custom Kmesh record, for example, raises before Select is called.
