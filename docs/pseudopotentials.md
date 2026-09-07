# Pseudopotential tables

A table is a named collection of pseudopotential files in UPF format and
recommended energy cutoffs. Goldilocks supports tables from PseudoDojo and SSSP.
Start with the default table in the [quickstart](quickstart.md); use this page
to choose another table or supply your own files.

## Choose a table

List the registered choices and their supported elements, functional, accuracy,
and relativistic treatment:

```bash
uv run goldilocks capabilities --json
```

The `pseudopotential_sets` array lists the available tables. Use `assets status`
to check which are installed.

Without an explicit source, Goldilocks chooses a compatible registered table,
preferring PseudoDojo unless the structure contains lanthanides or actinides. It
does not choose a different table merely because that table is installed. The
`default` asset profile includes the scalar-relativistic PBEsol efficiency
table, plus the default k-point and metallicity models.

To choose a table explicitly, use `--pseudo-table` or
`CalculationDraft.pseudo_table`. Its functional, accuracy tier, relativistic
treatment, and element coverage must match the request. In particular:

- `precision` tables require `--pseudo-accuracy precision`; this is a library
  tier, not a guarantee of convergence for your calculation.
- Table suffixes `sr` and `fr` mean scalar relativistic and fully relativistic.
  Explicit spin-orbit coupling (SOC) needs fully relativistic files; the default
  profile contains only an `sr` table.
- Lanthanides and actinides must use SSSP under Goldilocks' selection policy,
  with coverage checked for the actual elements. PseudoDojo's lanthanide table
  freezes 4f electrons in the core assuming trivalent ions, which is not
  suitable for all oxidation states; its tables do not cover actinides. No
  registered SSSP table is fully relativistic, so automatic or explicit
  registered-table selection cannot supply SOC for these elements.
- SSSP 1.3.0 PBEsol tables reuse PBE input parameters and cutoffs and were not
  tested with the SSSP convergence protocol. Do not treat these as
  PBEsol-validated cutoffs.
- Some files in SSSP scalar-relativistic tables declare non-relativistic
  treatment. Goldilocks permits this exception for scalar requests, preserves
  the per-file treatment, and emits a compatibility warning.

