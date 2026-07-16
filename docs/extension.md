# Extension guide

Extend Core by composing new stage backends into `Pipeline`.

A backend is a function with the stage signature. It returns the standard contract object for that stage. It does not subclass a base class and does not register itself in Core.

See [backends](backends.md) for detailed backend authoring examples.

## Pipeline extension model

```python

from goldilocks_core import Pipeline, run_core_job

pipeline = Pipeline(kmesh=my_kmesh_backend)
result = run_core_job(request, pipeline=pipeline)
```

Rules:

- `CoreJobRequest` remains data-only and serializable.
- `Pipeline` carries executable behavior.
- CLI/HTTP layers may resolve names to callables outside Core.
- Core does not maintain backend registries.
- Add new public fields to contracts only when a stage needs to expose new data.

## Adding a Kmesh backend

Use this when changing how concrete k-point grids are chosen.

Signature:

```python
KMeshAdvisor = Callable[[Structure, CalculationHints, KPointAdvice], KPointSelection]
```

Example:

```python
from goldilocks_core.contracts import KPointSelection, Provenance


def project_kmesh(structure, hints, kpoint_advice):
    if hints.k_grid is not None:
        return KPointSelection(
            grid=hints.k_grid,
            shift=(0, 0, 0),
            mesh_type=kpoint_advice.mesh_type,
            provenance=Provenance(
                source="user_hint",
                reason="Use the operator-provided explicit grid.",
            ),
        )

    return KPointSelection(
        grid=(6, 6, 6),
        shift=(0, 0, 0),
        mesh_type=kpoint_advice.mesh_type,
        provenance=Provenance(source="default", reason="Project default grid."),
    )
```

Then compose it:

```python
pipeline = Pipeline(kmesh=project_kmesh)
```

For ML k-points, use the built-in factory:

```python
from goldilocks_core.advisors import ml_kmesh_advisor

pipeline = Pipeline(kmesh=ml_kmesh_advisor(spec))
```

## Changing the current QE generator

Use `Pipeline(generate=...)` for alternate rendering of the same completed QE selection, such as replacing the hand-written QE formatter with a library writer.

Signature:

```python
GenerateStage = Callable[
    [Structure, CalculationIntent, ParameterAdvice, SelectionRecord],
    tuple[GeneratedFile, ...],
]
```

The generator returns `GeneratedFile` records with paths relative to the bundle root. It reads completed values from `intent`, `advice`, and `selection`; it does not choose resources or scientific defaults.

## Adding a DFT target

Do not add VASP, CP2K, CASTEP, ABINIT, or another target by swapping only Generate. The current request resource type, Select contract, cutoff fields, units, and CLI choices are QE-specific.

A future target implementation must follow the [target-code adapter boundary](target-code-adapters.md):

1. validate the target, task, and supported feature combinations;
2. define serializable target resource metadata and typed selections;
3. select concrete target resources and materialize target-specific numerical data in Select;
4. generate files from that completed target selection;
5. bind compatible Select and Generate behavior together at the composition boundary;
6. test `recommend`, `generate`, and `bundle` modes.

The adapter design is not implemented yet. Do not introduce an executable adapter protocol speculatively.

## Adding a new calculation task

A new task changes intent and generation behavior.

Steps:

1. Add the task name to `CalcTask` in `contracts.py`.
2. Extend or replace the Advise backend if the task needs different advice.
3. Write a Generate backend that supports the new task.
4. Add tests for advice, generation, and full `run_core_job()` integration.

Current task support is `scf_single_point` only.

## Adding a new QE pseudo source

Current pseudo source support is data-oriented but QE-shaped. Selection consumes UPF/SSSP-oriented `PseudoMetadata`, not raw files.

Steps:

1. Create a parser for the QE-compatible source format.
2. Return populated `PseudoMetadata` records.
3. Add a loader if the source has a directory or archive layout.
4. Use the existing Select backend if the metadata fields fit.
5. Replace Select only if QE ranking/cutoff policy must change.

A resource source for another DFT target belongs to that target adapter and needs its own typed metadata; do not force it into `PseudoMetadata`.

Rules:

- Do not add file-format logic to Select.
- Do not add pseudo downloads to Core.
- Do not make Generate parse pseudo metadata.

## Adding a Select backend

Use this for project-specific pseudopotential ranking or cutoff policy.

Signature:

```python
SelectStage = Callable[
    [Structure, ParameterAdvice, KPointSelection, Sequence[PseudoMetadata]],
    SelectionRecord,
]
```

Select receives the Kmesh-stage grid. It should not call `k_distance_to_mesh()` or run model prediction.

## Adding an Advise backend

Use this when changing scientific intent:

- smearing policy
- SOC policy
- magnetic policy
- convergence defaults
- pseudopotential intent

Signature:

```python
AdviseStage = Callable[
    [StructureAnalysisRecord, CalculationIntent, CalculationHints],
    ParameterAdvice,
]
```

Advice should produce `ParameterAdvice` with provenance on every nested record. Analyze and Advise must stay free of target keyword names and file-format syntax. The current Ry-valued advice fields are documented QE coupling to remove before treating the records as target-neutral.

## Adding an Analyze backend

Use this when changing structure fact extraction or conservative classification.

Signature:

```python
AnalyzeStage = Callable[[Structure], StructureAnalysisRecord]
```

Analyze should not choose parameters. If a new public fact is needed by later stages, add it to `StructureAnalysisRecord`.

## Adding a Bundle backend

Use this for a different deterministic output layout.

Signature:

```python
BundleStage = Callable[[CoreResult, str | Path], BundleRecord]
```

Bundle may write files and return a manifest dictionary. It should not submit jobs, copy private pseudo libraries, or inspect completed outputs.

## What not to extend

- Do not add backend fields to `CoreJobRequest`.
- Do not add global registries to Core.
- Do not bypass stage boundaries.
- Do not add compatibility shims or duplicate import paths.
- Do not add Runner/AiiDA/frontend concerns.
- Do not add new dependencies unless a stage genuinely needs one.
