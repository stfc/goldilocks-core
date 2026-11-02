# Scientific conventions

Use this reference for units, defaults, and override rules. For what to check
before trusting a recommendation, see [Check your recommendations](science.md).

## Units

| Quantity                  | Unit          | Field                                              |
| ------------------------- | ------------- | --------------------------------------------------- |
| k-point spacing           | 1/Å           | setting `k_distance` (group `k_sampling`)          |
| Band-path point spacing   | 1/Å           | setting `k_path_distance` (group `k_path`)         |
| q-point spacing           | 1/Å           | setting `q_distance` (group `q_sampling`)          |
| Phonon-DOS mesh spacing   | 1/Å           | setting `dos_q_distance` (group `phonon_dos`)      |
| Smearing width            | Rydberg (Ry)  | setting `degauss` (group `occupations`)            |
| Wavefunction cutoff       | Ry            | setting `ecutwfc_ry` (group `cutoffs`)             |
| Charge-density cutoff     | Ry            | setting `ecutrho_ry` (group `cutoffs`)             |
| SCF convergence threshold | Ry            | setting `conv_thr` (group `convergence`)           |
| Density-mixing strength   | Dimensionless | setting `mixing_beta` (group `convergence`)        |
| SCF iteration limit       | Integer       | setting `electron_maxstep` (group `convergence`)   |
| Force threshold           | Ry/Bohr       | setting `forc_conv_thr` (group `relax`)            |
| Phonon frequency          | cm⁻¹          | the phonon DOS (`pwscf.phdos`) and its step, `phonon_dos.delta_e`; the dispersion (`pwscf.freq`) |

Energies use Quantum ESPRESSO's Rydberg convention, not Hartree: 1 Ha = 2 Ry.
The SCF threshold controls the estimated self-consistency error; it is not a
k-point or cutoff convergence tolerance.

Every setting above is listed by `goldilocks settings` (with its group, type,
and default) and, once resolved for a structure, shown in the matching record
from `goldilocks explain`/the published `goldilocks.json` (`k_sampling`,
the `k_path` of a `band` task or of a phonon task's dispersion, a phonon
task's `q_sampling` and `phonon_dos`, `occupations`, `cutoffs`,
`convergence` and `relax` respectively). `k_distance` defaults to `0.15`
for metals or when metallicity is unknown and `0.30` for a confirmed
non-metal; `k_path_distance` to `0.025`; `q_distance` to `0.3`; `dos_q_distance` to
`0.10`; `forc_conv_thr` to `1e-3` Ry/Bohr, or `1e-4` in the phonon tasks'
relaxation; `degauss` defaults to
`0.01` Ry for metals; `ecutwfc_ry`/`ecutrho_ry` are decided together by the
`cutoffs` advisor from the selected pseudopotentials' own published
recommendations. When the table publishes no charge-density cutoff
(PseudoDojo), `ecutrho_ry` is its `charge_density_dual` times the resolved
`ecutwfc_ry` (a human one included), reported as the info notice
`cutoffs.ecutrho_derived_from_dual`.

## K-point spacing and shifts

