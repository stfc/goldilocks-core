# Tutorial

This walkthrough uses the preset and query surfaces of the DAG runtime. The package includes small example structures, so the recommendation examples run without your own file.

```python
from goldilocks_core.examples import available_structures, structure

print(available_structures())  # ('Fe_bcc.cif', 'Pt_fcc.cif', 'Si.cif')
si = structure("Si.cif")
```

Everywhere below, `"structure.cif"` can instead be your own structure path.

## Recommend with Python

`recommend()` runs the named recommendation preset and returns a complete `CoreResult`:

```python
from goldilocks_core import CalculationHints, recommend

result = recommend(
    si,
    hints=CalculationHints(k_grid=(4, 4, 4)),
)

print(result.analysis.reduced_formula)                 # "Si"
print(result.analysis.electronic_character)
print(result.analysis.electronic_character_source)     # "heuristic" or "model"
print(result.analysis.electronic_character_confidence) # None for the heuristic
print(result.k_points.grid)                            # (4, 4, 4)
print(result.k_points.provenance.source)               # "user_hint"
print(result.to_dict())                                # JSON-safe dictionary
```

The recommendation preset computes:

- `StructureAnalysisRecord`;
- `ParameterAdvice`;
- `KPointSelection`;
- `SelectionRecord`.

K-points are a sibling record at `result.k_points`; they are not part of `result.selection`.

## Override scientific defaults

```python
from goldilocks_core import CalculationHints, recommend

result = recommend(
    si,
    hints=CalculationHints(
        k_grid=(4, 4, 4),
        spin_polarized=True,
        smearing_type="cold",
        smearing_width_ry=0.01,
    ),
)

print(result.k_points.provenance.source)          # "user_hint"
print(result.advice.magnetism.provenance.source)  # "user_hint"
print(result.advice.smearing.provenance.source)   # "user_hint"
print(result.advice.convergence.provenance.source) # "default"
```

Each decision records why it was made, its data source where applicable, optional confidence, structured details, and warnings.

## Generate and publish files

Generation needs pseudopotential metadata that covers every element. Load metadata from a local pseudopotential tree, then pass an output directory to publish the generated files and manifest:

```python
from goldilocks_core import CalculationHints, generate
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata

pseudo_metadata = load_pseudo_metadata("path/to/pseudopotentials")

result = generate(
    "structure.cif",
    hints=CalculationHints(k_grid=(4, 4, 4), pseudo_type="NC"),
    pseudo_metadata=pseudo_metadata,
    output_dir="run/",
)

for generated_file in result.generated_files:
    print(generated_file.path)     # e.g. "inputs/qe.in"
    print(generated_file.content)

print(result.bundle.path)          # "run/"
print(result.bundle.manifest)
```

`run/manifest.json` and the generated input files now exist. The destination must be new. Publication is an option on generation, not a separate job mode.

Omit `output_dir` to receive generated file records without writing them:

```python
result = generate(
    "structure.cif",
    hints=CalculationHints(k_grid=(4, 4, 4)),
    pseudo_metadata=pseudo_metadata,
)

assert result.bundle is None
```

## Query partial results with compute

Use `CoreRuntime.compute()` when only selected records are needed. The executor resolves the minimal subgraph and returns a type-keyed `CoreRecords` mapping:

```python
from goldilocks_core import CalculationHints, CoreJobRequest, CoreRuntime
from goldilocks_core.contracts import KPointSelection, StructureAnalysisRecord

request = CoreJobRequest(
    structure=si,
    hints=CalculationHints(k_grid=(4, 4, 4)),
)

with CoreRuntime() as runtime:
    records = runtime.compute(
        (StructureAnalysisRecord, KPointSelection),
        request,
    )

analysis = records[StructureAnalysisRecord]
k_points = records[KPointSelection]
print(analysis.reduced_formula)
print(k_points.grid)
print(records.to_dict())
```

This query runs Load, Analyze, and Kmesh. It does not run Advise, Select, or Generate.

For a serializable job request, put output types on `CoreJobRequest.outputs` and dispatch with `run_core_job()`:

```python
from goldilocks_core import CoreJobRequest, run_core_job
from goldilocks_core.contracts import ParameterAdvice, SelectionRecord

records = run_core_job(
    CoreJobRequest(
        structure=si,
        outputs=(ParameterAdvice, SelectionRecord),
    )
)
```

`outputs` selects a query and takes precedence over `mode`.

## Reuse model state

A supplied runtime remains open across calls and reuses lazily loaded model state:

```python
from goldilocks_core import CoreJobRequest, CoreRuntime, run_core_job

with CoreRuntime() as runtime:
    silicon = run_core_job(CoreJobRequest(structure=si), runtime=runtime)
    iron = run_core_job(
        CoreJobRequest(structure=structure("Fe_bcc.cif")),
        runtime=runtime,
    )
```

Without a supplied runtime, `run_core_job()` creates and closes one for the call.

## Use a local k-mesh model

Put a `ModelSpec` on the request to replace the default QRF k-distance backend with a local k-index model:

```python
from goldilocks_core import CoreJobRequest, run_core_job
from goldilocks_core.contracts import ModelSpec

spec = ModelSpec(
    name="local-kmesh-model",
    version="v0",
    model_type="random_forest",
    target="k_index",
    feature_set="cslr",
    source="local",
    location="path/to/model.joblib",
)

result = run_core_job(
    CoreJobRequest(structure=si, mode="recommend", kmesh_model=spec)
)

print(result.k_points.grid)
print(result.k_points.provenance.source)       # "model"
print(result.k_points.provenance.data_source)  # spec.name
```

Explicit k-point hints take precedence and bypass model inference.

## CLI equivalents

Recommendation preset:

```bash
goldilocks-core recommend structure.cif --k-grid 4 4 4 --json
```

Generation preset with publication:

```bash
goldilocks-core generate structure.cif \
    --pseudo-root path/to/pseudopotentials \
    --pseudo-type NC \
    --k-grid 4 4 4 \
    --out run/ \
    --json
```

Partial query:

```bash
goldilocks-core compute structure.cif \
    --outputs StructureAnalysisRecord,KPointSelection \
    --k-grid 4 4 4
```

The compute command always emits a JSON object containing only the requested record names.

## Error handling

- Invalid hints fail when `CalculationHints` is constructed.
- Unsupported tasks fail before graph execution.
- Unknown query output names fail during output-type resolution.
- Missing pseudopotentials appear as warned selections; Generate rejects incomplete selections.
- Disordered structures carry analysis warnings; Generate rejects unresolved occupancies.
- Model loading and inference errors propagate.
- Publication rejects an existing destination or paths that escape it.
