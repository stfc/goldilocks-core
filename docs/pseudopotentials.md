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

The table must match the calculation functional, accuracy mode, and relativistic
mode.

- Use an `efficiency` table for normal calculations.
- Use a `precision` table when accuracy is more important than cost.
- Use an `sr` table for a calculation without SOC.
- Use an `fr` table for a calculation with SOC.
- Use an SSSP table for lanthanides or actinides.

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

Install the table:

```bash
uv run goldilocks assets install pseudodojo-pbesol-efficiency-fr
```

Load that table in Python and enable SOC:

```python
from goldilocks_core import CalculationHints, CoreService, PresetRequest
from goldilocks_core.pseudo.pp_registry import load_installed_pseudo_metadata

metadata = load_installed_pseudo_metadata("pseudodojo-pbesol-efficiency-fr")
request = PresetRequest(
    structure="structure.cif",
    hints=CalculationHints(spin_orbit_coupling=True),
    pseudo_metadata=metadata,
)

with CoreService() as core:
    result = core.generate(request, output_dir="run")
```

The default profile contains only an `sr` table. It cannot supply the fully
relativistic UPFs that an SOC calculation needs.

### SSSP tables

SSSP tables cover the lanthanides and actinides. Selection uses SSSP for these
elements when the request contains SSSP metadata.

- `sssp-pbesol-efficiency-sr`
- `sssp-pbesol-precision-sr`
- `sssp-pbe-efficiency-sr`
- `sssp-pbe-precision-sr`

Install the SSSP table that matches the functional and accuracy mode. Then pass
it to `PresetRequest` with `load_installed_pseudo_metadata()`, as in the SOC
example above.

The default profile does not include an SSSP table.

The registry also contains `pseudodojo-pbe-lanthanides-sr`. Goldilocks does not
select this table automatically. It assumes trivalent f-in-core ions and is not
suitable for all lanthanides.

The CLI uses the installed default table unless you give it `--pseudo-root`.
Installing a different table does not change that default. Use
`load_installed_pseudo_metadata(TABLE_ID)` in Python to select a different
installed table.

## Check an installed table

Show its state:

```bash
uv run goldilocks assets status pseudodojo-pbesol-efficiency-fr
```

Check every installed file:

```bash
uv run goldilocks assets verify pseudodojo-pbesol-efficiency-fr
```

The state is `installed`, `missing`, or `corrupt`. Run `assets install` again to
repair a corrupt table.

## Use your own UPF files

Use `--pseudo-root` to read a directory that you manage:

```bash
uv run goldilocks generate structure.cif --pseudo-root pseudos --k-grid 4 4 4 --out run
```

Goldilocks reads `.upf` and `.UPF` files below the directory. It does not copy or
change them. The UPF data or nearby JSON metadata must provide enough
information to select one file and two positive cutoffs for each element.

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
