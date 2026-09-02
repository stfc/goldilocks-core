# Tutorial

This tutorial walks the Python API from a CIF file to published Quantum
ESPRESSO SCF inputs: inspect a structure, compute recommendations, select
individual records, and publish a ready-to-run bundle. The
[quickstart](quickstart.md) does the same through the CLI.

## Inspect a structure

```python
from goldilocks_core import PathStructureSource, Service
from goldilocks_core.examples.structures import structures_path

source = PathStructureSource(structures_path() / "Si.cif")
with Service() as core:
    inspection = core.inspect_structure(source)

print(inspection["structure"]["reduced_formula"])
print(inspection["structure"]["site_count"])
print(inspection["canonical_cif"])
```

`inspect_structure` returns a document with four keys: `source` (identity and
content hash of what you gave it), `structure` (formula, lattice, sites,
species, occupancies, periodicity), `canonical_cif`, and `schema_version`:

```text
Si
8
# generated using pymatgen
data_Si
...
```

Nothing scientific has happened yet — inspection normalizes the structure and
reports facts.

## Compute a recommendation

An empty draft lets every stage decide for itself. This loads the models and
recommends k-points, smearing, convergence settings, and pseudopotentials:

```python
from goldilocks_core import (
    CalculationDraft,
    ComputeRequest,
    PresetSelection,
    Service,
)
from goldilocks_core.serialization import to_portable

request = ComputeRequest(
    CalculationDraft(source, pseudo_table="pseudodojo-pbesol-efficiency-sr"),
    PresetSelection("recommend"),
)

with Service() as core:
    result = core.compute(request)

records = to_portable(result)["records"]
print(records["k_points"]["grid"])
print(records["advice"]["smearing"])
print(records["selection"]["pseudopotentials"][0]["ecutwfc_ry"])

# The shown values are part of the contract this tutorial documents; CI
# re-proves them on every run, so a model change flags the docs for review.
assert records["k_points"]["grid"] == [6, 6, 6]
assert records["advice"]["smearing"]["smearing_type"] == "cold"
assert records["selection"]["pseudopotentials"][0]["ecutwfc_ry"] == 48.0
```

For the bundled silicon example this prints:

```text
[6, 6, 6]
{'smearing_type': 'cold', 'width_ry': 0.01, 'provenance': {'source': 'analysis', 'reason': 'Model-classified metallic systems benefit from modest smearing.', ...}}
48.0
```

`recommend` is a preset ID. It requests the `analysis`, `advice`, `k_points`,
and `selection` records without generating runnable input data.

Every sub-dict carries a `provenance` block. The smearing provenance above
says the choice came from `analysis` — the metallicity model — not from a
fixed default and not from you. The same structure of provenance appears on
every recommendation, so you can always ask where a number came from. The
`assert` lines in the snippet pin the shown values: when a model update
changes a recommendation, CI fails here and the tutorial gets re-blessed.
[How recommendations are made](science.md) covers each source.

## Override with hints

Hints override the models. An explicit grid also skips loading the k-point
model entirely:

```python
from goldilocks_core import CalculationHints

request = ComputeRequest(
    CalculationDraft(
        source,
        hints=CalculationHints(k_grid=(4, 4, 4)),
        pseudo_table="pseudodojo-pbesol-efficiency-sr",
    ),
    PresetSelection("recommend"),
)
```

`CalculationHints` covers k-point spacing and grid, smearing type and width,
spin polarization, spin-orbit coupling, dispersion, and the convergence
settings. Every hint is optional; anything you omit stays with the advice
stages. The [CLI reference](cli.md#scientific-controls) maps every flag to its
hint field.

## Select explicit records

Presets are shorthand for a set of records. To run only a subgraph — here,
structure analysis and k-points — name the records:

```python
from goldilocks_core import RecordSelection, StructureAnalysisRecord, KPointSelection

query = ComputeRequest(
    request.draft,
    RecordSelection((StructureAnalysisRecord, KPointSelection)),
)
with Service() as core:
    result = core.compute(query)
```

Only the stages the selected records depend on execute. `result.records` is
keyed by the record classes themselves; `to_portable` projects those keys to
the stable IDs used on the wire (`analysis`, `advice`, `k_points`,
`selection`, `generated_files`, `dft_input_data`).

## Generate and publish inputs

`generate` additionally produces the generated files and the complete
ready-to-run bundle. Choose an output target:

```python
from goldilocks_core import DirectoryOutput

request = ComputeRequest(request.draft, PresetSelection("generate"))
with Service() as core:
    result = core.compute(request, output=DirectoryOutput("run"))

print(result.publication["path"])
```

- `DirectoryOutput("run")` writes a new directory; the destination must not
  exist.
- `ArchiveOutput("run.zip")` writes the same layout as one ZIP.
- `DirectoryOutput()` with no path allocates `goldilocks_out`, then
  `goldilocks_out_1`, and so on.
- `None` (the default) keeps everything in memory.

A publication contains the generated inputs, canonical and original
structures, the exact pseudopotential files, licence material, citations,
provenance, and checksums — the layout shown in the
[quickstart](quickstart.md). Extract an archive and run Quantum ESPRESSO from
its root so `pseudo_dir = './pseudo'` resolves.

## Reuse the Service

One `Service` owns its model state and reuses it across computations:

```python
with Service() as core:
    capabilities = core.capabilities()
    first = core.compute(query)
    second = core.compute(query)
```

## CLI, HTTP, and MCP

The CLI exposes the same three operations:

```bash
uv run goldilocks inspect structure.cif --json
uv run goldilocks compute structure.cif --preset generate --out run
```

HTTP and MCP expose the same operations over a running process. Both accept
inline structure content and a registered pseudopotential table ID — not
paths or publication destinations, which stay local to Python and the CLI.
The exact contract is in the [CLI reference](cli.md#optional-transports).