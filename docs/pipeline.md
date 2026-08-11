# Pipeline

Goldilocks Core exposes one staged SCF workflow through `CoreService`. The same
service backs Python, CLI, HTTP, and MCP entry points.

## Reusable service

Use one service for repeated work. It owns lazy model state and closes resources
when the context exits.

```python
from goldilocks_core import CalculationHints, CoreService, PresetRequest
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata

request = PresetRequest(
    structure="Fe.cif",
    hints=CalculationHints(k_grid=(6, 6, 6), spin_polarized=True),
    pseudo_metadata=tuple(load_pseudo_metadata("pseudos")),
)

with CoreService() as core:
    recommendation = core.recommend(request)
    generated = core.generate(request, output_dir="run")

print(recommendation.selection.pseudopotentials)
for generated_file in generated.generated_files:
    print(generated_file.path)
print(generated.bundle.path)
```

`recommend` runs through Select. `generate` also runs Generate; its optional
`output_dir` publishes the generated files and `manifest.json` into a new
directory.

## Selected record queries

`compute` asks the DAG for selected record types and runs only their
prerequisites:

```python
from goldilocks_core import CalculationHints, CoreService, QueryRequest
from goldilocks_core.contracts import KPointSelection, StructureAnalysisRecord

request = QueryRequest(
    structure="Fe.cif",
    outputs=(StructureAnalysisRecord, KPointSelection),
    hints=CalculationHints(k_grid=(6, 6, 6)),
)

with CoreService() as core:
    records = core.compute(request)

print(records[StructureAnalysisRecord].reduced_formula)
print(records[KPointSelection].grid)
```

Record type IDs on CLI and transport boundaries are `analysis`, `advice`,
`k_points`, `selection`, and `generated_files`. Python requests use the record
types themselves.

## One-call entry points

For a single operation, `run_core_job` and `query_records` create a short-lived
service:

```python
from goldilocks_core import PresetRequest, QueryRequest, query_records, run_core_job
from goldilocks_core.contracts import StructureAnalysisRecord

result = run_core_job(PresetRequest(structure="Fe.cif", mode="recommend"))
records = query_records(
    QueryRequest(structure="Fe.cif", outputs=(StructureAnalysisRecord,))
)
```

Use `CoreService` when multiple calls should reuse loaded models or when task,
code, and model discovery is needed.

## K-point backends

K-points are resolved by `resolve_kpoints(structure, hints, backend)`. An
explicit `k_grid` wins over `k_spacing`; both bypass model loading. Without a
k-point hint, the configured QRF k-distance model is loaded lazily.

Put a `ModelSpec` on either request type to select a local k-index model:

```python
from goldilocks_core import CoreService, PresetRequest
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

with CoreService() as core:
    result = core.recommend(
        PresetRequest(structure="Fe.cif", kmesh_model=spec)
    )
```

The model specification is request data and is included in serialized requests.

## Task graph

The built-in `SCF_TASK` declares each stage's inputs and output record type.
`TaskDispatcher` selects the graph from `CalculationIntent.task`; the executor
resolves the minimal subgraph for a preset or query. `CoreRuntime` owns only
model lifecycle.

```text
Load -> Analyze -> Advise -> Select
Load -> Kmesh
Load + Advice + Select + Kmesh -> Generate
```

The shipped task is `scf_single_point`. New calculation tasks register another
`TaskHandler` containing a `TaskSpec`, context builder, and result assembler;
the executor itself remains task-agnostic.

## Direct stage composition

The service is not an access restriction. Scientific stages remain ordinary
functions:

```python
from goldilocks_core.advice import advise_parameters
from goldilocks_core.analysis import analyze_structure
from goldilocks_core.advisors import default_kmesh_advisor
from goldilocks_core.generation import generate_inputs
from goldilocks_core.io.structures import load_structure
from goldilocks_core.kmesh import resolve_kpoints
from goldilocks_core.selection import select_parameters

loaded = load_structure("Fe.cif")
analysis = analyze_structure(loaded)
advice = advise_parameters(analysis, intent, hints)
k_points = resolve_kpoints(loaded, hints, default_kmesh_advisor())
selection = select_parameters(loaded, advice, metadata)
files = generate_inputs(loaded, intent, advice, selection, k_points)
```

Use direct composition for intermediate inspection or project-specific work,
not to reproduce service dispatch in another wrapper.

## Stage responsibilities

- **Load** reads a `pymatgen.Structure` or periodic structure file.
- **Analyze** reports structure facts.
- **Advise** recommends physics and numerical settings with provenance.
- **Kmesh** resolves operator hints or a model into a concrete grid.
- **Select** chooses pseudopotentials and cutoffs.
- **Generate** creates target-code input files from completed records.

Bundle publication is a filesystem side effect of generation, not a separate
stage preset or job mode.
