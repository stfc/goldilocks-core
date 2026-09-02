# Pseudopotential tables

Goldilocks needs pseudopotential metadata to select UPF files and energy
cutoffs. You can install a table that Goldilocks manages, or use a directory of
UPF files that you manage.

## Use automatic table selection

Without an explicit source, Core chooses a registered table matching the
requested functional, accuracy, relativistic treatment, and structure
elements. It prefers PseudoDojo for ordinary elements and requires SSSP for
lanthanides or actinides. The default runtime profile installs the preferred
scalar-relativistic PBEsol efficiency table for a normal calculation without
spin-orbit coupling (SOC).

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
uv run goldilocks compute structure.cif --preset recommend --no-out
```

## Choose a different table

Select an exact table ID with `--pseudo-table` or `CalculationDraft.pseudo_table`.
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
uv run goldilocks compute structure.cif --preset recommend --spin-orbit-coupling true --pseudo-table pseudodojo-pbesol-efficiency-fr --no-out
```

Python requests carry the ID; Core verifies and loads its installed manifest
only when Select is required:

```python
from goldilocks_core import (
    CalculationDraft,
    CalculationHints,
    ComputeRequest,
    DirectoryOutput,
    PathStructureSource,
    PresetSelection,
    Service,
)
from goldilocks_core.examples.structures import structures_path

request = ComputeRequest(
    CalculationDraft(
        PathStructureSource(structures_path() / "Si.cif"),
        hints=CalculationHints(spin_orbit_coupling=True),
        pseudo_table="pseudodojo-pbesol-efficiency-fr",
    ),
    PresetSelection("generate"),
)

with Service() as core:
    result = core.compute(request, output=DirectoryOutput("run"))
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

Some UPFs in SSSP's scalar-relativistic tables declare themselves
non-relativistic. Goldilocks preserves that per-file treatment on the selected
record and archive instead of relabelling it scalar. Core permits the file only
for a scalar request and emits a compatibility warning for operator review.

The registry also contains `pseudodojo-pbe-lanthanides-sr`. It assumes
trivalent f-in-core ions and is not suitable for every lanthanide, so
selection never uses it for lanthanide or actinide elements; only an SSSP
table can serve them.

Automatic selection reads the scientific registry, not the set of directories
currently installed in the asset store. If the preferred compatible table is
missing, Core reports its exact asset ID and version so `--fetch-missing` can
install that dependency.

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

Asset stores installed by older releases used `schema_version: 1` manifests
and bare or namespaced table directories; they are incompatible with the
strict manifest reader. Reinstall affected assets:

```bash
uv run goldilocks assets install workbench
```

## Use your own UPF files

Use `--pseudo-root` to read a directory that you manage:

```bash
uv run goldilocks compute structure.cif --preset generate --pseudo-root pseudos --k-grid 4 4 4 --out run
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

Generating publishable DFT Input Data from a local root also requires the
operator to declare the real redistribution terms and source citation. Put a
`goldilocks-pseudopotentials.json` sidecar at the root:

```json
{
    "schema_version": 1,
    "licence": "the actual licence name or SPDX expression",
    "licence_file": "LICENSE.txt",
    "citation": "the citation requested by this pseudopotential source"
}
```

`licence_file` is a relative path contained under the root. Goldilocks reads
and publishes that file verbatim with the selected UPFs. It does not infer a
licence from a provider name, UPF filename, or cutoff sidecar. Recommendation
can inspect a root without this publication sidecar, but generation fails
clearly until complete legal and citation material is supplied.

`pseudo_metadata`, `pseudo_root`, and `pseudo_table` are mutually exclusive.
Explicit metadata is useful for in-memory callers; an explicit root remains
operator-managed; an exact table ID resolves through the verified asset store.
HTTP and MCP expose only `pseudo_table`: callers may choose a registered
scientific set by stable ID without transmitting metadata, roots, or files.
Build explicit metadata with `parse_upf_metadata`, which binds the file's SHA-256
and size from one binary read. Generation rereads the file once and requires that
binding to match. `source_identifier` must be a provider-relative identity or URL,
not an absolute or home-relative host path.

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

Asset installation stores licence material as `LICENSE.txt` beside each
normalized table. PseudoDojo installations receive the table's CC BY 4.0
notice; SSSP installations preserve the upstream record's complete mixed-family
licence file. Workbench calculation archives include that installed licence
material with the selected UPFs.

Upstream sources:

- [PseudoDojo](https://www.pseudo-dojo.org/)
- [SSSP 1.3.0](https://archive.materialscloud.org/records/rcyfm-68h65)
