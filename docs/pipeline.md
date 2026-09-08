# Pipeline and stage behavior

Use one `Service` for repeated work. It owns lazy model state, serializes
computation, and closes owned resources.

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
        PathStructureSource("Fe.cif"),
        hints=CalculationHints(k_grid=(6, 6, 6)),
    ),
    PresetSelection("recommend"),
)

with Service() as core:
    result = core.compute(request)
```

## Public operations

`Service` exposes three scientific operations:

- `capabilities()` returns tasks, Presets, selectable Records, codes, models,
  pseudopotential sets, and defaults;
- `inspect_structure(source)` normalizes a Structure Source and returns a
  canonical `StructureInspection`;
- `compute(request, output=...)` executes one Preset or Record selection.

The top-level `compute()` convenience uses the same request and output
contracts. It owns a short-lived Runtime unless the caller supplies one.

## Compute selection

`PresetSelection("recommend")` requests `analysis`, `advice`, `k_points`, and
`selection`. `PresetSelection("generate")` additionally requests
`generated_files`.

Use `RecordSelection` for a minimal subgraph:

```python
from goldilocks_core import RecordSelection
from goldilocks_core.contracts import KPointSelection, StructureAnalysisRecord

request = ComputeRequest(
    draft,
    RecordSelection((StructureAnalysisRecord, KPointSelection)),
)
result = compute(request)
```

Results always use `ComputationResult`. Its `Records` mapping serializes class
keys as stable IDs: `analysis`, `advice`, `k_points`, `selection`,
and `generated_files`.

## Output targets

`output=None` keeps the canonical Result in memory. `DirectoryOutput(path)`
writes generated inputs and `manifest.json` to a new directory and refuses an
existing destination. Directory output requires the complete `generate`
record set; a partial Record selection remains available in memory.

For Quantum ESPRESSO the bundle contains `qe.in` and a manifest recording
analysis, advice, k-points, pseudopotential selection, file paths, and warnings.
It does not copy pseudopotentials or run the target code. Supply the selected
UPFs under the input's `pseudo_dir` before running the calculation.

## Stage graph

The built-in SCF graph is type keyed:

```text
Load -> Analyze -> Advise
Load -> Kmesh
Load + Advice -> Select
Load + Advice + Select + Kmesh -> Generate
```

- Core normalizes the Structure Source before executing the graph; **Load**
  supplies that normalized structure to its dependent stages.
- **Analyze** records structure facts.
- **Advise** chooses scientific and numerical intent with provenance.
- **Kmesh** resolves an operator hint or model result.
- **Select** resolves and selects concrete pseudopotentials.
- **Generate** renders target-code syntax.

The executor resolves dependencies from selected Record types. New tasks
register one `GraphHandler`; the generic Runtime and executor remain
stage-agnostic.

## K-point models

An explicit `k_grid` wins over `k_spacing`; both bypass model loading. Without
a hint, the configured QRF backend loads lazily. A request-specific
`ModelSpec` selects a local k-index model.

## Pseudopotential sources

A `CalculationDraft` accepts one of explicit metadata, a local root, or a
stable registered table ID. Without an explicit source, Select chooses a
compatible registered table. Resolution happens only when selected Records
depend on pseudopotentials.

Transport adapters expose only source variants appropriate to their seam.
HTTP and MCP accept inline structures and resolve pseudopotentials on the server.
They do not accept structure paths, pseudopotential roots or metadata payloads,
table overrides, model locations, or output paths. Python and CLI retain trusted
local sources and output targets.
