# API guide

This is the canonical staged Core API. There is no compatibility layer and no prior released shape to migrate from — this branch is the first landing of the staged Core pipeline. This document describes the final surface so callers and future work share one reference.

## Public surface

```python
from goldilocks_core import (
    CalculationHints,
    CalculationIntent,
    CoreJobRequest,
    CoreResult,
    Pipeline,
    generate,
    recommend,
    run_core_job,
    write_bundle,
)
```

`CoreJobRequest` is the serializable request boundary. `CoreResult` is the single result type returned by every entry point. `Pipeline` is the behavior boundary (a frozen dataclass of stage backends with default values).

## Result shape

There is one result type, `CoreResult`. It is the accumulator of every stage record the fixed graph produces:

```python
@dataclass(frozen=True, slots=True)
class CoreResult:
    intent: CalculationIntent
    analysis: StructureAnalysisRecord
    advice: ParameterAdvice
    selection: SelectionRecord
    generated_files: tuple[GeneratedFile, ...] = ()
    warnings: tuple[str, ...] = ()
    bundle: BundleRecord | None = None
    stages: tuple[StageRecord, ...] = ()
```

- `generated_files` is populated in generate/bundle modes.
- `bundle` is set only in bundle mode and carries `bundle.path` and `bundle.manifest`.
- `stages` is the execution trace, always populated.
- The request is **not** echoed on the result. The caller already has it. CLI/HTTP layers echo it themselves in their serialized output (the CLI prints `{"request": request.to_dict(), **result.to_dict()}`).

```python
result = recommend("structure.cif")
print(result.analysis.reduced_formula)
print(result.selection.k_points.grid)
print(result.to_dict())

result = write_bundle("structure.cif", "run/")
print(result.bundle.path)
print(result.bundle.manifest)
```

## Stage-by-stage usage

Swappable stages live on `Pipeline`. Load is stable request-boundary I/O handled by `load_structure`:

```python
from goldilocks_core import CalculationIntent, CalculationHints, Pipeline
from goldilocks_core.io.structures import load_structure

intent = CalculationIntent()
hints = CalculationHints()
pipeline = Pipeline()

structure = load_structure("structure.cif")
analysis = pipeline.analyze(structure)
advice = pipeline.advise(analysis, intent, hints)
k_points = pipeline.kmesh(structure, hints, advice.k_points)
selection = pipeline.select(structure, advice, k_points, ())
```

There are no standalone `load`/`analyze`/`advise`/`select` wrapper functions. Call the stage implementation functions directly (`analyze_structure`, `advise_parameters`, `select_parameters`, `load_structure`) or — preferred — call them through `Pipeline` fields so the swappable-backend model is explicit.

## Composing backends

`Pipeline` is a frozen dataclass whose fields default to the built-in backends. Override any field at construction to swap that stage:

```python
from goldilocks_core import Pipeline, recommend
from goldilocks_core.advisors import ml_kmesh_advisor

pipeline = Pipeline(kmesh=ml_kmesh_advisor(spec))
result = recommend("structure.cif", pipeline=pipeline)
```

There is no `default_pipeline()` function — `Pipeline()` is the default composition. There is no `dataclasses.replace`-based swap idiom taught; construct `Pipeline` with the overrides you want. (`dataclasses.replace(pipeline, kmesh=...)` remains available as an escape hatch for swapping one field on an already-custom pipeline.)

## Removed names

These names do not exist and there are no aliases for them:

- `CoreRecommendation` — use `CoreResult`.
- `CoreJobResult` — use `CoreResult`.
- `default_pipeline()` — use `Pipeline()`.
- `bundle_recommendation()` — use `result.to_dict()`.
- `goldilocks_core.pipeline` module — entry points moved to `goldilocks_core.jobs`; stage standalones removed.
- `goldilocks_core.shared` module — contract types live in `goldilocks_core.contracts`.

## Contract invariants enforced at construction

- `KPointAdvice` raises `ValueError` unless exactly one of `spacing` or `explicit_grid` is set.
- `CoreJobRequest` raises `ValueError` for an unsupported `mode` or for `mode="bundle"` without `output_dir`.

## Heavy-element heuristic

"Heavy" elements are those with pymatgen `row >= 5` (period 5+). This includes period-5 non-lanthanides like iodine (Z=53). See [conventions](conventions.md) for details. Heavy elements make SOC worth considering; Core never silently enables SOC.