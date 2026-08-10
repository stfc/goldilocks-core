# Pseudopotentials

goldilocks-core selects a pseudopotential for every element in a structure and
reads its recommended cutoffs from it. This page covers where the
pseudopotentials come from, how they are laid out on disk, how selection
reads that layout, how to add a new table to the registry, and how to add an
entirely new provider.

## Two ways to get pseudopotentials onto disk

**`gl pp install`** fetches a table from a small built-in registry
(`pseudo_registry.toml`) directly from its publisher -- PseudoDojo or the
Materials Cloud Archive -- verifying every file against a digest the
publisher itself provides. Nothing is bundled with the package and nothing is
installed unless you run the command: `gl generate`/`gl bundle` refuse to run
with a clear error naming the command, the size, the licence, and the
citation, rather than downloading anything on your behalf.

**`--pseudo-root PATH`** points at pseudopotentials you already have --
hand-downloaded, generated yourself, or installed by some other tool. Any
library works, not just the ones Core knows how to install.

Both routes converge on the same directory contract below, and both are read
by the same parser (`goldilocks_core.pseudo.pp_registry.load_pseudo_metadata`).
Once files are on disk, Core cannot tell -- and does not need to tell --
which route put them there.

```bash
gl pp install                              # the default table
gl generate structure.cif                  # uses whatever gl pp installed
gl generate structure.cif --pseudo-root /path/to/your/pseudopotentials
```

## The on-disk contract

Every table, installed or hand-placed, must follow:

```
<root>/<library>/<source_set>/*.upf
<root>/<library>/<source_set>.json      # optional: cutoffs and relativistic mode
```

`library` and `source_set` are read from the **path**, not the UPF header:
`_extract_library()` takes the path segment that follows a directory
literally named `pseudopotentials`, and `source_set` is simply that file's
parent directory name (`parse_upf.py`). This is why `gl pp install` always
works: the managed cache root is
`~/.local/share/goldilocks-core/pseudopotentials/<library>/<source_set>/`
(overridable with `GOLDILOCKS_CACHE`, see below), which contains that literal
segment by construction.

