# DAG runtime

Goldilocks executes calculation tasks as typed dependency graphs. Callers choose either a named preset or an arbitrary record query; the executor runs only the required stages.

## SCF graph

The built-in `scf_single_point` task registers six record-producing stages:

```text
Load -> Structure
Structure -> Analyze -> StructureAnalysisRecord
Structure -> Kmesh -> KPointSelection
StructureAnalysisRecord -> Advise -> ParameterAdvice
Structure + ParameterAdvice -> Select -> SelectionRecord
Structure + ParameterAdvice + SelectionRecord + KPointSelection
    -> Generate -> GeneratedFiles
```

The exact dependencies are:

- Analyze needs `Structure`.
- Kmesh needs `Structure` and is independent of Analyze.
- Advise needs `StructureAnalysisRecord`.
- Select needs `Structure` and `ParameterAdvice`; it does not need Kmesh.
- Generate needs `Structure`, `ParameterAdvice`, `SelectionRecord`, and `KPointSelection`.

Analyze and Kmesh are parallel graph roots after Load. The executor currently evaluates the resolved graph in dependency order, but the graph does not impose an order between independent branches.

## Stages

A stage is a pure function with one declared output type, declared upstream input types, and access to a read-only run context.

- **Load** reads a `pymatgen.Structure` or structure file.
- **Analyze** reports structure, symmetry, dimensionality, and electronic-character facts.
- **Advise** recommends scientific and numerical settings with provenance.
- **Kmesh** resolves operator hints or a model into a concrete grid.
- **Select** chooses pseudopotentials and cutoffs.
- **Generate** renders calculation input files from all required choices.

The context carries request data and runtime-owned services. A stage does not own model lifecycle or transport state.

## Minimal execution and memoization

Outputs are identified by their contract types. The executor recursively resolves each output's producer and prerequisites, detects cycles or missing producers, and executes each resolved stage once.

Examples:

- `KPointSelection` runs Load and Kmesh only.
- `SelectionRecord` runs Load, Analyze, Advise, and Select; Kmesh does not run.
- `GeneratedFiles` resolves all six stages.
- requesting both `ParameterAdvice` and `SelectionRecord` computes their shared prerequisites once.

Only explicitly requested records are returned from a query.

## Presets

A preset is a named, complete `CoreResult` composition for a task:

- `recommend`: `StructureAnalysisRecord`, `ParameterAdvice`, `KPointSelection`, and `SelectionRecord`;
- `generate`: all recommendation records plus `GeneratedFiles`.

```python
from goldilocks_core import CalculationHints, generate, recommend

recommendation = recommend(
    "Fe.cif",
    hints=CalculationHints(k_grid=(6, 6, 6)),
)
print(recommendation.k_points.grid)

generated = generate(
    "Fe.cif",
    hints=CalculationHints(k_grid=(6, 6, 6)),
    pseudo_metadata=metadata,
    output_dir="run/",
)
print(generated.generated_files)
print(generated.bundle.path)
```

`output_dir` does not add another graph stage or mode. It asks the generate entrypoint to publish the assembled result after graph execution.

## Queries

A query asks for any subset of supported output records and returns `CoreRecords`:

```python
from goldilocks_core import CalculationHints, CoreJobRequest, CoreRuntime
from goldilocks_core.contracts import KPointSelection, StructureAnalysisRecord

request = CoreJobRequest(
    structure="Fe.cif",
    hints=CalculationHints(k_grid=(6, 6, 6)),
)

with CoreRuntime() as runtime:
    records = runtime.compute(
        (StructureAnalysisRecord, KPointSelection),
        request,
    )

analysis = records[StructureAnalysisRecord]
k_points = records[KPointSelection]
print(records.to_dict())
```

The supported query types are:

- `StructureAnalysisRecord`
- `ParameterAdvice`
- `KPointSelection`
- `SelectionRecord`
- `GeneratedFiles`

For serialized dispatch, put the resolved types on `CoreJobRequest.outputs`:

```python
from goldilocks_core import CoreJobRequest, run_core_job
from goldilocks_core.contracts import KPointSelection, SelectionRecord

records = run_core_job(
    CoreJobRequest(
        structure="Fe.cif",
        outputs=(KPointSelection, SelectionRecord),
    )
)
```

`CoreJobRequest.outputs` takes precedence over `mode`. CLI, HTTP, and MCP resolve public record names to these types before execution.

## Runtime reuse

`run_core_job()` creates a temporary `CoreRuntime` unless a caller supplies one. Reuse a runtime for repeated jobs so lazily loaded k-mesh and metallicity models remain available:

```python
from goldilocks_core import CoreJobRequest, CoreRuntime, run_core_job

with CoreRuntime() as runtime:
    first = run_core_job(CoreJobRequest(structure="Fe.cif"), runtime=runtime)
    second = run_core_job(CoreJobRequest(structure="Si.cif"), runtime=runtime)
```

The HTTP and MCP servers follow this pattern with one runtime per process.

## K-point backends

Explicit `k_grid` takes precedence over `k_spacing`; both bypass the model backend. Without either hint, the runtime uses its lazily loaded QRF k-distance backend.

A request can select a local k-index model with `CoreJobRequest.kmesh_model`:

```python
from goldilocks_core import CoreJobRequest, run_core_job
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

result = run_core_job(
    CoreJobRequest(structure="Fe.cif", mode="recommend", kmesh_model=spec)
)
```

The model spec is request data and serializes with the job.
