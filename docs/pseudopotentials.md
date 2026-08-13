# Pseudopotential tables

Goldilocks can download and install complete pseudopotential tables. It does not
put UPF files in the Python package.

## Start here

Install the default runtime profile once:

```bash
goldilocks assets install default
```

Check the installed files:

```bash
goldilocks assets verify default
```

The default profile contains two model assets and this pseudopotential table:

```text
pseudodojo-pbesol-efficiency-sr@0.4
```

A normal calculation does not use the network. If an asset is missing, the
command stops and tells you what to install. The `--fetch-missing` option gives
one command permission to install the full default profile.

You can also install one table:

```bash
goldilocks assets install pseudodojo-pbe-efficiency-sr
```

## Where the files go

Goldilocks selects the asset store root in this order:

1. The root that code passes to `AssetStore`.
2. `GOLDILOCKS_ASSET_ROOT`.
3. `$XDG_DATA_HOME/goldilocks/assets`.
4. `~/.local/share/goldilocks/assets` if `XDG_DATA_HOME` is not set.

A normal Linux installation therefore uses:

```text
~/.local/share/goldilocks/assets
```

Each asset has its own version directory:

```text
<asset-store>/<asset-id>/<version>/
```

For example:

```text
~/.local/share/goldilocks/assets/pseudodojo-pbesol-efficiency-sr/0.4/
```

A pseudopotential table contains:

```text
manifest.json
pseudo-table.json
pseudos/*.upf
```

`manifest.json` contains the size and SHA-256 digest of each installed file.
`pseudo-table.json` contains the table identity, functional, accuracy,
relativistic treatment, licence, citation, cutoffs, and UPF paths.

Goldilocks uses a temporary directory during installation. It removes downloaded
archives after installation. It publishes the final directory only after all
checks pass.

Treat installed asset directories as read-only. You can put the store in a
shared location with `GOLDILOCKS_ASSET_ROOT`. Calculations can use a shared
read-only store after one process installs the assets.

## Check and repair the store

Show the state of the default profile:

```bash
goldilocks assets status default
```

The state is `installed`, `missing`, or `corrupt`.

Check every installed file:

```bash
goldilocks assets verify default
```

Run `assets install` again to repair a corrupt asset. Goldilocks downloads the
pinned source again. It replaces the corrupt version only after all checks pass.

## Use your own UPF directory

Use `--pseudo-root` to use a directory that you manage:

```bash
goldilocks generate structure.cif --pseudo-root pseudos --k-grid 4 4 4 --out run
```

Goldilocks reads `.upf` and `.UPF` files below that directory. It does not copy
or change them. This option bypasses the installed default table.

## How table installation works

Table definitions are in `goldilocks_core/pseudo/registry.toml`. Each definition
contains source URLs, sizes, SHA-256 digests, scientific properties, element
coverage, a licence, and a citation.

Goldilocks checks downloaded source files before it extracts them. It then
converts PseudoDojo and SSSP data to the same installed format.

For PseudoDojo, Goldilocks checks each UPF against its report. It also converts
cutoff values from Hartree to Rydberg.

For SSSP, Goldilocks checks each UPF against the SSSP JSON data. It keeps the
published wavefunction and charge-density cutoffs.

Selection reads only the installed `pseudo-table.json` file. It does not depend
on a provider's archive layout.

## Selection limits

Automatic selection matches the requested functional, accuracy mode, and
relativistic treatment. Input generation needs one UPF and two positive cutoffs
for each element.

The PseudoDojo 3+ lanthanide table is available for manual installation.
Automatic selection does not use it because it assumes trivalent f-in-core ions
and is PBE-only. Read selection warnings before you use an input for production
work.

## Licences and citations

Pseudopotential files keep their upstream licences. The Goldilocks BSD licence
does not apply to those files. Goldilocks does not include them in its wheel or
source archive.

PseudoDojo table definitions record CC BY 4.0. Cite van Setten et al.,
*Computer Physics Communications* 226, 39–54 (2018).

SSSP 1.3.0 contains files from different pseudopotential families. The Materials
Cloud record is CC BY 4.0. Individual files can use GPL-2.0-or-later, GPL-3.0,
CC BY 3.0, CC BY 4.0, or CC BY-SA 4.0. Read the SSSP
[`LICENSE.txt`](https://archive.materialscloud.org/records/rcyfm-68h65/files/LICENSE.txt?download=1)
before you redistribute an SSSP table.

The installed `pseudo-table.json` keeps the table licence and citation. For
SSSP, each element also keeps its source pseudopotential family. Cite the table
and the source family when their terms require it.

Upstream sources:

- [PseudoDojo](https://www.pseudo-dojo.org/)
- [SSSP 1.3.0](https://archive.materialscloud.org/records/rcyfm-68h65)