> **A `--pseudo-root` whose path never contains a directory named
> `pseudopotentials` gets `library=None` for every file.** Selection still
> runs, but anything that filters by library (`PseudoPolicy.allowed_sources`,
> in `pp_policy.py`) silently matches nothing instead of erroring. This is a
> known, unfixed gap -- see [Known gaps](#known-gaps) -- and the workaround
> today is to make sure a `pseudopotentials` directory sits somewhere above
> your tables, e.g. `--pseudo-root /anywhere/pseudopotentials/mine`.

The optional sidecar JSON is a flat map read by `parse_upf.py`'s
`_load_sssp_json()` (a misleading name: it is not SSSP-specific, just
SSSP-shaped, and every registered table now writes one):

```json
{
  "_relativistic": "scalar",
  "Si": {"cutoff_wfc": 48.0, "cutoff_rho": 192.0}
}
```

`gl pp install` always writes this file. If you hand-place pseudopotentials
with no sidecar, selection still works -- cutoffs simply come back
unrecommended (`sssp_recommended_cutoff: null`) and relativistic mode falls
back to whatever the individual UPF header claims.

### Where installed tables actually live

`goldilocks_core.artifacts.cache.cache_root()` resolves, in order:

1. `GOLDILOCKS_CACHE` environment variable
2. `XDG_DATA_HOME`
3. `~/.local/share`

then appends `goldilocks-core/`. This is deliberately **outside** the
installed Python package: `pip install --upgrade` replaces the package
directory, and on shared installs that directory is often read-only anyway.
Downloads are written atomically -- streamed to a `.part` file, digest
verified, then renamed onto the final path -- so an interrupted transfer
never leaves a truncated pseudopotential that later fails to load or, worse,
loads with silently wrong data (`artifacts/cache.py::store_verified`).

## The registry: what Core knows how to install

`src/goldilocks_core/pseudo_registry.toml` is a catalogue, not a store -- it
holds no pseudopotentials, only what each table costs, covers, and is
licensed under, so Core can answer "what would resolve this gap" before
touching the network. `pseudo/table_registry.py` is the code that turns that
TOML into `PseudoTable` objects your code can actually query
(`table.covers("Si")`, `default_table()`, `tables_covering(element)`).

This is a different thing from `pseudo/pp_registry.py`, despite the similar
name: `table_registry.py` is the download catalogue (works with nothing
installed); `pp_registry.py` reads UPF files already on disk (works with
nothing registered). The only thing connecting them is the directory
convention above.

### Naming convention

Every registry key ends in `-sr`, `-fr`, or `-nr`, matching that table's
`relativistic` field, and contains its functional:

```
pseudodojo-pbesol-efficiency-sr
pseudodojo-pbesol-efficiency-fr
sssp-pbesol-efficiency-sr
```

so `gl pp available` tells you SR from FR by reading the name, without
opening the TOML.

### Current catalogue (12 tables)

```
$ gl pp available
NAME                            XC      REL  ACCURACY     ELEMENTS  Ln  An     SIZE
pseudodojo-pbesol-efficiency-sr *PBEsol  SR   efficiency         72   2   0   5.2 MB
pseudodojo-pbesol-precision-sr  PBEsol  SR   precision          72   2   0   5.4 MB
pseudodojo-pbe-efficiency-sr    PBE     SR   efficiency         72   2   0   5.2 MB
pseudodojo-pbe-precision-sr     PBE     SR   precision          72   2   0   5.4 MB
pseudodojo-lda-efficiency-sr    LDA     SR   efficiency         70   0   0   4.9 MB
pseudodojo-lda-precision-sr     LDA     SR   precision          70   0   0   5.2 MB
pseudodojo-pbe-lanthanides-sr   PBE     SR   efficiency         14  14   0   1.4 MB
pseudodojo-pbesol-efficiency-fr PBEsol  FR   efficiency         71   1   0   6.7 MB
pseudodojo-pbesol-precision-fr  PBEsol  FR   precision          71   1   0   7.1 MB
pseudodojo-pbe-efficiency-fr    PBE     FR   efficiency         70   0   0   6.6 MB
pseudodojo-pbe-precision-fr     PBE     FR   precision          72   2   0   7.3 MB
sssp-pbesol-efficiency-sr       PBEsol  SR   efficiency        103  15  15  60.5 MB
```

`*` marks the default (`pseudodojo-pbesol-efficiency-sr`): cheapest, cleanest
licence (CC-BY-4.0, PseudoDojo redistributes nothing GPL), PBEsol.

**Why 12, not aiida-pseudo's 13.** aiida-pseudo's PseudoDojo family offers 13
configurations; SSSP is a separate, uncounted 13th-and-beyond family entirely.
Of PseudoDojo's 13, Core registers 11 and excludes
`nc-sr-05_pbe_{standard,stringent}`: both ship 72 pseudopotentials but publish
`.djrepo` cutoff hints for only 61 of them. Fetching both archives directly
shows the 11 missing elements are exactly Ba, Bi, I, Pb, Po, Rb, Rn, S, Te,
Tl, Xe -- the set PseudoDojo's own v0.5 site flags as updated for PBE only
("use 0.4.1 for LDA or PBEsol xc"), consistent with those hints simply not
existing yet rather than an arbitrary gap. Registering the table would let a
user download it cleanly and then hit a cutoff-less failure at generation
time for 11 specific elements; Core would rather not offer it at all.

## Installing: `gl pp`

```
gl pp available            # every table Core can install, and its terms
gl pp list                 # what is actually on disk, and where
gl pp install [NAME ...]   # install the default, or named tables
```

`gl pp install` always prints the licence, upstream URL, citation, and any
table-specific note *before* transferring a byte -- a user who just installed
Core has no other way to learn any of that. Installing an already-installed
table is a no-op that says so; it does not re-verify or re-fetch.

Under the hood (`pseudo/install.py::install()`):

1. Dispatch on `table.provider` to `artifacts/pseudodojo.py` or
   `artifacts/sssp.py`.
2. **PseudoDojo**: fetch the `.djrepo` report archive first (three orders of
   magnitude smaller than the pseudopotentials, and it publishes the expected
   digest of every UPF file), then fetch and verify each pseudopotential
   individually against it. A corrupt member is caught by name, not just as a
   corrupt download.
3. **SSSP** (via Materials Cloud Archive, an InvenioRDM instance -- same API
   shape as PSDI Data Collections, so `artifacts/sssp.py` reuses
   `artifacts/psdi.py`'s record-resolution code): fetch the table's small JSON
   sidecar first, then the `.tar.gz`, verifying each extracted file against
   the sidecar's published MD5.
4. Write the cutoff sidecar (see below), then stamp the table's registered
   relativistic classification into that same sidecar (`_stamp_relativistic`).

Nothing here is ever redistributed by Core -- bytes travel from the publisher
to your machine directly, every time. This is what makes an SSSP table
installable at all despite carrying GPL-licensed components: Core is never
the one distributing them.

## Cutoffs: where the numbers come from

**SSSP** publishes `cutoff_wfc`/`cutoff_rho` directly in its sidecar JSON, in
Ry already. Copied through unchanged.

**PseudoDojo publishes no cutoff in the UPF file at all.** The UPF header's
own `rho_cutoff` field looks like a candidate but is not one -- it is a
pseudopotential-*generation* parameter recorded next to `mesh_size` and
`l_max`, not a converged-basis recommendation, and measured against
PseudoDojo's own PBEsol standard table it moves in the wrong direction: Si is
15.1, O is 9.3, yet Si converges at half the plane-wave cutoff O needs (48 Ry
vs 96 Ry). The real numbers live in the `.djrepo` report published beside
each table:

1. **Which hint.** A `.djrepo` publishes three -- `low`, `normal`, `high` --
   for the *same* pseudopotential. This is not the `efficiency`/`precision`
   axis (that is two different pseudopotentials). Core always takes `high`,
   so a recommended cutoff is the converged one, not the cheapest that might
   do (`high` runs ~1.16x `normal` in `ecutwfc`, ~1.25x in plane-wave count).
2. **Units.** `.djrepo` hints are in Hartree (ABINIT's convention); Core's
   cutoffs are in Rydberg. Factor of 2
   (`goldilocks_core.artifacts.pseudodojo.HARTREE_TO_RYDBERG`).
3. **Charge-density cutoff is not published at all.** `ecutrho = dual *
   ecutwfc`, with `dual = 4`
   (`goldilocks_core.artifacts.pseudodojo.DEFAULT_DUAL`) -- the usual quoted
   value for norm-conserving pseudopotentials and QE's own default, but
   provisional: `aiida-pseudo` uses 8 for the same tables, and SSSP's own
   published dual (a different, ultrasoft formalism, not a like-for-like
   check) is 240/30 = 8. Tracked in
   [#149](https://github.com/stfc/goldilocks-core/issues/149).

An element whose report carries no `high` hint is **omitted from the
sidecar, not given a fabricated cutoff** -- selection then reports it as
uncovered instead of silently under-converged.

## Relativistic mode: SR / FR / NR

A calculation selects **one pseudopotential table**, not a relativistic
treatment per element -- the registry already classifies each table `SR`,
`FR`, or `NR` as a whole (no `NR` table is registered today). `gl pp install`
converts that classification to the UPF vocabulary (`SR`->`scalar`,
`FR`->`full`, `NR`->`non-relativistic`) and stamps it into the table's sidecar
as `_relativistic`; `parse_upf.py` prefers that stamp over what an individual
file's own header claims, falling back to the header only when a table (e.g.
hand-installed) carries no sidecar at all.

This matters concretely: SSSP marks its lightest elements (B, Be, Li)
`non-relativistic` in their own UPF headers even though the table as a whole
is scalar-relativistic. Before this stamp existed, a search for `scalar`
pseudopotentials silently dropped those three elements from an otherwise
fully-installed, fully-covering table. See
[#150](https://github.com/stfc/goldilocks-core/issues/150).

**Tables installed before this stamp existed keep their old sidecar until
reinstalled** -- `gl pp install` treats an already-populated directory as
done and will not rewrite it. There is currently no `--force` reinstall
flag; delete the table's directory under the cache root and reinstall it.

## Scientific caveats you should know before picking a table

**SSSP cannot do spin-orbit coupling.** SSSP is scalar-relativistic only --
no fully-relativistic SSSP set exists, and none is planned (see the `note` on
`sssp-pbesol-efficiency-sr` in the registry). Core advises considering SOC for
heavy elements regardless of which library is installed; if you follow that
advice with only SSSP on disk, no candidate can satisfy it, and the shortage
is not that you picked the wrong SSSP table -- SSSP has no such table at all.
Use a PseudoDojo **NC-FR** table (`*-fr`) for spin-orbit calculations.

**`pseudodojo-pbe-lanthanides-sr` freezes the 4f shell (f-in-core), assuming
a trivalent lanthanide.** It is the only registered table covering most
lanthanides (the default table covers only La and Lu), so selection will
reach for it without comment whenever a structure needs one. That assumption
is wrong for Eu²⁺/Yb²⁺ (e.g. EuO, YbAl₂), cannot represent Ce's valence, and
drops 4f magnetism entirely -- yet the calculation still runs and converges
to reasonable-looking numbers, so nothing about the output signals the
problem. There is no runtime warning for this yet; it is tracked in
[#126](https://github.com/stfc/goldilocks-core/issues/126) (P2), which
explicitly wants the wording reviewed by a domain expert before it ships.
Until then: **check by hand whether a lanthanide in your structure needs
open-4f treatment before trusting this table's result.**

## Selection: how a candidate is actually chosen

At generation time (`selection.py::select_pseudopotential`), for each
element:

1. **Hard filters** (`pp_selector.select_pseudos`): `functional`,
   `pseudo_type`, and `relativistic` must match exactly. No candidates
   surviving this is reported as "no pseudopotential metadata matched
   `{element} / {functional} / {relativistic_mode}`", not a silent gap.
2. **Ranking** among the survivors (`_rank_pseudo_candidate`), in order:
   `pseudo_mode` (efficiency/precision) match, then complete cutoffs, then
   SSSP preferred, then a deterministic tie-break by source and filename.
3. `library`/`source_set` of the winner are recorded in the result's
   provenance.

`--pseudo-root`, `--pseudo-mode`, `--pseudo-type`, `--relativistic-mode` on
the CLI map onto this directly; see `docs/cli.md`.

`PseudoPolicy`/`apply_pseudo_policy` (`pp_policy.py`) is a second, more
general filtering layer -- functional, source library, pseudo type,
relativistic mode, all as hard filters -- but nothing in the CLI or the
staged pipeline constructs one today; it is exercised only by its own unit
tests. Treat it as available for direct/programmatic use, not as something
`gl generate` currently goes through.

## Licences and attribution

Nothing is ever redistributed by Core -- every byte comes from the publisher
to you directly, at install time, every time.

| Library | Licence | Notes |
| --- | --- | --- |
| PseudoDojo | CC-BY-4.0 | The GPL-2.0 on the `PseudoDojo/pseudodojo` GitHub repo covers the *generator code*, not the published tables. |
| SSSP | Mixed | The Materials Cloud record itself is CC-BY-4.0, but individual files carry the licence of the project they came from: GBRV (GPL v3), rare-earths/Wentzcovitch (GPL v3), PSlibrary (GPL v2+), SG15 (CC BY-SA 4.0), PseudoDojo (CC BY 4.0), Goedecker (CC BY 3.0). |
| `--pseudo-root` (bring your own) | Whatever you downloaded | Your responsibility; Core has no way to know. |

`gl pp install` prints licence and citation before transferring anything,
and the registry (`table.citation`) records what to put in a methods section.

## Adding a new table to an existing provider

To register another PseudoDojo or SSSP/Materials Cloud table:

1. **Measure it, don't guess it.** Coverage differs between tables the
   naming suggests are siblings, and (as above) one table can publish cutoffs
   for fewer elements than it ships pseudopotentials for. Run
   `scripts/survey_pseudo_tables.py` against the candidate, or fetch its
   report archive by hand the way this doc's "Current catalogue" section did.
2. **Add a `[tables."..."]` entry** to `pseudo_registry.toml` with every
   field `PseudoTable` requires: `provider`, `upstream_table` (what the
   *provider* calls it -- the download URL is built from this, never from
   your key), `version`, `functional`, `relativistic` (`SR`/`FR`/`NR`),
   `accuracy` (`efficiency`/`precision`), `licence`, `upstream_url`,
   `citation`, `elements`, and measured `transfer_bytes`. Materials Cloud
   entries also need `record` (the Archive record ID).
3. **Name it `<ours>-<functional>-<accuracy>-{sr,fr,nr}`**, matching the
   convention above.
4. **Write the `note` field** for anything a user must know before choosing
   it -- a functional mismatch, a coverage gap, an encumbered licence. The
   existing entries are the style guide.
5. Run the test suite: `test_table_registry.py` enforces the naming
   convention and that every entry declares terms (licence, citation, URL);
   `test_pseudo_install.py` covers layout and installability.

No code change is needed for a new table under an existing provider --
`install.py` dispatches on `table.provider`, not on the table name.

## Adding an entirely new provider

A provider is a module under `artifacts/` exposing:

```python
def install(*args, root: Path, http: HttpClient | None = None) -> Path:
    """Fetch, verify, and unpack a table; return the directory of *.upf files."""
```

The contract it has to uphold, matching `pseudodojo.py` and `sssp.py`:

- **Verify before writing.** Use `artifacts/cache.py::store_verified()` for
  a per-file digest check, streamed to a `.part` file and renamed only once
  it matches -- never leave a partial or unverified pseudopotential where
  selection could find it.
- **Fetch small-before-large.** Get whatever publishes the expected digests
  (a report archive, a sidecar JSON) before the pseudopotentials themselves,
  so integrity is known in advance rather than checked after the fact.
- **Reuse `artifacts/remote.py`** for the actual HTTP transport
  (`stream()`, `download()`, `transferred_size()`) rather than reimplementing
  chunked download and `HEAD`-based size reporting.
- **Write the cutoff sidecar**, `<destination.parent>/<destination.name>.json`,
  in the shared schema (`{"element": {"cutoff_wfc": ..., "cutoff_rho": ...}}`)
  so `parse_upf.py` needs no provider-specific code to find cutoffs. Omit
  elements with no real cutoff rather than fabricating one.
- **Follow the layout convention**: land pseudopotentials at
  `<root>/<library>/<source_set>/*.upf` where `library` is a name unique to
  the provider (a module-level `LIBRARY` constant, as `pseudodojo.py` and
  `sssp.py` both define).

Then wire it into `pseudo/install.py`:

- add an `elif table.provider == "your-provider":` branch in `install()`
  calling your module's `install()`;
- add the matching branch in `_layout()` returning `(library, source_set)`
  for a table of that provider, *without downloading anything* -- this has to
  work for tables that are not installed yet, since `is_installed()` and
  `install_path()` depend on it.

You do not need to touch `_stamp_relativistic()`: it runs centrally on
whatever `install()` returns, regardless of provider.

## Known gaps

- **`_extract_library()` requires the literal path segment
  `pseudopotentials`.** A `--pseudo-root` whose path does not contain a
  directory with exactly that name gets `library=None` for every file,
  which silently empties `PseudoPolicy.allowed_sources`-based filtering
  (see [The on-disk contract](#the-on-disk-contract)). Previously raised as
  [#90](https://github.com/stfc/goldilocks-core/issues/90), closed by being
  folded into #95 without the fix landing; confirmed still present. Currently
  low-impact only because nothing in the CLI constructs an `allowed_sources`
  policy yet -- it bites direct `apply_pseudo_policy()` callers today.
- **`pseudo_mode` (efficiency/precision) ranking is a no-op for PseudoDojo
  tables.** `selection.py::_metadata_matches_mode()` looks for the literal
  words `efficiency`/`precision` in a candidate's library, source set,
  source pseudopotential, or filename. SSSP's on-disk directory names contain
  those words (`SSSP_1.3.0_PBEsol_efficiency`); PseudoDojo's do not -- its
  upstream tables are named `standard`/`stringent`, which Core's registry
  maps onto `efficiency`/`precision` only in `pseudo_registry.toml`, not on
  disk. Verified live: for a PseudoDojo `-efficiency-sr` and `-precision-sr`
  pair installed side by side, `_metadata_matches_mode()` returns `False` for
  both regardless of the requested `--pseudo-mode`, so the two rank
  identically and the accuracy preference has no effect once you are choosing
  between two PseudoDojo tables (or between PseudoDojo and SSSP, where SSSP
  always wins the tie-break). Not yet filed as an issue.
- **`gl pp install` cannot force a reinstall.** A table installed before a
  sidecar-schema change (like the `_relativistic` stamp above) keeps its old
  sidecar until its directory is deleted and reinstalled by hand.
- **Only two providers are wired up**: PseudoDojo and Materials Cloud/SSSP.
  Anything else (GBRV, PSlibrary, SG15 fetched standalone, ...) has to be
  supplied via `--pseudo-root`.

## Tests

- `test_artifacts_cache.py` -- the atomic-write primitive (`store_verified`).
  `remote.py`'s HTTP transport has no dedicated test file; it is exercised
  indirectly through the fake-HTTP-client fixtures in the two tests below.
- `test_artifacts_psdi.py`, `test_artifacts_pseudodojo.py` -- provider
  download/verify logic (SSSP's own `install()`/`_unpack_verified()` has no
  dedicated unit test yet; it is only exercised indirectly through
  `test_pseudo_install.py`'s layout checks).
- `test_table_registry.py` -- the registry: naming convention, exactly one
  default, every entry declares terms, coverage lookups.
- `test_pseudo_install.py` -- the installer: layout, `require_installed()`'s
  message, the relativistic stamp, `resolve_pseudos()`.
- `test_parse_upf.py` -- UPF parsing, including the sidecar override.
- `test_pp_registry.py`, `test_pp_policy.py`, `test_pp_selector.py`,
  `test_selection.py` -- filtering and ranking.

## Related work

- [#126](https://github.com/stfc/goldilocks-core/issues/126) -- this page's
  tracking issue. Its P1 (root layout, licences, the f-in-core caveat) is what
  this rewrite covers; its P2 (a runtime f-in-core warning at selection,
  worded by a domain expert) is still open.
- [#149](https://github.com/stfc/goldilocks-core/issues/149) -- validate the
  PseudoDojo `dual=4` assumption with real convergence tests.
- [#150](https://github.com/stfc/goldilocks-core/issues/150) -- the
  relativistic-classification fix described above.
- [#90](https://github.com/stfc/goldilocks-core/issues/90) -- the
  `_extract_library` literal-path-segment gap, still open.
