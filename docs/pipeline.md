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
`generated_files` and `dft_input_data`.

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
`generated_files`, and `dft_input_data`.

## Output targets

`output=None` keeps the canonical Result in memory. `DirectoryOutput(path)` and
`ArchiveOutput(path)` atomically publish complete DFT Input Data and refuse an
existing destination. `DirectoryOutput()` allocates `goldilocks_out`, then
`goldilocks_out_1`, and so on. Automatic output leaves a Result without DFT
Input Data in memory rather than failing.

Directory and ZIP publication use the same extracted layout:

```text
source/
structure/
inputs/
pseudo/
licences/
CITATIONS.md
README.md
goldilocks.json
checksums.sha256
```

The output contains the original source when available, canonical CIF,
generated inputs, exact pseudopotentials, licence material, citations,
provenance, a manifest, and checksums. Publication never runs the target code.

## Stage graph

The built-in SCF graph is type keyed:

```text
Load -> Analyze -> Advise
Load -> Kmesh
Load + Advice -> Select
Load + Advice + Select + Kmesh -> Generate
Analysis + Advice + Kmesh + Select + Generate -> DFT Input Data
```

- **Load** normalizes the Structure Source.
- **Analyze** records structure facts.
- **Advise** chooses scientific and numerical intent with provenance.
- **Kmesh** resolves an operator hint or model result.
- **Select** resolves and selects concrete pseudopotentials.
- **Generate** renders target-code syntax.
- **DFT Input Data** binds every runnable artifact and its provenance.

The executor resolves dependencies from selected Record types. New tasks
register one `GraphHandler`; the generic Runtime and executor remain
stage-agnostic.

## K-point models

An explicit `k_grid` wins over `k_spacing`; both bypass model loading. Without
a hint, the configured QRF backend loads lazily. A request-specific
`ModelSpec` selects a local k-index model. Publishable custom-model results must
provide licence text and citation identity; Core does not invent attribution.

## Pseudopotential sources

A `CalculationDraft` accepts one of explicit metadata, a local root, or a
stable registered table ID. Without an explicit source, Select chooses a
compatible registered table. Resolution happens only when selected Records
depend on pseudopotentials.

Transport adapters expose only source variants appropriate to their seam:
HTTP accepts inline structures and stable table IDs; CLI and local MCP may also
accept local structure and pseudopotential paths.
