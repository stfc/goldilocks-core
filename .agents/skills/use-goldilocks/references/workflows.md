# Goldilocks workflows

Use these canonical patterns before reading implementation files.

## Inspect a Structure Source

```python
from goldilocks_core import PathStructureSource, Service

with Service() as core:
    inspection = core.inspect_structure(PathStructureSource("structure.cif"))

print(inspection.structure.reduced_formula)
print(inspection.canonical_cif)
```

## Compute a Preset

```python
from goldilocks_core import (
    CalculationDraft,
    CalculationHints,
    ComputeRequest,
    PathStructureSource,
    PresetSelection,
    Service,
)

request = ComputeRequest(
    CalculationDraft(
        PathStructureSource("structure.cif"),
        hints=CalculationHints(k_grid=(4, 4, 4)),
        pseudo_table="pseudodojo-pbesol-efficiency-sr",
    ),
    PresetSelection("recommend"),
)
with Service() as core:
    result = core.compute(request)

records = result.records.to_dict()
print(records["analysis"]["reduced_formula"])
print(records["k_points"]["grid"])
print(records["selection"]["pseudopotentials"])
print(result.warnings)
```

`PresetSelection("generate")` also returns `generated_files` and complete
`dft_input_data`.

## Publish Ready-to-run Output

```python
from goldilocks_core import DirectoryOutput

with Service() as core:
    result = core.compute(request, output=DirectoryOutput("run-dir"))

print(result.publication.path)
```

The destination must not exist. Use `ArchiveOutput("run.zip")` for ZIP,
`DirectoryOutput()` for automatic allocation, or `None` for memory-only output.
Directory and ZIP outputs contain the same logical files: source and canonical
structures, inputs, selected UPFs, licences, citations, provenance, and
checksums.

CLI equivalents:

```bash
uv run goldilocks compute structure.cif --preset generate --pseudo-table pseudodojo-pbesol-efficiency-sr --k-grid 4 4 4 --out run-dir --json
uv run goldilocks compute structure.cif --preset generate --pseudo-table pseudodojo-pbesol-efficiency-sr --k-grid 4 4 4 --archive run.zip --json
```

## Select Records

```python
from goldilocks_core import ComputeRequest, RecordSelection, compute
from goldilocks_core.contracts import KPointSelection, StructureAnalysisRecord

query = ComputeRequest(
    request.draft,
    RecordSelection((StructureAnalysisRecord, KPointSelection)),
)
result = compute(query)
print(result.records[StructureAnalysisRecord])
print(result.records[KPointSelection])
```

CLI equivalent:

```bash
uv run goldilocks compute structure.cif --outputs analysis,k_points --k-grid 4 4 4 --no-out --json
```

## Use a local pseudopotential root

```bash
uv run goldilocks compute structure.cif --preset generate --pseudo-root pseudos --k-grid 4 4 4 --out run-dir
```

`goldilocks-pseudopotentials.json` in the root must identify the real licence
file and citation before Core can publish local UPFs. Never invent missing
cutoffs or redistribution terms.

## Use a local k-point model

```python
from goldilocks_core.contracts import ModelSpec

model = ModelSpec(
    name="local-kmesh-model",
    version="v1",
    model_type="random_forest",
    target="k_index",
    feature_set="cslr",
    source="local",
    location="models/kmesh.joblib",
    licence="licence-id",
    licence_text="actual model licence text",
    citation="model citation",
)
request = ComputeRequest(
    CalculationDraft(
        PathStructureSource("structure.cif"),
        kmesh_model=model,
        pseudo_table="pseudodojo-pbesol-efficiency-sr",
    ),
    PresetSelection("generate"),
)
```

Publishable model-backed Results require licence and citation identity.

## Optional transports

```bash
uv sync --all-extras
uv run goldilocks serve http --host 127.0.0.1 --port 8000
uv run goldilocks serve mcp
```

HTTP accepts inline Structure Sources and returns one multipart response with
reviewed Result JSON and its exact optional ZIP. Local MCP accepts inline
content or paths and can publish local outputs. Both reuse one process-owned
`Service`.
