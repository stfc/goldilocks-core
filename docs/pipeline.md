# Pipeline and stage behavior

Use one `Service` for repeated work. It owns lazy model state, executes
Computations concurrently over that shared state, and closes owned resources.

```python
from goldilocks_core.calculation import CalculationHints
from goldilocks_core.io.structures import PathStructureSource
from goldilocks_core.request import CalculationDraft, ComputeRequest, PresetSelection
from goldilocks_core.runtime.service import Service

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
  canonical inspection dict;
- `compute(request, output=...)` executes one Preset or Record selection.

The top-level `compute()` convenience uses the same request and output
contracts. It owns a short-lived Runtime unless the caller supplies one.

## Compute selection

`PresetSelection("recommend")` requests `analysis`, `advice`, `k_points`, and
`selection`. `PresetSelection("generate")` additionally requests
`generated_files` and `dft_input_data`.

Use `RecordSelection` for a minimal subgraph:

```python
from goldilocks_core.analysis import StructureAnalysisRecord
from goldilocks_core.kmesh.resolve import KPointSelection
from goldilocks_core.request import RecordSelection
from goldilocks_core.runtime.service import compute

request = ComputeRequest(
    request.draft,
    RecordSelection((StructureAnalysisRecord, KPointSelection)),
)
result = compute(request)
```

Results always use `ComputationResult`. Its `records` field is a plain dict:
record-marker classes are keys and stage documents are dict values. For example,
`result.records[KPointSelection]["grid"]` reads the mesh. `to_portable(result)`
serializes record keys as stable IDs: `analysis`, `advice`, `k_points`,
`selection`, `generated_files`, and `dft_input_data`. Capabilities, Inspection,
and publication metadata are also dict documents, not attribute-based records.

## Output targets

`output=None` keeps the canonical Result in memory. `DirectoryOutput(path)` and
`ArchiveOutput(path)` atomically publish complete DFT Input Data and refuse an
existing destination. The Publisher writes into private staging, then installs
the completed output with a native no-replace rename. The destination parent
must be operator-controlled; hostile changes to private staging are out of scope.
Platforms without a native exclusive rename fail without installing output.
`DirectoryOutput()`
allocates `goldilocks_out`, then `goldilocks_out_1`, and so on. Automatic output
leaves a Result without DFT Input Data in memory rather than failing.
An explicit directory or archive path requires DFT Input Data and otherwise
raises an error. Successful publication is reported in
`result.publication["path"]`; memory-only Results have `publication=None`.

DFT Input Data holds the selected file bytes, not deferred Asset references.
Assembly checks external UPFs and licence files when it reads them.
Publication uses that snapshot without reopening the files or the Asset Store.
Changing or removing source files after Compute does not change its output.
JSON lists artifact paths and roles but excludes their contents.

Runtime provenance records model identities and Asset preparation fingerprints,
not full model-file inventories. Internal Records and generated content are
trusted; file hashes are calculated once when the Publisher builds the manifest.

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
```

The output contains the original source when available, canonical CIF,
generated inputs, exact pseudopotentials, licence material, citations,
and provenance. `goldilocks.json` records each payload's size and SHA-256 hash.
These hashes detect corruption; they do not establish authenticity.
Publication never runs the target code.

## Stage graph

The built-in SCF graph is type keyed:

```text
Load -> Analyze -> Advise
Load -> Kmesh
Load + Advice -> Select
Load + Advice + Select + Kmesh -> Generate
Analysis + Advice + Kmesh + Select + Generate -> DFT Input Data
```

- Core normalizes the Structure Source before executing the graph; **Load**
  supplies that normalized structure to its dependent stages.
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

Transport adapters expose only source variants appropriate to their seam.
HTTP and MCP accept inline structures and stable registered table IDs. They do
not accept structure paths, pseudopotential roots or metadata payloads, model
locations, or publication paths. Python and CLI retain trusted local sources
and output targets.