`k_distance` uses solid-state reciprocal lattice vectors, including the 2π
factor (matching AiiDA-QuantumESPRESSO's k-distance convention). For each
reciprocal vector `b_i`, the grid size is:

```text
N_i = max(1, ceil(round(L_i / k_distance, 5)))   along a periodic lattice vector
N_i = 1                                          along a vacuum axis
```

`L_i` is the longest `|b_j|` among the periodic lattice vectors that a
rotation of the cell's point group mixes with vector `i`, directly or through
the third, `|b_i|` itself included. Vectors the point group mixes therefore
get the same count, the larger one, and the mesh is one the point group maps
onto itself. The point group is searched on the cell's species, spin classes
included, at a 0.01 Å tolerance. Rounding to five decimal places avoids
numerical noise at integer boundaries. A smaller `k_distance` gives a denser
mesh. The human-override, `k_distance`, and `k_grid` paths all default to
shift `[0, 0, 0]` (Gamma-centered) when no explicit `shift` is given; the
ML-based k-point model (`qrf-kpoints`) is wired into `k_distance`'s own
heuristic-vs-ml resolution, not into shift selection. In Quantum ESPRESSO's
`K_POINTS automatic` convention this includes Γ (the reciprocal-space
origin), even for even-sized meshes; a shift flag of `1` means a half-grid
shift on that axis.

A vacuum axis is a lattice vector along which the cell has an atom-free slab
wider than 5 Å (the `geometry` record's `vacuum_axes`), so a slab gets one
k-point across its vacuum and a molecule in a box the Γ-point alone, for any
`k_distance` or `k_index`; an explicit `k_grid` is written as given.

A phonon task's q-point mesh (`q_distance`) and phonon-DOS mesh
(`dos_q_distance`) follow the same formula on the written cell, vacuum axes
and mixed vectors included. An explicit `q_grid` is the q-point mesh as
given, but is refused unless every symmetry operation pw.x keeps maps it onto
itself, with one division along each vacuum axis and equal counts on mixed
vectors (see [Check the phonon tasks](science.md#check-the-phonon-tasks)).

## Band path spacing

A `band` task's bands step runs a path of high-symmetry lines instead of a
mesh (see [Check the band structure path](science.md#check-the-band-structure-path)),
and a phonon task's dispersion step the same path.
`k_path_distance` follows `k_distance`'s convention, 2π included. A segment
of the path of length `L`, measured with the written cell's reciprocal
vectors (in the plane of a slab), takes

```text
n = max(1, ceil(round(L / k_path_distance, 5)))
```

equal steps, so no step is longer than `k_path_distance`. pw.x runs every
point of the path: the sum over its branches of their steps plus one, per
spin channel. matdyn.x runs every point of the dispersion's path once, by
the same sum; on fixed occupations, unless `isolation='slab'`, that path
lists each Γ inside a branch twice, ending one branch and starting the
next, and a segment into Γ can take a few more steps (49 becomes 50), so
that it lands on Γ exactly (see
[Check the phonon tasks](science.md#check-the-phonon-tasks)). The default,
`0.025` Å⁻¹, is aiida-quantumespresso's `bands.yaml` (balanced); the
setting's lower bound is `0.001` Å⁻¹.

## Defaults

| Setting                                       | Default                                                        |
| ---------------------------------------------- | ---------------------------------------------------------------- |
| Target                                        | Quantum ESPRESSO, SCF single point                             |
| Exchange-correlation functional               | `PBEsol`                                                       |
| Pseudopotential accuracy tier                 | `efficiency` (only usable tier today, see below)               |
| SCF threshold / total-energy threshold        | `conv_thr = nat × 0.2e-9` Ry / `etot_conv_thr = nat × 1e-5` Ry |
| Mixing / iteration limit                      | `mixing_beta 0.4` / `electron_maxstep 80`                      |
| Hubbard +U (d/f compounds with O or F)        | Built-in Dudarev U_eff table, see [Check Hubbard +U](science.md#check-hubbard-u) |
| Fixed Hubbard occupations (+U)                | `mixing_fixed_ns` unset (QE's 0)                               |
| Hubbard projectors (+U)                       | `hubbard_projectors` `ortho-atomic`                            |
| Confirmed metal, or metallicity unconfirmed   | `smearing`, `cold`, `degauss` `0.01` Ry                        |
| Confirmed non-metal                           | `fixed`, no width, where it can run; otherwise `smearing` as above |
| `band` task's bands step                      | `k_path_distance 0.025` Å⁻¹; `nbnd` three times the occupied bands |
| Phonon tasks' relaxation                      | `forc_conv_thr 1e-4` Ry/Bohr (the `relax` and `vc-relax` tasks: Quantum ESPRESSO's `1e-3`) |
| Phonon tasks' first step                      | k-mesh raised against the q-mesh; no `max_seconds`, a job timer at 95% of the walltime |
| Phonon tasks' ph step                         | `q_distance 0.3` Å⁻¹; `tr2_ph 1e-18`, `alpha_mix(1) 0.4`, `nmix_ph 8` |
| Phonon tasks' q2r and phonon_dos steps        | `asr` `simple`; `dos_q_distance 0.10` Å⁻¹, every 1 cm⁻¹ |
| Phonon tasks' dispersion step                 | the `band` task's path at `k_path_distance 0.025` Å⁻¹          |

`conv_thr`/`etot_conv_thr` scale with the structure's atom count `nat`, not a
fixed constant: for Si (`nat=8`) this gives `conv_thr = 1.6e-9` Ry and
`etot_conv_thr = 8e-5` Ry, matching real `goldilocks explain` output. The
products are exact decimals (`nat=14` gives `2.8e-9`), and the input writes
every real namelist value to at most 12 significant digits.
`mixing_beta` and `electron_maxstep` are fixed defaults. `mixing_fixed_ns` is
never set by default; see [Check SCF convergence](science.md#check-scf-convergence).

Today `efficiency` is the only usable pseudopotential accuracy tier: there is
no setting to request `precision`, and pinning a `precision`-tier
`pseudo_table_id` makes pseudopotential resolution `Unavailable` rather than
switching tiers (verified:
`--set pseudo_table_id=pseudodojo-pbesol-precision-sr` on `Si.cif` errors
with `accuracy is precision, requested efficiency`). This is a genuine
current gap, not a doc omission.

Metallicity comes from `is_metal` (`FieldState[Metallicity]`): a *confirmed*
non-metal gets `fixed` occupations; a confirmed metal, or a structure where
composition alone cannot confirm metallic character (`is_metal` is
`Unavailable`), gets `smearing`. This is deliberate -- a wrong-but-plausible
fixed-occupations run is worse than an unnecessary but correct smearing run.
The phonon tasks are the exception: ph.x treats a smearing run as a metal,
which an insulator is not, so they refuse smearing or tetrahedra on a
composition that is not all-metallic until you set `is_metal=metal` or the
run is on fixed occupations, which `is_metal=non_metal` alone does not give
the runs described below (see
[the phonon tasks](science.md#check-the-phonon-tasks)).
A non-metal gets `fixed` only where both spin channels hold a whole number of
electrons: an even electron count without spin polarization (with or without
spin-orbit coupling), any count on a spin-polarized spin-orbit run, or a
collinear spin-polarized run with an integer
`tot_magnetization` of the electron count's parity (one you set, or 0 for a
`magnetic_ordering` compensated by symmetry). Otherwise it gets `smearing`,
so no default is refused before generation; see
[Check electronic occupations](science.md#check-electronic-occupations).

Each per-step advisor module under `src/goldilocks_core/advisors/` documents
and owns its own heuristic default (e.g. `occupations.py` for smearing,
`convergence.py` for SCF thresholds, `functional.py` for the default
functional); there is no single parameters/policy module. The default code
and task, `quantum_espresso` and `scf_single_point`, are the CLI's
`--code`/`--task` defaults and those of the HTTP/MCP request document
(`server/documents.py`).

Spin, dispersion, and electronic-character heuristics are described in
[Check your recommendations](science.md). Pseudopotential compatibility
exceptions belong to the [table guide](pseudopotentials.md#choose-a-table).

## Override precedence

Fields below are `--set`-able keys (see `goldilocks settings` for the full,
live list) that `set_overrides.build_overrides` turns into a `RunOverrides`
object for one task, consumed by `service.advise()`/`generate()` and their
task variants. Each key reaches the steps of that task it applies to; a key
no step of the task reads is refused, and `steps.<step>.<key>` sets one step
only, ahead of the plain key for that step (see the
[CLI reference](cli.md#scientific-controls)). Leaving a key unset
leaves the choice to Goldilocks's heuristics, or -- for `is_metal`,
`is_magnetic`, and `k_distance`, where an ML tier is wired and resolves
ahead of the heuristic -- to a real model prediction (`human > ml > llm >
heuristic`; see `goldilocks settings` for each key's actual sources).

- `k_grid` wins over `k_distance`; either one bypasses the heuristic
  k-point sizing entirely (the `k_sampling.grid_and_distance_conflict` info
  warning fires if both are given).
- A `dos` task's nscf step has a protocol tier between your settings and
  the ML tier, for that step only: k_distance 0.10 Å⁻¹ and `tetrahedra_opt`
  occupations (aiida-quantumespresso's `pdos.yaml`, balanced). Its values read
  `heuristic` with the protocol named in `source_note`; `human` means only a
  value set in the request. A setting you give replaces the protocol field by
  field: a `shift` alone keeps the protocol's k_distance, and a
  `smearing_type`/`degauss` alone keeps `tetrahedra_opt` and is not applied
  to the nscf step.
- A `band` task's bands step has protocol defaults of its own:
  `k_path_distance` 0.025 Å⁻¹ and three times the occupied bands
  (aiida-quantumespresso's `bands.yaml`), read `heuristic` with the protocol
  named in `source_note`. `nbnd` replaces the band count, and `extra_bands`
  adds to it. The step takes the scf step's occupations, a `tetrahedra_opt`
  written as cold smearing at 0.01 Ry, so `occupations`, `smearing_type` and
  `degauss` set the scf step only. Its scf step derives no
  `tot_magnetization = 0` for a compensated `magnetic_ordering`, and a
  collinear band task refuses one you set (see
  [the band structure path](science.md#check-the-band-structure-path)).
- A phonon task holds its first step's k-mesh against its q-point mesh after
  every k tier: a mesh the request did not set is raised, to the next
  multiple of each q-axis with smearing or tetrahedra and to at least it with
  fixed occupations, and a `k_grid`, `k_index` or `k_distance` you set is
  used as given, with `phonon.k_grid_coarser_than_q` or
  `phonon.k_grid_not_commensurate` where it falls short. `q_grid` wins over
  `q_distance` (the `q_sampling.grid_and_distance_conflict` info warning
  fires if both are given). The phonon tasks' protocol values,
  `forc_conv_thr` 1e-4 Ry/Bohr for their relaxation (aiida-quantumespresso's
  pw `base.yaml`), `q_distance` 0.3 Å⁻¹ and the ph.x settings (its ph
  `base.yaml`), `dos_q_distance` 0.10 Å⁻¹, and the dispersion's
  `k_path_distance` 0.025 Å⁻¹ (its `bands.yaml`), read `heuristic` with the
  protocol named in `source_note`, and a value you set replaces each one
  alone. The relaxation's `forc_conv_thr` has no ML or LLM tier: a value you
  set wins over the protocol, which wins over Quantum ESPRESSO's 1e-3, and
  one looser than 1e-4 gets the warning `phonon.loose_force_threshold`.
- `smearing_type` and `degauss` are independent overrides in the
  `occupations` group; `degauss` defaults to `0.01` Ry (the metallic
  cold-smearing default) if smearing is chosen without an explicit value.
  `occupations='fixed'` always carries no `smearing_type`/`degauss`.
- `conv_thr`, `etot_conv_thr`, `mixing_beta`, and `electron_maxstep`
  override independently; an unspecified `conv_thr`/`etot_conv_thr` falls
  back to the per-atom-scaled formula (see Defaults above), not a fixed
  constant. `etot_conv_thr` applies to relax and vc-relax only, the runs
  that compare energies between ionic steps. `mixing_beta`, `mixing_mode`,
  `mixing_fixed_ns` and `electron_maxstep` tune the SCF loop, so they apply
  to the scf, relax and vc-relax steps and not to a `dos` task's nscf step
  or a `band` task's bands step, which pw.x diagonalizes once in the scf
  step's density. `conv_thr` sets their diagonalization threshold instead,
  `max(1e-13, 0.1 × min(1e-2, conv_thr / nelec))` (Quantum ESPRESSO's
  setup.f90).
- The functional comes from the `functional` setting (default `PBEsol`).
  There is currently no setting to choose the pseudopotential accuracy
  tier -- it is hardcoded to `efficiency`; pinning a `precision`-tier
  `pseudo_table_id` will make pseudopotential resolution `Unavailable`
  rather than switch tiers (see Defaults above). This is a known current
  gap, not a doc omission.
- `hubbard_projectors` chooses the projectors of the HUBBARD card when an
  element gets +U, for every task, and changes nothing without +U; a U value
  is used unchanged with either projector type (see
  [Check Hubbard +U](science.md#check-hubbard-u)).
- `spin_polarized` and `spin_orbit_coupling` are independent settings
  (group `magnetic`) consumed together by one combined advisor,
  `magnetic_config.py`, specifically so that enabling one can never
  silently clear or ignore the other.
- `use_vdw` explicitly enables or disables dispersion. `method` alone
  changes the method only if dispersion is otherwise enabled; it does not
  enable dispersion for a 3D or unknown structure. Enabled dispersion
  defaults to `d3bj` if no method is given. `use_vdw=true` is refused for a
  functional without D3(BJ) parameters, which is any functional except PBE
  and PBEsol (LDA included).
- The single setting `pseudo_table_id` pins an explicit table id instead
  of automatic selection. An explicit table must still satisfy the
  already-decided functional/accuracy/relativistic-treatment/element-coverage
  requirements, or the whole pseudopotential resolution becomes
  `Unavailable` (naming which tables would have matched); pinning a table
  never changes the requested functional, and (today) accuracy can't be
  changed via any setting at all -- see the accuracy-tier gap noted above.

## Relativistic modes

`relativistic` is a derived value, not a settable field -- it is shown in
`goldilocks explain`/`goldilocks.json`, and as each pseudopotential table's
own `relativistic` classification in `goldilocks assets`/`capabilities`.

| `relativistic` value | Meaning                                           |
| --------------------- | -------------------------------------------------- |
| `scalar`              | Scalar relativistic effects, without explicit SOC |
| `full`                | Fully relativistic data, needed for explicit SOC  |
| `non-relativistic`    | No relativistic treatment                         |

It is always derived from `spin_orbit_coupling`: Goldilocks requests `full`
when SOC is enabled and `scalar` otherwise. There is no direct override for
the relativistic treatment itself. Pinning a `pseudo_table_id` whose own
relativistic classification does not match what `spin_orbit_coupling`
implies makes pseudopotential resolution `Unavailable` (it does not override
the derived requirement). Fully relativistic files alone do not enable SOC.
With SOC enabled, QE generation writes `noncolin = .true.` and
`lspinorb = .true.`, a noncollinear run whether or not it is magnetic;
otherwise spin-polarized advice produces a collinear `nspin = 2` run.
`tot_magnetization` belongs to the collinear run only, since pw.x stops on
it without `nspin = 2`: it is refused before generation together with
`spin_orbit_coupling`, and ignored with a warning when `spin_polarized` is
explicitly false. A collinear `band` task refuses it too, since `bands.x`
stops on it, and so does a phonon task with smearing or tetrahedra, since
ph.x refuses the two Fermi energies it gives there. The phonon tasks also
refuse `spin_orbit_coupling` together with a Hubbard U, since ph.x's DFPT+U
treats collinear spins only. A noncollinear run with fixed occupations needs no
`tot_magnetization`; its moments come from `starting_magnetization`. A
magnetic noncollinear run also writes `angle1`/`angle2` for every species:
the direction of `moment_direction`, a lattice direction of the uploaded
cell, [0, 0, 1] by default (see
[Check magnetism and spin-orbit coupling](science.md#check-magnetism-and-spin-orbit-coupling)).
