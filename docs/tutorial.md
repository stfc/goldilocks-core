# Tutorial

Goldilocks Core turns a periodic structure into provenance-backed DFT parameter
recommendations and Quantum ESPRESSO SCF input files.

## Run an installed example

Install the default runtime assets, then use an explicit k-point hint for a
deterministic first run that bypasses the k-point model:

```python
from goldilocks_core import CalculationHints, CoreService, PresetRequest
from goldilocks_core.examples import structure

request = PresetRequest(
    structure=structure("Si.cif"),
    hints=CalculationHints(k_grid=(4, 4, 4)),
)

with CoreService() as core:
    result = core.recommend(request)

print(result.analysis.reduced_formula)
print(result.k_points.grid)
print(result.k_points.provenance)
print(result.warnings)
```

`recommend` runs Load, Analyze, Advise, Kmesh, and Select. The
result contains analysis, advice, a concrete k-point selection,
pseudopotential selection, and aggregated warnings. This request resolves the
installed default pseudopotential table.

## Supply operator hints

Hints override only the fields they name:

```python
from goldilocks_core import CalculationHints, CoreService, PresetRequest

request = PresetRequest(
    structure="structure.cif",
    hints=CalculationHints(
        k_grid=(4, 4, 4),
        spin_polarized=True,
        spin_orbit_coupling=False,
        use_vdw=False,
        pseudo_type="NC",
        conv_thr=1.0e-8,
    ),
)

with CoreService() as core:
    result = core.recommend(request)

print(result.advice.magnetism.provenance.source)  # user_hint
print(result.k_points.grid)                       # (4, 4, 4)
```

Every recommendation retains its source and reason. Unspecified values remain
eligible for structure-derived advice or the configured model.

## Supply an operator-managed pseudopotential source

Selection consumes validated metadata records, not raw UPF contents. To use a
directory outside the asset store, point the request at it:

```python
from goldilocks_core import CalculationHints, CoreService, PresetRequest

request = PresetRequest(
    structure="structure.cif",
    hints=CalculationHints(k_grid=(4, 4, 4), pseudo_type="NC"),
    pseudo_root="pseudos",
)

with CoreService() as core:
    result = core.recommend(request)

for pseudo in result.selection.pseudopotentials:
    print(pseudo.element, pseudo.filename, pseudo.ecutwfc_ry, pseudo.ecutrho_ry)
```

Recommendation requires one scientifically compatible pseudopotential with
complete cutoffs for every structure element. Missing or inconsistent metadata
raises an explicit selection error; Core does not create fallback selections.

## Generate input files

```python
from goldilocks_core import CalculationHints, CoreService, PresetRequest

request = PresetRequest(
    structure="structure.cif",
    hints=CalculationHints(k_grid=(4, 4, 4), pseudo_type="NC"),
    pseudo_table="pseudodojo-pbesol-efficiency-sr",
)

with CoreService() as core:
    result = core.generate(request)

qe_input = result.generated_files[0]
print(qe_input.path)     # inputs/qe.in
print(qe_input.content)
```

To publish the generated files, pass a new output directory:

```python
with CoreService() as core:
    result = core.generate(request, output_dir="run")

print(result.bundle.path)
print(result.bundle.manifest)
# run/manifest.json and run/inputs/qe.in now exist
```

Publication refuses an existing destination and confines every generated path
inside the new directory.

## Query selected records

A `QueryRequest` names the Python record types needed by the caller. The DAG
runs only their prerequisites:

```python
from goldilocks_core import CalculationHints, CoreService, QueryRequest
from goldilocks_core.contracts import KPointSelection, StructureAnalysisRecord

request = QueryRequest(
    structure="structure.cif",
    outputs=(StructureAnalysisRecord, KPointSelection),
    hints=CalculationHints(k_grid=(4, 4, 4)),
)

with CoreService() as core:
    records = core.compute(request)

print(records[StructureAnalysisRecord].crystal_system)
print(records[KPointSelection].grid)
```

Transport and CLI queries use the stable IDs `analysis`, `advice`, `k_points`,
`selection`, and `generated_files` instead of Python class names.

## Reuse model state

Keep one service alive across requests. It lazily loads configured models,
serializes dispatch over shared state, and releases owned resources on close:

```python
from goldilocks_core import CoreService, PresetRequest

with CoreService() as core:
    first = core.recommend(PresetRequest(structure="Si.cif"))
    second = core.recommend(PresetRequest(structure="Ge.cif"))
    print(core.describe_tasks())
    print(core.describe_codes())
    print(core.describe_models())
```

For one call, use the convenience functions:

```python
from goldilocks_core import PresetRequest, QueryRequest, query_records, run_core_job
from goldilocks_core.contracts import StructureAnalysisRecord

result = run_core_job(PresetRequest(structure="Si.cif", mode="recommend"))
records = query_records(
    QueryRequest(structure="Si.cif", outputs=(StructureAnalysisRecord,))
)
```

## Select a local k-point model

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
        PresetRequest(structure="structure.cif", kmesh_model=spec)
    )

print(result.k_points.grid)
```

An explicit `k_grid` or `k_spacing` still wins and bypasses model inference.
Only load joblib artifacts from trusted sources.

## Serialize a request

Both request types produce JSON-safe dictionaries. The shared transport parser
accepts the same representation, including a `pymatgen.Structure`:

```python
import json
from pymatgen.core import Structure
from goldilocks_core import PresetRequest

request = PresetRequest(structure=Structure.from_file("structure.cif"))
body = request.to_dict()
print(json.dumps(body))
```

HTTP accepts that body at `POST /recommend` or `POST /generate`; the endpoint
selects the preset, so a conflicting `mode` is rejected. `POST /compute`
requires a non-empty `outputs` list. Request errors use a stable
`{"error": {"kind": ..., "message": ...}}` envelope.

## CLI and optional transports

```bash
uv run goldilocks recommend structure.cif --k-grid 4 4 4 --json
uv run goldilocks generate structure.cif --pseudo-root pseudos --k-grid 4 4 4 --out run --json
uv run goldilocks compute structure.cif --outputs analysis,k_points --k-grid 4 4 4
```

Install and run the optional servers with:

```bash
uv sync --all-extras
uv run goldilocks serve http --host 127.0.0.1 --port 8000
uv run goldilocks serve mcp
```

The HTTP server exposes operation and discovery endpoints. The MCP stdio server
exposes the same operations and discovery as six typed tools. Both keep one
`CoreService` alive for the server process.
