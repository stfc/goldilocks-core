# Pseudopotential tables

Goldilocks installs complete pseudopotential tables as external runtime assets.
The Python package contains table declarations, checksums, scientific metadata,
and provider-specific import code; it does not contain UPF files.

## Installed default

The `default` runtime profile currently pins
`pseudodojo-pbesol-efficiency-sr@0.4`. Install and verify it with the model
assets:

```bash
goldilocks assets install default
goldilocks assets verify default
```

Install or inspect one declared table by its registry id:

```bash
goldilocks assets install pseudodojo-pbe-efficiency-sr
goldilocks assets status pseudodojo-pbe-efficiency-sr
goldilocks assets verify pseudodojo-pbe-efficiency-sr
```

Without `--pseudo-root`, CLI and server requests resolve the installed default
table. They do not fetch it during ordinary execution. `--fetch-missing` is the
explicit CLI opt-in to install the complete default profile before a run.

`--pseudo-root PATH` bypasses the installed default and loads a user-managed UPF
directory recursively. Goldilocks does not copy that directory into the asset
store or change its files.

## Asset store layout

The store root is resolved in this order:

1. an explicit root passed to `AssetStore`;
2. `GOLDILOCKS_ASSET_ROOT`;
3. `$XDG_DATA_HOME/goldilocks/assets`;
4. `~/.local/share/goldilocks/assets` when `XDG_DATA_HOME` is unset.

Each immutable version is published beneath:

```text
<root>/<asset-id>/<version>/
├── manifest.json
├── pseudo-table.json          # pseudopotential tables
└── pseudos/
    └── *.upf
```

Model assets use the same `<asset-id>/<version>` seam and keep their declared
model filenames beside `manifest.json`. `<root>/.locks/` contains per-version
installation locks. Downloads and provider archives exist only in a temporary
staging directory under the store root and are removed after installation.
Failed preparation is not published.

`manifest.json` inventories every installed file with its size and SHA-256
digest. `pseudo-table.json` carries the table identity, provider, functional,
accuracy, relativistic treatment, licence, citation, element coverage, selected
cutoffs, and UPF paths. `assets verify` rejects missing, changed, or extra files.
A later `assets install` repairs a corrupt version from its pinned sources.

Treat an installed asset directory as read-only. To relocate a deployment, set
`GOLDILOCKS_ASSET_ROOT` before installation. A shared read-only store is valid
for execution after one writer has completed installation.

## Acquisition and normalization

Table definitions live in `goldilocks_core/pseudo/registry.toml`. Each entry
pins its provider table, version, source URLs, source sizes and SHA-256 digests,
functional, relativistic treatment, accuracy family, element coverage, licence,
and citation.

Installation verifies the source files before provider-specific normalization:

- PseudoDojo: verifies the UPF and report archives, checks each UPF against its
  report digest, converts cutoff hints from Hartree to Rydberg, and emits the
  normalized manifest.
- SSSP: verifies the table archive and JSON sidecar, checks every UPF against
  the sidecar digest, retains the published wavefunction and charge-density
  cutoffs, and emits the same normalized manifest.

Source archives are not retained. Selection consumes only the verified installed
manifest, so provider directory names and archive layouts do not leak into the
runtime interface.

## Selection constraints

Automatic selection matches the requested functional, accuracy mode, and
relativistic treatment. Generation requires one matching UPF and finite positive
`ecutwfc` and `ecutrho` values for every element.

The PseudoDojo 3+ lanthanide table is declared for explicit installation but is
not selected automatically: it assumes trivalent f-in-core ions, is PBE-only,
and is unsuitable for elements whose usual valence differs. The registry notes
other incomplete or provider-specific coverage constraints. Read the selected
record warnings before treating a generated input as production-ready.

## Licensing and citation

Goldilocks downloads upstream pseudopotentials on the operator's explicit
request. The UPF files are not part of the Goldilocks wheel or source archive,
and the Goldilocks BSD licence does not replace their upstream terms.

- PseudoDojo table declarations record CC BY 4.0 and the citation: van Setten
  et al., *Computer Physics Communications* 226, 39–54 (2018).
- SSSP 1.3.0 is a mixed collection. The Materials Cloud record is CC BY 4.0,
  while individual pseudopotential families include GPL-2.0-or-later, GPL-3.0,
  CC BY 3.0, CC BY 4.0, and CC BY-SA 4.0 terms. Consult the record's
  [`LICENSE.txt`](https://archive.materialscloud.org/records/rcyfm-68h65/files/LICENSE.txt?download=1)
  before redistribution.

The installed `pseudo-table.json` preserves the table-level licence and citation;
SSSP's `source_pseudopotential` field identifies the upstream family for each
element. Cite the table and the underlying pseudopotential family as required by
the upstream publication and licence. Do not assume that installing a table
grants permission to redistribute it as one uniformly licensed bundle.

Upstream sources:

- [PseudoDojo](https://www.pseudo-dojo.org/)
- [SSSP 1.3.0 Materials Cloud record](https://archive.materialscloud.org/records/rcyfm-68h65)
