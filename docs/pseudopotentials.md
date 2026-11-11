# Pseudopotential tables

A table is a named collection of pseudopotential files in UPF format and
recommended energy cutoffs. Goldilocks supports tables from PseudoDojo and SSSP.
Start with the default table in the [quickstart](quickstart.md); use this page
to choose another registered table, or to find the assets and licence
material Goldilocks installs for you.

## Choose a table

List the registered choices and their supported elements, functional, accuracy,
and relativistic treatment with `goldilocks capabilities --json` (see
the `pseudopotential_tables` array), or filter it directly in Python:

```python
from goldilocks_core.capabilities import capabilities

for table in capabilities()["pseudopotential_tables"]:
    print(table["id"], table["functional"], table["accuracy"], table["relativistic"])
```

(Or `GET /capabilities` once `goldilocks serve http` is running, or the MCP
`capabilities` tool — all four return the same payload.)

The `pseudopotential_tables` array lists the registered tables. Each table's
`elements` field lists elements permitted by Core's selection policy, not just
those present in the upstream library. `goldilocks assets status` with
no argument only reports the `default` profile's single table; run
`goldilocks assets status all` to see every registered table's
install state.

Without an explicit source, Goldilocks chooses a compatible registered table,
preferring PseudoDojo unless the structure contains lanthanides or actinides. It
does not choose a different table merely because that table is installed. The
`default` asset profile includes the scalar-relativistic PBEsol efficiency
table, plus the default `qrf-kpoints`, `metallicity-cgcnn`,
`is-metal-classifier`, and `is-magnetic-classifier` models.

If no registered table satisfies the request, the `pseudo_table` record is
unavailable. Its reason lists every table with the requested functional and
accuracy, in table-ID order, with the constraints that rejected it. For
example, La2O3 under PBEsol with `spin_orbit_coupling=true` gives `no
pseudopotential table satisfies PBEsol efficiency full for La, O:
pseudodojo-pbesol-efficiency-fr: lanthanide and actinide elements require an
SSSP table; pseudodojo-pbesol-efficiency-sr: ...; sssp-pbesol-efficiency-sr:
relativistic treatment is scalar, requested full`. This tells a routing rule
apart from missing coverage.

To choose a table explicitly, pin `pseudo_table_id`: `--set
pseudo_table_id=<table-id>` on the CLI, `build_overrides({"pseudo_table_id":
"<table-id>"}, task=...)` in Python (see the [Python tutorial](tutorial.md)), or
`{"overrides": {"pseudo_table_id": "<table-id>"}}` over HTTP/MCP. The pinned
table's functional, accuracy tier, relativistic treatment, and element
coverage must still match the request. In particular:

- Only `efficiency`-tier tables can currently be selected, automatically or by
  pinning: the required accuracy tier is hardcoded to `efficiency` throughout
  selection today, with no override anywhere. Pinning a `precision` table
  (for example `pseudodojo-pbesol-precision-sr`) fails with `pseudopotential
  table '...' does not satisfy the request: accuracy is precision, requested
  efficiency; matching tables: ...`. `precision` tables are registered but not
  yet reachable, automatically or explicitly.
- Table suffixes `sr` and `fr` mean scalar relativistic and fully relativistic.
  Explicit spin-orbit coupling (SOC) needs fully relativistic files; the default
  profile contains only an `sr` table.
