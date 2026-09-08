# Tutorial

This tutorial inspects a structure, computes recommendations, and publishes
Quantum ESPRESSO SCF inputs through the canonical Python interface.

## Inspect a structure

```python
from goldilocks_core import PathStructureSource, Service

source = PathStructureSource("structure.cif")
with Service() as core:
    inspection = core.inspect_structure(source)

print(inspection.structure.reduced_formula)
print(inspection.canonical_cif)
```

`StructureInspection` retains source identity, canonical CIF, lattice, sites,
species occupancies, formula, and periodicity.

## Compute a recommendation

Use an explicit grid for a deterministic first run that does not load the
k-point model:

```python
from goldilocks_core import (
    CalculationDraft,
    CalculationHints,
    ComputeRequest,
    PresetSelection,
    Service,
)

request = ComputeRequest(
    CalculationDraft(
        source,
        hints=CalculationHints(k_grid=(4, 4, 4)),
        pseudo_table="pseudodojo-pbesol-efficiency-sr",
    ),
    PresetSelection("recommend"),
)

with Service() as core:
    result = core.compute(request)

print(result.records.to_dict()["analysis"]["reduced_formula"])
print(result.records.to_dict()["k_points"]["grid"])
print(result.warnings)
```

`recommend` is a Preset ID. It requests analysis, advice, k-points, and
pseudopotential selection without generating runnable input data.

## Generate an input bundle

Select the `generate` Preset and a Core output target:

```python
from goldilocks_core import DirectoryOutput

request = ComputeRequest(request.draft, PresetSelection("generate"))
with Service() as core:
    result = core.compute(request, output=DirectoryOutput("run"))

print(result.bundle.path)
```

The destination must not already exist. Omit the output target or use `None`
for memory-only structured output.

The bundle contains `qe.in` and `manifest.json` with scientific choices and
provenance. It does not copy pseudopotentials. Supply the selected UPFs under
`pseudo/` so the generated input's `pseudo_dir = './pseudo'` resolves correctly.

## Select explicit Records

```python
from goldilocks_core import RecordSelection
from goldilocks_core.contracts import KPointSelection, StructureAnalysisRecord

query = ComputeRequest(
    request.draft,
    RecordSelection((StructureAnalysisRecord, KPointSelection)),
)
with Service() as core:
    result = core.compute(query)
```

Only dependencies required by the selected Records execute.

## Reuse Runtime state

```python
with Service() as core:
    capabilities = core.capabilities()
    first = core.compute(request)
    second = core.compute(query)

print([preset.id for preset in capabilities.tasks[0].presets])
```

One Service reuses lazy model state and supports concurrent Compute calls. Capabilities
replaces separate task, code, and model discovery operations.

## CLI

```bash
uv run goldilocks recommend structure.cif --k-grid 4 4 4 --json
uv run goldilocks generate structure.cif --pseudo-root pseudos --k-grid 4 4 4 --out run --json
```

## HTTP

HTTP Structure Sources are explicit inline content:

```json
{
  "structure": {
    "content": "data_Si ...",
    "format": "cif"
  },
  "hints": {"k_grid": [4, 4, 4]}
}
```

Send this body to `POST /generate`. The JSON response contains the selected
scientific Records and generated input contents. Use `POST /recommend` for
recommendations, or add `"outputs": ["analysis"]` and call `POST /compute`
for a Record query. The server stores no output.

## MCP

Local stdio MCP exposes `recommend`, `generate`, `compute`, `list_tasks`,
`list_codes`, and `list_models`. Scientific tools accept the same flat structure,
intent, and hints as HTTP; `compute` also requires an `outputs` list.
Results remain in memory without an output directory.

MCP does not accept structure paths, pseudopotential roots, model locations, or
publication paths. Use the CLI or Python interface for trusted local filesystem
configuration.