The [scientific guide](science.md#check-pseudopotentials-and-cutoffs) explains
what to check before using selected cutoffs.

## Install and select it

The commands below assume Goldilocks is installed. Replace `structure.cif` with
your ordered structure file. This example installs and selects fully
relativistic PBEsol files for an SOC recommendation:

```bash
uv run goldilocks assets install pseudodojo-pbesol-efficiency-fr
uv run goldilocks compute structure.cif --preset recommend --spin-orbit-coupling true --pseudo-table pseudodojo-pbesol-efficiency-fr
```

Use the [asset commands](cli.md#install-and-check-assets) if a required model or
table is missing.

Check installation state and verify file integrity:

```bash
uv run goldilocks assets status pseudodojo-pbesol-efficiency-fr
uv run goldilocks assets verify pseudodojo-pbesol-efficiency-fr
```

Status is `installed`, `missing`, or `corrupt`. Repeat `assets install` to
repair a corrupt installation. Verification checks stored files, not scientific
accuracy.

### Read installed metadata in Python

For ordinary calculations, pass the table ID on `CalculationDraft`; see the
[Python tutorial](tutorial.md). To inspect its installed metadata directly:

```python
from goldilocks_core.assets.store import AssetStore
from goldilocks_core.pseudo.installed import load_installed_table
from goldilocks_core.pseudo.registry import load_tables

table = load_tables()["pseudodojo-pbesol-efficiency-fr"]
installed = AssetStore().resolve_spec(table.asset)
metadata = load_installed_table(installed, table=table)
for pseudo in metadata:
    print(pseudo.element, pseudo.filename, pseudo.cutoffs)
```

Managed PseudoDojo tables convert the provider's high cutoff hint from Hartree
to Ry and derive the charge-density cutoff using the registered multiplier
(currently 4). SSSP tables supply separate wavefunction and charge-density
cutoffs. Neither path optimizes cutoffs for your structure.

## Use your own UPF files

Replace `pseudos` with your UPF root and `structure.cif` with your structure.
This first command inspects a recommendation without publishing files:

```bash
uv run goldilocks compute structure.cif --preset recommend --pseudo-root pseudos
```

Goldilocks scans UPF files recursively, ignoring extension case, and leaves the
source directory unchanged. Check the parsed functional and relativistic
treatment against your request. UPF headers alone do **not** populate the
selection's cutoff fields. Recognized cutoff sidecars are:

- **PseudoDojo:** a `.djrepo` beside each UPF, with the same stem. Its checksum
  and functional must match. The high cutoff hint supplies `ecutwfc_ry`, but
  leaves `ecutrho_ry` unset for a custom root. Use a managed table or supply
  complete Python metadata before generation.
- **SSSP:** a JSON file beside the UPF with an element entry naming that file
  and providing both cutoffs. For UPFs in a subdirectory of the supplied root,
  Goldilocks also checks `<subdirectory>.json` in its parent. For example,
  `pseudos/table/Si.upf` can use `pseudos/table.json` when the supplied root is
  `pseudos`. It does not search outside the supplied root. More than one
  matching cutoff record is an error.

Unrelated JSON is ignored. A recommendation can contain missing cutoffs or
unresolved elements with warnings; generation needs a compatible file and two
finite positive cutoffs for every element.

### Supply licence and citation material

Before generating a complete output, add `goldilocks-pseudopotentials.json` at
the UPF root. Replace the descriptive strings below with the source's real terms
and citation, and place its licence text in `LICENSE.txt`:

```json
{
  "schema_version": 1,
  "licence": "Actual licence name or SPDX expression",
  "licence_file": "LICENSE.txt",
  "citation": "Citation required by the pseudopotential source"
}
```

`licence_file` must be a relative POSIX path contained under the root, without
`.` or `..` components. Its UTF-8 text must be nonempty. Goldilocks does not
infer redistribution rights from filenames or provider names. Recommendation can
proceed without this sidecar; a complete generated output cannot.

Once the scientific metadata and licence material are complete:

```bash
uv run goldilocks compute structure.cif --preset generate --pseudo-root pseudos --out run
```

Published outputs contain copies of the selected UPFs and licence text. Run QE
from the output root (`run` here), so `pseudo_dir = './pseudo'` resolves to the
published files, not the original UPF directory.

For Python-managed metadata, start with
`goldilocks_core.pseudo.parse_upf.parse_upf_metadata`, then supply the cutoffs
and legal metadata on `PseudoMetadata` (`cutoffs` and `pseudo_info`). Parsing
binds the file's SHA-256 and size; generation rejects changed file content. Keep
`source_identifier` a provider-relative identity or URL, not an absolute or
home-relative host path. `pseudo_metadata`, `pseudo_root`, and `pseudo_table`
are mutually exclusive. HTTP and MCP requests support only `pseudo_table`.

## Find stored assets

The default store is `$XDG_DATA_HOME/goldilocks/assets`, or
`~/.local/share/goldilocks/assets` when `XDG_DATA_HOME` is unset.
`GOLDILOCKS_ASSET_ROOT` overrides it. Table installations live at:

```text
<asset-store>/pseudopotentials/<table-id>/<version>/
```

Treat managed files as read-only; use `assets install`, `status`, and `verify`.

## Licences and citations

UPFs retain their upstream licences; the Goldilocks BSD licence does not apply
to them. UPFs are downloaded separately, not bundled in the package.

- [PseudoDojo](https://www.pseudo-dojo.org/): registered tables use CC BY 4.0.
  Cite van Setten et al., _Computer Physics Communications_ 226, 39–54 (2018).
- [SSSP 1.3.0](https://archive.materialscloud.org/records/rcyfm-68h65): cite
  Prandini et al., _npj Computational Materials_ 4, 72 (2018), and the data
  record. The record's CC BY 4.0 licence does not replace the individual UPF
  licences. Read its mixed-family
  [`LICENSE.txt`](https://archive.materialscloud.org/records/rcyfm-68h65/files/LICENSE.txt?download=1)
  before redistribution.

Installations store licence material in `LICENSE.txt`: the CC BY 4.0 notice for
PseudoDojo, or the upstream mixed-family licence file for SSSP. Published
calculation outputs include that material with the selected UPFs.