- Lanthanides and actinides must use SSSP under Goldilocks' selection policy,
  with coverage checked for the actual elements. PseudoDojo's lanthanide table
  freezes 4f electrons in the core assuming trivalent ions, which is not
  suitable for all oxidation states; its tables do not cover actinides. No
  registered SSSP table is fully relativistic, so automatic or explicit
  registered-table selection cannot supply SOC for these elements. Their runs
  carry the notice `magnetic.soc_unavailable`, with the selector's reason, in
  place of a suggestion to enable SOC (see
  [spin-orbit coupling](science.md#check-magnetism-and-spin-orbit-coupling)).
- SSSP 1.3.0 PBEsol tables reuse PBE input parameters and cutoffs and were not
  tested with the SSSP convergence protocol. Do not treat these as
  PBEsol-validated cutoffs.
- Some files in SSSP scalar-relativistic tables declare non-relativistic
  treatment. Goldilocks permits this exception for scalar requests and
  preserves the per-file treatment; no warning is currently emitted for it.

`spin_orbit_coupling` decides the relativistic treatment the table must have:
`full` when it is true, `scalar` otherwise (see
[relativistic modes](conventions.md#relativistic-modes)). With no pinned
table, enabling it makes automatic selection take the matching fully
relativistic table, with the same functional and accuracy: fcc Pb under
PBEsol goes from `pseudodojo-pbesol-efficiency-sr` to
`pseudodojo-pbesol-efficiency-fr`. This is the same in Python, on the CLI and
over HTTP/MCP; nothing besides `spin_orbit_coupling` needs to be set. Where no
registered table is fully relativistic for the structure's elements and
functional (every lanthanide and actinide, and LDA), the `pseudo_table` record
is unavailable. A pinned table is never changed: if its relativistic treatment
does not match, `pseudo_table` is unavailable, for example `relativistic
treatment is scalar, requested full; matching tables:
pseudodojo-pbesol-efficiency-fr`. Selecting an `fr` table does **not** enable
SOC; pinned without SOC, it is unavailable the same way.

In the Workbench, the table dropdown shows choices that support every element
in your structure at the selected functional; there is no accuracy or
relativistic-treatment filter or hint in the UI today (accuracy and
relativistic treatment appear only as descriptive text in each option's
label). Changing the functional clears any pinned table override. With no pin,
the dropdown shows the table automatic selection chose, so it follows the
`spin_orbit_coupling` switch.

The [scientific guide](science.md#check-pseudopotentials-and-cutoffs) explains
what to check before using selected cutoffs.

## Install and select it

The commands below assume Goldilocks is installed. Replace `structure.cif` with
your ordered structure file. This example installs the fully relativistic
PBEsol files and asks for an SOC recommendation, which selects them
automatically:

```bash
goldilocks assets install pseudodojo-pbesol-efficiency-fr
goldilocks explain structure.cif --set spin_orbit_coupling=true
```

Pinning the table with `--set pseudo_table_id=pseudodojo-pbesol-efficiency-fr`
is optional; it selects the same table.

Use the [asset commands](cli.md#install-and-check-assets) if a required model or
table is missing.

Check installation state and verify file integrity:

```bash
goldilocks assets status pseudodojo-pbesol-efficiency-fr
goldilocks assets verify pseudodojo-pbesol-efficiency-fr
```

Status is `installed`, `missing`, or `corrupt`. Repeat `assets install` to
repair a corrupt installation. Verification checks stored files, not scientific
accuracy.

### Read installed metadata in Python

For ordinary calculations, pin the table ID with `pseudo_table_id` (see
[Choose a table](#choose-a-table) above, and the
[Python tutorial](tutorial.md)). To inspect its installed metadata directly:

```python
from goldilocks_core.assets.store import AssetStore
from goldilocks_core.assets.pseudopotentials.importers import load_installed_table
from goldilocks_core.assets.pseudopotentials.registry import load_tables

table = load_tables()["pseudodojo-pbesol-efficiency-fr"]
installed = AssetStore().resolve_spec(table.asset)
metadata = load_installed_table(installed, table=table)
for pseudo in metadata:
    print(pseudo.element, pseudo.filename, pseudo.cutoffs)
```

PseudoDojo publishes only wavefunction cutoff hints (low, normal and high, in
Hartree). A managed PseudoDojo table converts them to Ry and keeps all three as
`cutoff_hints`; `cutoffs` holds the high hint as `ecutwfc_ry` and `None` as
`ecutrho_ry`, because PseudoDojo publishes no charge-density cutoff. SSSP tables
publish both cutoffs, so `cutoff_hints` is `None`. The `cutoffs` advisor is the
one place a charge-density cutoff is derived: for a table that publishes none it
writes the table's `charge_density_dual` (4 for every PseudoDojo table) times
the resolved `ecutwfc_ry`, a `--set ecutwfc_ry` value included, and the
`cutoffs` record says so with the info notice `cutoffs.ecutrho_derived_from_dual`.
Neither path optimizes cutoffs for your structure.

## Use your own UPF files

Not currently supported. There is no `--pseudo-root` flag, no custom-UPF-root
scanning, and no user-facing way to supply local UPF files, licence sidecars,
or scientific metadata for an arbitrary directory — `SystemOverrides` has no
`pseudo_root`/`pseudo_metadata` field, and the CLI, HTTP, and MCP surfaces only
accept a `pseudo_table_id` pinned to a *registered* table. The only way to
supply pseudopotentials today is automatic selection or `pseudo_table_id`,
described above.

(`parse_upf_metadata` in
`goldilocks_core.assets.pseudopotentials.upf` still exists, but it is an
internal UPF-header parser used by the asset-install pipeline, not a
public entry point for bringing your own files.)

## Find stored assets

The default store is `$XDG_DATA_HOME/goldilocks/assets`, or
`~/.local/share/goldilocks/assets` when `XDG_DATA_HOME` is unset.
`GOLDILOCKS_ASSET_ROOT` overrides it. Table installations live at:

```text
<asset-store>/pseudopotentials/<table-id>/<version>/
```

Treat managed files as read-only; use `assets install`, `status`, and `verify`.

Published records never contain this path. The `pseudopotentials` record of
`explain`, `run` and `goldilocks.json` names each UPF by `table_id`
(`pseudopotentials/<table-id>`), `asset_path` (its path inside the table's
installation, such as `pseudos/Si.upf`), `filename` (its copy under `pseudo/`
in a bundle) and `content_sha256`/`content_size_bytes`, which equal that
copy's entry in the manifest's `files`. Two machines with the same tables
installed publish the same records.

## Licences and citations

UPFs retain their upstream licences; the Goldilocks BSD licence does not apply
to them. UPFs are downloaded separately, not bundled in the package.

- [PseudoDojo](https://www.pseudo-dojo.org/): registered tables use CC BY 4.0,
  as the project states in its
  [README](https://github.com/abinit/pseudo_dojo/blob/404896295771/README.md#license).
  Cite van Setten et al., _Computer Physics Communications_ 226, 39–54 (2018).
  The archives download from an unmodified copy on PSDI
  ([record 8gc82-qm928](https://data-collections.psdi.ac.uk/records/8gc82-qm928)),
  since www.pseudo-dojo.org has been unreachable for days at a time.
- [SSSP 1.3.0](https://archive.materialscloud.org/records/rcyfm-68h65): cite
  Prandini et al., _npj Computational Materials_ 4, 72 (2018), and the data
  record. The record's CC BY 4.0 licence does not replace the individual UPF
  licences. Read its mixed-family
  [`LICENSE.txt`](https://archive.materialscloud.org/records/rcyfm-68h65/files/LICENSE.txt?download=1)
  before redistribution.

Installations store licence material in `LICENSE.txt`: the CC BY 4.0 notice for
PseudoDojo, or the upstream mixed-family licence file for SSSP, which gives
each family's licence and references (GBRV under GPL-3.0, for example, and
Topsakal & Wentzcovitch 2014 for the rare-earth PAWs). Every bundle that
ships UPFs (CLI `run --out`, HTTP `/run` archives, Workbench downloads) also
ships that file byte for byte as `licences/<table-id>.txt`, listed in
`goldilocks.json`'s `files` with role `licence` and named in `CITATIONS.md`.
