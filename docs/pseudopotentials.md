# Pseudopotential tables

Goldilocks needs pseudopotential metadata to select UPF files and energy
cutoffs. You can install a table that Goldilocks manages, or use a directory of
UPF files that you manage.

## Use the default table

The default runtime profile includes a scalar-relativistic PBEsol efficiency
table. It is suitable for a normal PBEsol calculation without spin-orbit
coupling (SOC).

Install the profile once:

```bash
uv run goldilocks assets install default
```

Check it:

```bash
uv run goldilocks assets verify default
```

You can now run a PBEsol calculation:

```bash
uv run goldilocks recommend structure.cif
```

## Choose a different table

Select an exact table ID with `--pseudo-table` or `PresetRequest.pseudo_table`.
The table must agree with the calculation functional, accuracy tier,
relativistic treatment, and every element in the structure. Core reports all
disagreements before selection.

- Use an `efficiency` table for normal calculations.
- Use a `precision` table with `--pseudo-accuracy precision`.
- Use an `sr` table for a calculation without SOC.
- Use an `fr` table for a calculation with SOC.
- Use an SSSP table for lanthanides or actinides. Selection refuses PseudoDojo
  pseudopotentials for these elements: its lanthanide table freezes 4f
  electrons assuming a trivalent ion (wrong for Eu, Yb, and Ce) and no
  PseudoDojo table covers actinides at all. SSSP has no fully-relativistic
  table, so these elements also cannot use SOC pseudopotentials.

### PseudoDojo scalar-relativistic tables

- `pseudodojo-pbesol-efficiency-sr`
- `pseudodojo-pbesol-precision-sr`
- `pseudodojo-pbe-efficiency-sr`
- `pseudodojo-pbe-precision-sr`
- `pseudodojo-lda-efficiency-sr`
- `pseudodojo-lda-precision-sr`

### PseudoDojo fully relativistic tables for SOC

- `pseudodojo-pbesol-efficiency-fr`
- `pseudodojo-pbesol-precision-fr`
- `pseudodojo-pbe-efficiency-fr`
- `pseudodojo-pbe-precision-fr`

Install the table, then select the same ID:

```bash
uv run goldilocks assets install pseudodojo-pbesol-efficiency-fr
uv run goldilocks recommend structure.cif --spin-orbit-coupling true --pseudo-table pseudodojo-pbesol-efficiency-fr
```

Python requests carry the ID; Core verifies and loads its installed manifest
only when Select is required:

```python
from goldilocks_core import CalculationHints, CoreService, PresetRequest

request = PresetRequest(
    structure="structure.cif",
    hints=CalculationHints(spin_orbit_coupling=True),
    pseudo_table="pseudodojo-pbesol-efficiency-fr",
)

with CoreService() as core:
    result = core.generate(request, output_dir="run")
```

The default profile contains only an `sr` table. It cannot supply the fully
relativistic UPFs that an SOC calculation needs.

### SSSP tables

SSSP tables cover the lanthanides and actinides as well as the lighter
elements. Select the one table matching the calculation:

- `sssp-pbesol-efficiency-sr`
- `sssp-pbesol-precision-sr`
- `sssp-pbe-efficiency-sr`
- `sssp-pbe-precision-sr`

Install the table, then put its exact ID on the CLI or Python request. The
default profile does not include an SSSP table.

SSSP 1.3.0 PBEsol tables reuse pseudopotentials and input parameters from the
PBE library; SSSP did not validate those PBEsol tables with its convergence
protocol. Goldilocks preserves this provenance rather than presenting the
cutoffs as PBEsol-validated.

The registry also contains `pseudodojo-pbe-lanthanides-sr`. It assumes
trivalent f-in-core ions and is not suitable for every lanthanide, so
selection never uses it for lanthanide or actinide elements; only an SSSP
table can serve them.

Installing a table does not change the request default. Without an explicit
source, Core uses `pseudodojo-pbesol-efficiency-sr`; it does not choose among
installed tables by scanning the asset store.

## Check an installed table

Show its state:

```bash
uv run goldilocks assets status pseudodojo-pbesol-efficiency-fr
```

Check every installed file:

```bash
uv run goldilocks assets verify pseudodojo-pbesol-efficiency-fr
```

The state is `installed`, `missing`, or `corrupt`. Run `assets install` again
to replace a corrupt table transactionally.

## Use your own UPF files

Use `--pseudo-root` to read a directory that you manage:

```bash
uv run goldilocks generate structure.cif --pseudo-root pseudos --k-grid 4 4 4 --out run
```

Goldilocks reads `.upf` and `.UPF` files recursively. It does not copy or
change them. The UPF header or a recognized provider sidecar must identify the
scientific metadata and provide two finite positive cutoffs for every selected
element. Arbitrary JSON files and filename words are not treated as scientific
facts.

The recognized sidecar filenames are a fixed convention:

- PseudoDojo: one `.djrepo` beside each UPF (same stem).
- SSSP: any `*.json` beside the UPF, or exactly one table-level JSON named
  `<directory>.json` one level above it (for example `pseudos/` with
  `pseudos.json` beside it). A table-level JSON must cover every UPF in that
  directory.

Other parent-directory layouts are not searched: keep sidecars beside their
UPF files, or follow the one table-level filename above.

`pseudo_metadata`, `pseudo_root`, and `pseudo_table` are mutually exclusive.
Explicit metadata is useful for in-memory callers; an explicit root remains
operator-managed; an exact table ID resolves through the verified asset store.

## Find installed files

Goldilocks uses this directory on a normal Linux system:

```text
~/.local/share/goldilocks/assets
```

Set `GOLDILOCKS_ASSET_ROOT` to use a different directory. If
`XDG_DATA_HOME` is set, the default is `$XDG_DATA_HOME/goldilocks/assets`.

Each version has its own directory:

```text
<asset-store>/<asset-id>/<version>/
```

Treat this directory as read-only. Use the `assets` commands to install, check,
or repair its contents.

## Licences and citations

Pseudopotential files keep their upstream licences. The Goldilocks BSD licence
does not apply to those files. Goldilocks does not include UPF files in its
wheel or source archive.

PseudoDojo table definitions record CC BY 4.0. Cite van Setten et al.,
*Computer Physics Communications* 226, 39–54 (2018).

SSSP 1.3.0 contains files from different pseudopotential families. The Materials
Cloud record is CC BY 4.0. Individual files can use GPL-2.0-or-later, GPL-3.0,
CC BY 3.0, CC BY 4.0, or CC BY-SA 4.0. Read the SSSP
[`LICENSE.txt`](https://archive.materialscloud.org/records/rcyfm-68h65/files/LICENSE.txt?download=1)
before you redistribute an SSSP table.

Upstream sources:

- [PseudoDojo](https://www.pseudo-dojo.org/)
- [SSSP 1.3.0](https://archive.materialscloud.org/records/rcyfm-68h65)
