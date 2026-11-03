# Check your recommendations

Goldilocks suggests starting inputs for a Quantum ESPRESSO calculation --
self-consistent-field (SCF), density of states (DOS), band structure (`band`),
relaxation (`relax`), variable-cell relaxation (`vc-relax`), or phonons with
their density of states and dispersion (`phonon`, `relax-phonon`,
`vc-relax-phonon`). It does not establish that your energy, forces, or other
properties are converged.
Review the choices below before running a calculation, then test the
settings against the accuracy your work needs.

For a first calculation, use the [quickstart](quickstart.md). For exact units,
defaults, and override precedence, see [Scientific conventions](conventions.md).

## Check electronic occupations

Smearing smooths electron occupations near the Fermi energy to help metals
converge. Goldilocks chooses the occupations scheme from the `is_metal`
analysis fact:

| `is_metal` result                                     | Default occupations                              |
| ------------------------------------------------------ | ------------------------------------------------- |
| `metal`, or unavailable (composition couldn't decide)  | Smearing (`smearing_type='cold'`, `degauss=0.01` Ry) |
| `non_metal`, where fixed occupations can run (below)  | Fixed occupations, without smearing               |
| `non_metal`, otherwise                                 | Smearing, as for a metal                          |

Ahead of the heuristic, a published CGCNN classifier (installed by default as
`models/is-metal-classifier`) can resolve `is_metal` directly from structure;
`is_metal` only falls back to the heuristic below when that model asset is
not installed or fails verification. If the installed model fails to run,
the request fails rather than silently using the heuristic. The heuristic
itself returns `metal` only when every element in the composition is a metal
according to pymatgen (elemental metals and intermetallics). Any other
element (O, N, the halogens, H, metalloids such as Si) leaves `is_metal`
unavailable, naming those elements: whether such a compound conducts depends
on its band filling, which composition cannot settle, so insulating NaCl and
MgO look the same to it as metallic RuO2 and TiN. Unavailable -- like an
actual `metal` result -- still defaults to smearing, not fixed occupations,
because assuming "fixed" on an undetected metal risks silent
non-convergence. A confident `non_metal` result is reachable via a human
override (`--set is_metal=non_metal`), the ML classifier, or an LLM override.
Neither the heuristic nor the ML model determines a band structure. The
phonon tasks refuse smearing or tetrahedra on a composition that is not
all-metallic unless you set `is_metal=metal`, since ph.x treats such a run as
a metal, which an insulator is not: an insulator needs fixed occupations (see
[the phonon tasks](#check-the-phonon-tasks)).

Fixed occupations fill whole bands in each spin channel: pw.x puts
(nelec + `tot_magnetization`)/2 electrons in the spin-up channel and
(nelec - `tot_magnetization`)/2 in the spin-down one. A non-metal therefore
gets fixed occupations only where both are whole numbers: a run without spin
polarization and an even electron count, with or without spin-orbit coupling
(without moments, time reversal pairs every spin-orbit band with a degenerate
partner, so an odd count half-fills one); a spin-polarized spin-orbit run,
which has no `tot_magnetization` and fills single-electron bands; or a collinear
spin-polarized run with an integer `tot_magnetization` of the electron
count's parity, either one you set or 0 when the applied `magnetic_ordering`
is compensated by symmetry (see below; a `band` task pins no moment, see
[the band structure path](#check-the-band-structure-path)). Any other
non-metal gets smearing.
LiFePO4, or NiO classified as a non-metal, therefore runs spin-polarized on
smearing instead of being refused. The occupations record's
`tot_magnetization` is the moment the input pins: the one you set, with any
occupations, or the derived 0 under fixed occupations. If you set
`occupations` to `fixed` on a collinear spin-polarized run with no such
moment, it gets the warning
`occupations.fixed_spin_polarized_needs_integer_tot_magnetization` and is
refused before generation: set `tot_magnetization` too, or use smearing.

Check the `is_metal` record's `status`, `source`, and `reason` (via
`goldilocks explain --json` or the published `goldilocks.json`'s
`records.is_metal`), and the `occupations` record's own `warnings` array.
When the classifier decided (`source` `ml`), `model.details` holds its
`score` and the `threshold` it was compared with; a score close to the
threshold is a call the model nearly made the other way. A
composition-only `metal` result can still be wrong -- intermetallic
semiconductors such as CsAu or Mg2Sn contain only metals -- and give the
wrong occupation choice for your system. Correct the classification with
`is_metal` (`metal` or `non_metal`, the record's own values; `true`/`false`
are refused), or override the scheme itself with
`occupations` (`fixed`, `smearing`, or `tetrahedra_opt`); when using
smearing, refine it with `smearing_type` (`gaussian`, `mp` for
Methfessel-Paxton, `cold` for Marzari-Vanderbilt, or `fd` for Fermi-Dirac;
default `cold`) and `degauss` (Ry, default 0.01). Test the width together
with the k-point mesh.

## Check k-point sampling

K-points sample the Brillouin zone for reciprocal-space integration. Too sparse
a mesh can leave energies, forces, or electronic properties unconverged.

Without a grid or distance hint, Goldilocks first asks a published
machine-learning k-point model (`qrf-kpoints`, installed by default) to
predict a raw `k_distance` for the structure (if the installed model fails to
run, the request fails); only when that model asset is not installed or fails
verification does it fall back to picking a target k-point spacing
heuristically: 0.15 Å⁻¹ if `is_metal`
resolves to `metal` or is unavailable, 0.30 Å⁻¹ for a `non_metal` (a mesh
that is too coarse on an undetected metal risks silent under-convergence,
while a mesh that is too fine on an actual insulator only costs more
compute). When the model picked the distance, the `k_sampling` record's
`model` keeps QRF95's own prediction interval in `details.interval`. The
published model records no conformal calibration, so a
`k_sampling.model_warning` says that interval carries no coverage guarantee.
`k_distance_interval` is not that interval: it is the range of k-distances
that give the chosen ladder rung.

Each lattice vector in the `geometry` record's `vacuum_axes` (see
[boundary conditions and vacuum](#check-boundary-conditions-and-vacuum)) gets
exactly one k-point, whatever the `k_distance` and its source: electrons do not
disperse across vacuum, so more k-points there only cost compute. A slab gets
one k-point across its vacuum, and a molecule in a box only the Γ-point,
written as a 1×1×1 `K_POINTS automatic` mesh (pw.x rejects `K_POINTS gamma`
with noncollinear spin or k-point pools). The rule reads the vacuum of the cell
that is written, not its dimensionality, so a bulk layered crystal such as
graphite is still sampled along its stacking axis. `k_index` rungs step the
periodic axes only.

The mesh is one the crystal's point group maps onto itself: lattice vectors
that a symmetry operation mixes get the same number of k-points, the larger
one, so no direction is sampled more coarsely than `k_distance` asks and
pw.x can reduce the mesh by every operation it keeps. Meshing each vector
from its own length broke this on cells whose mixed vectors differ in length.
Alpha-U as the Materials Project serves it (the reduced primitive cell of its
base-centred lattice) got 11×10×6, which pw.x ran with 224 irreducible
k-points where the denser 11×11×6 has 144. CIF noise in the seventh
significant figure between the three equal vectors of UN's primitive cell made
`k_index` 33 a 32×33×32 mesh. Equal counts can cost irreducible k-points at
some spacings and save them at most others: on La2CuO4's body-centred
primitive cell, 8×8×4 (48 irreducible k-points) becomes 8×8×8 (59) at
0.24 Å⁻¹, and 18×18×10 (800) becomes 18×18×18 (480) at 0.10 Å⁻¹. `k_index`
numbers the distinct meshes of this kind from the Γ-point down to 0.03 Å⁻¹,
so its rungs are numbered differently from goldilocks-data's k-index ladder
wherever mixed vectors differ in length.

Compare results on denser meshes. Use `k_grid` or `k_distance` to override
the default; an explicit `k_grid` is written as given, vacuum axes included,
even where the point group does not map it onto itself.
Setting either one only affects k-point selection; it does not change the
separate `is_metal` heuristic used elsewhere (e.g. by occupations). A `band`
task's bands step runs no mesh but a path of high-symmetry lines (see
[the band structure path](#check-the-band-structure-path)), and a phonon
task raises its first step's mesh against its q-point mesh (see
[the phonon tasks](#check-the-phonon-tasks)).

## Check the written cell

Every site of the cell has to hold one species. No input file can describe a
site with a fraction of a species, or several (an alloy such as
Fe0.5Ni0.5O, or a vacancy), so `explain`, `run` and the magnetic-ordering
listing refuse such a structure before any advice, naming the first partially
occupied sites (exit 2 on the command line, HTTP 422). Order it first, for
example as a supercell with one species on every site. `inspect` still reads
it, occupancies included.

Quantum ESPRESSO does not search a cell for its symmetry. pw.x tests 32 fixed
Cartesian rotations, the 24 of a cube with its axes along x, y and z and 8 for
a hexagonal axis along z, and keeps those that map the cell as written onto
itself within 1e-5 in crystal coordinates, with a fractional translation of 0
or ±1/n (n = 2, 3, 4 or 6) only, and none at all in a cell that is a supercell
of a smaller one. A cell in pymatgen's frame (c along z, a in the xz plane)
shows it only part of its point group: diamond Si's primitive cell shows 4 of
its 48 operations, so pw.x ran 282 k-points of a 10×10×10 mesh where the full
group gives 47, and `npool` and the memory estimate were sized for 47.

Goldilocks therefore writes the cell in the frame where pw.x keeps the most of
its point group, which is all of it except possibly for the sheets, the cells
that keep their orientation and the supercells described below, and counts
`n_irr_k` with pw.x's rules on the cell it writes. The cell is the uploaded one
(or the cell of an antiferromagnetic ordering), idealized to the space group
spglib finds within 1e-3 Å, which moves atoms of a CIF by about 1e-5 Å, and:

- a cell without vacuum is turned rigidly into its standard orientation (cubic
  axes along x, y and z; a hexagonal a along x and c along z) when pw.x would
  miss operations otherwise, as it does for fcc, bcc and rhombohedral
  primitive cells;
- a slab with its vacuum along c is turned rigidly so that a lies along +x,
  a and b lie in the xy plane and c points to positive z, the frame Quantum
  ESPRESSO's 2D cell constraint and 2D Coulomb truncation assume. There pw.x
  keeps an in-plane 2-fold axis or mirror only where it lies at a multiple of
  30° or 45° from x, so a sheet whose in-plane axes lie elsewhere relative to a
  loses them: a centred-rectangular sheet given in its primitive basis (a = b,
  γ not 60°, 90° or 120°) has them along a ± b and keeps half its operations,
  and `n_irr_k` counts the extra k-points pw.x then runs. A slab with its
  vacuum along a or b, a wire and a molecule in a box keep their orientation;
- the origin moves to a symmetry centre when an off-centre mirror or screw
  axis would give pw.x a fractional translation it rejects, as on the CeTe3
  monolayer, preferring the shift that keeps a slab in one piece inside the
  cell.

The lattice vectors are the uploaded ones, turned, so fractional coordinates
(up to the origin shift), the k-point grid, `k_index`, species labels,
`starting_magnetization`, Hubbard labels, `fix_bottom_layers` and
`moment_direction` keep their meaning, and the energy does not change. The
input keeps `ibrav = 0` with an explicit `CELL_PARAMETERS` card.
`records.magnetic.frame` records the rotation (`rotation`, R with written
lattice vectors = uploaded ones × Rᵀ), the origin shift, the largest
displacement and the number of operations pw.x keeps. A turn that moves no
lattice vector by more than 1e-3 Å only undoes a tilt the idealization gave
the cell; it is recorded as no rotation and counted in the displacement. The
info notice `magnetic.cell_framed` names the rotation, shift and
displacement when the cell was turned, its origin moved, or an atom moved by
1e-4 Å or more.
The `geometry` record describes the uploaded cell, and `geometry_eff` the
written one: its vacuum axes and widths and its `slab` facts, with the bond
rank (`dimensionality`) of the upload, as `symmetry_eff` is the written cell's
`symmetry`. The dipole notice, its `isolation='slab'` offer and the `vc-relax`
default for `cell_dofree` read `geometry_eff`, so a slab uploaded tilted shows
`xy_frame` false in `geometry` and true in `geometry_eff`, and is written, and
relaxed with `'2Dxy'`, in the xy frame.
A `cell_dofree` that holds or frees Cartesian components (`a`, `b`, `c`, `x`,
`y`, `z`, `xy`, `xz`, `yz`, `xyz`) is refused on a turned cell, whose x, y and
z are not the uploaded cell's; `all`, `shape` and `fixa`, `fixb` or `fixc`
keep their meaning. The refusal's remedy unsets `cell_dofree`, for the default
of the written cell: `all`, or `'2Dxy'` for a slab, which `all` would not suit
under `isolation='slab'`.

A supercell, such as the 8-atom conventional cell of diamond, gets no
fractional translations in pw.x, so it keeps only the operations that need
none (24 of diamond's 48), and is counted that way.

The cards write lattice components and fractional coordinates to 10
significant digits, and any smaller than 1e-10 in magnitude as `0`: the
1e-16 Å left where a lattice built from its angles, or turned into its
standard orientation, has a zero, and the 1e-36 coordinates some CIFs list.

## Check pseudopotentials and cutoffs

A pseudopotential replaces the core-electron potential with an effective
potential for the valence electrons. Check that its functional, valence
configuration, and relativistic treatment suit your system.

Goldilocks selects files and cutoff metadata, not system-specific convergence
limits. Quantum ESPRESSO receives the largest wavefunction cutoff and largest
charge-density cutoff among the selected elements. PseudoDojo publishes no
charge-density cutoff, so for its tables `ecutrho` is 4 times `ecutwfc` (the
table's `charge_density_dual`: Quantum ESPRESSO's default, which its
documentation advises keeping for norm-conserving files), flagged by the
`cutoffs.ecutrho_derived_from_dual` notice. An `efficiency` or `precision`
table is a library choice, not proof that your target property is converged.
Test both cutoffs. See [Pseudopotential tables](pseudopotentials.md) for
selection rules, installation, and custom files.

## Check magnetism and spin-orbit coupling

Spin polarization allows different spin populations, decided by `is_magnetic`
(`human > ml > llm > heuristic`, see [CLI reference](cli.md#scientific-controls)).
Once its ML asset is installed and `GOLDILOCKS_MACE_BACKBONE` points at a
downloaded mMACE checkpoint ([mMACE setup](mmace-setup.md)), a published
mMACE-embedding classifier answers directly (if it then fails to run, the
request fails).
Otherwise the heuristic tier answers, and it calls a structure magnetic when
an element carries a local d or f moment or the structure holds an open-shell
radical:

- **Ionic compounds** (an O, S, Se, Te, F, Cl, Br, or I anion is present): the
  first oxidation-state guess from the composition (pymatgen's
  `Composition.oxi_state_guesses`) gives each transition metal its d count
  (group minus oxidation state) and each lanthanide or actinide its f count. A
  shell strictly between empty and full carries a moment: Ni2+ (d8), Fe3+
  (d5), and Gd3+ (f7) do; Zn2+ (d10), Ti4+ (d0), La3+, Ce4+, and Th4+ (f0),
  and Lu3+ (f14) do not. When pymatgen finds no guess (GdI2, Fe3GeTe2, NpO2),
  an element carries a moment if every one of its common oxidation states
  leaves the shell open. Otherwise the heuristic cannot decide: a composition
  those states cannot balance holds the element in another state.
- **Metals and other compounds** (elements, intermetallics, nitrides,
  carbides, borides, hydrides): oxidation states do not describe these, so Cr,
  Mn, Fe, Co, and Ni carry moments, as do Ce to Tm (not La, Yb, or Lu) and, in
  a compound such as UN, the actinides Pa to Md. Cu, the 4d and 5d metals,
  metallic TiN and WC, and the elemental actinide metals (alpha-U) do not.
- **Radicals**, in any structure: an open-shell main-group atom with no
  neighbour within 1.5 times the covalent-radius sum (atoms in a box), or an
  O2 or S2 molecule bonded only to its partner (solid O2).

When the heuristic cannot decide, Goldilocks defaults to spin-polarized with
the warning `magnetic.magnetism_unknown_defaulted_spin_polarized`. An SCF can
quench a moment it was seeded with, but a non-spin-polarized run can never
find one, so a wrong default costs compute time, not physics. The rules still
over-seed where a formally open shell keeps no moment (low-spin Co3+ in
LiCoO2, Mo4+ in MoS2), and a misguessed oxidation state can hide one (pymatgen
reads CrTe3 as d0 Cr6+): set `spin_polarized` when you know better.

A [Hubbard U](#check-hubbard-u) on an element whose d or f count (from the
ionic oxidation-state guess above) is odd also makes the run spin-polarized,
with the warning `magnetic.spin_polarized_for_hubbard_open_shell`, even when
`is_magnetic` says `non_magnetic`, whichever tier said so, your own override
included. Quantum ESPRESSO applies the Dudarev potential per spin, and
without spin polarization each spin holds half of the shell's electrons: 4.5
for Cu2+ (d9), which fills no whole orbital, so +U can neither form the
moment nor open the gap, and pw.x converges to the wrong state without
complaint. The classifier calls tenorite CuO non-magnetic, yet spin-polarized
it forms 0.66 Bohr magnetons per Cu and lies 25.6 meV/atom lower. The rule
reads the shell count, so low-spin Co3+ (d6) in LiCoO2 keeps a non-magnetic
answer. Only an explicit `spin_polarized=false` overrides it.

Spin-polarized inputs get a `starting_magnetization` for every species;
review it for your calculation. Neither tier predicts magnetic *order* (see
`magnetic_ordering` below for that). Override either tier with
`spin_polarized`, or correct the classification with `is_magnetic`
(`magnetic` or `non_magnetic`).

Bands are counted per spin channel, and the default follows pw.x's own rule
(QE setup.f90), sized so the majority channel holds (nelec + |M|)/2 electrons.
M is `tot_magnetization` when the moment is pinned, as in pw.x. On a collinear
smearing run without one, where pw.x would split the electrons evenly, M is
the net moment the starting magnetization seeds (each species' fraction times
its pseudopotential's valence electrons, `records.magnetic.seeded_moment`),
so the default can exceed pw.x's own count. pw.x holds a smearing run's
moment at 2 × `nbnd` − nelec Bohr magnetons without an error: with pw.x's
default 22 bands, hcp Gd converged to 8 instead of 15.5 Bohr magnetons per
cell; Goldilocks gives it 28. An oversized seed only adds
bands. An `nbnd` or `extra_bands` that leaves fewer bands than pw.x accepts
-- the electrons of each spin channel, or one band per electron with
spin-orbit coupling -- is refused before generation, and one that holds the
moment below its seed gets the warning `nbnd.moment_capped`. pw.x checks
these floors only in a run with its own SCF loop, but a `dos` task's nscf
step and a `band` task's bands step need every occupied band too, so the
refusal covers them; on those steps, which run at the scf step's density,
`nbnd.moment_capped` says that bands of the majority channel are left out
if the scf's moment reaches its seed, and names the count to use,
(nelec + |M|)/2 rounded up.

A `starting_magnetization` you set is a fraction of each species' valence
electrons, strictly between -1 and 1: from Quantum ESPRESSO 7.3, a value of
1 or more turns every species' value into a moment in Bohr magnetons, so it
is refused. It is keyed by site label: your file's labels (`goldilocks
inspect` and `/inspect` list them; a POSCAR's are its element symbols), or
the `Ni1`/`Ni2`/`O` labels of an applied `magnetic_ordering`.
`records.magnetic.site_labels` lists the labels in force, even for a run that
is not spin-polarized. An element symbol sets all of that element's sites
(`{"Ni": 0.5}` on a CIF labelled `Ni1`/`O1`), except where an applied
ordering seeds them differently: `Ni` on the `Ni1`/`Ni2` sublattices is
refused, naming the labels to set instead. A label beats its element, so on
a file labelled `Fe1`..`Fe4`, `{"Fe": 0.5, "Fe1": -0.5}` starts `Fe1` at
-0.5 and the other three at 0.5.
Each value replaces the heuristic seed of its sites only; sites you leave out
keep theirs, so `{"Ni1": 0.5}` on NiO's AFM cell keeps `Ni2` at its negative
seed and `O` at 0. `records.magnetic.human_seeded_labels` names the species
you set. The input has one species per element and starting value, whatever
labels your file gave its sites (`Si1`..`Si40` are one `Si`), and sites of
one element with different values become separate species (`Fe0` at 0.5 and
`Fe1` at -0.5 are written as `Fe1` and `Fe2`). A value you set that equals
another site's computed seed still makes its own species, since the computed
seed is known only once the pseudopotentials are chosen. Symmetry and the
irreducible k-points are counted on those species, the way pw.x counts them:
that bcc Fe pair is simple cubic (Pm-3m), not body-centred.
`records.magnetic.starting_magnetization` is keyed by the written species,
not by your file's site labels; an element name there (`Ni`) is also a key
you can set.

Spin-orbit coupling (SOC) couples electron spin to orbital motion. Goldilocks
flags elements at or above Rb (Z=37) whose valence character is p, d, or f for
consideration, but does not enable SOC unless you request it -- heavy s-block
elements (Rb, Sr, Cs, Ba) are excluded because s orbitals carry no
first-order spin-orbit splitting. The flag is the read-only fact `needs_soc`:
it takes no override (`--set needs_soc=...` is an unknown setting) and changes
nothing in the input. `spin_orbit_coupling` is the only setting that enables
SOC. Whether SOC matters depends on the property, not only the elements.
Enabling it changes the required pseudopotentials and the QE spin settings.
See [relativistic modes](conventions.md#relativistic-modes) and the
[table restrictions](pseudopotentials.md#choose-a-table). The info
notice follows the table selection SOC would make. `magnetic.soc_suggested`
names the fully relativistic table automatic selection would use, for
example `pseudodojo-pbesol-efficiency-fr` for fcc Pb under PBEsol. Where no
registered table can serve SOC, the notice is `magnetic.soc_unavailable`
instead and carries the selector's reason. That covers every lanthanide and
actinide, which must use SSSP, and any element under LDA, which has no fully
relativistic table: enabling `spin_orbit_coupling` there would leave
`pseudo_table` unavailable.

A spin-polarized run with SOC is noncollinear: every moment starts along one
direction, and that direction is a physical choice, since magnetic
anisotropy, orbital moments and band splittings depend on it. Set
`moment_direction` to a lattice direction [u, v, w] of the uploaded cell
(`--set 'moment_direction=[1,1,0]'`). Unset, the moments start along
[0, 0, 1], the uploaded cell's third lattice vector, with the info notice
`magnetic.soc_moment_direction_defaulted`; for a CIF that is the c axis. The
direction is a crystal direction, so it keeps its meaning whatever cell is
written, an antiferromagnetic one or one turned into pw.x's frame (see
[the written cell](#check-the-written-cell)) included. It is QE's own
default, Cartesian z, only where c is written along z, which a cell turned
into pw.x's frame (an fcc, bcc or rhombohedral primitive cell) is not, so
`angle1` is not 0 there. `records.magnetic.moment_direction` shows it
and whether you set it, and the input carries it as `angle1`/`angle2`, the
same for every species (the sign stays in `starting_magnetization`). Any
other run ignores `moment_direction` with the warning
`magnetic.moment_direction_ignored`. The irreducible k-points of such a run
are counted the way pw.x counts them: with only the symmetry operations
that keep every moment, alone or combined with time reversal, and no
k -> -k pairing. Cubic B2 FeCo with moments along [001] keeps 16 of its 48
operations, so a 10x10x10 mesh has 126 irreducible k-points rather than
56, and `npool` and the memory estimate follow that count.

Set `magnetic_ordering` to `afm` to opt in to an antiferromagnetic
ordering instead of the ferromagnetic default, or to the label of one
candidate `goldilocks magnetic-orderings` lists (`afm-3`). Like
`tot_magnetization` and
`starting_magnetization`, any `magnetic_ordering`, `fm` included, asks for a
spin-polarized run, so it turns spin
polarization on even for a structure the classifier calls non-magnetic; an
explicit `spin_polarized` false wins and ignores it with the warning
`magnetic.ordering_ignored_spin_polarized_false`. Goldilocks cannot tell you
which magnetic ordering is the true ground state -- that needs comparing total
energies from several actual calculations -- so `afm` only gives one
reasonable, deterministic starting point (`afm-1`, the smallest and most
symmetric ordering found), for you to run and compare against
the ferromagnetic guess yourself. Only the sites the heuristic above says
carry a local d or f moment are ordered, up against down:
the Cu2+ ions of La2CuO4 but not its La3+ (4f0), the Fe of FePt but not its
Pt, whose moment Fe induces. Those sites are seeded up and down with the
calibrated value (5 Bohr magnetons over the pseudopotential's valence for
Ni, 5/18 with an 18-electron pseudopotential); every other species starts
at 0, as in QE's own antiferromagnetic examples, so the start carries no
net moment. `records.magnetic` records the label applied (`ordering`), and
whether the ordering is compensated (`compensated`): whether some symmetry
operation of its cell maps every spin onto an opposite one, so its net
moment is zero by construction. `compensated` is false without an applied
antiferromagnetic ordering, even where starting magnetizations you set on
the uploaded cell cancel by symmetry.
NiO's AFM-II cell is compensated. Spinel Fe3O4's R-3m candidate is not: it
has 3 Fe up and 3 down, but both tetrahedral Fe point down, so it is a
ferrimagnet. Nor is B2 FeCo's `afm-1`, Fe up and Co down in the uploaded
cell: its starting moments sum to zero, but no symmetry makes the two
elements' moments cancel. A compensated non-metal gets fixed occupations with
`tot_magnetization = 0`, except on a `band` task, whose `bands.x` step stops
on any pinned moment: there it runs on smearing (see
[the band structure path](#check-the-band-structure-path)). This is decided
on the starting magnetizations as written, to rounding: yours where you set
them on the applied cell, the
computed ones elsewhere. Setting one NiO sublattice to its computed seed as
`records.magnetic` or `scf.in` gives it (any copy to six significant digits
or more) keeps the cell compensated; setting it to 0.28 or 0.5 does not,
since that start carries a net moment.
A structure with no such site (closed-shell Si, or solid O2, whose moment
belongs to the O2 molecule) keeps the ferromagnetic default with the warning
`magnetic.afm_no_open_shell_sites`; to try an antiferromagnetic pattern
there, upload a cell whose site labels separate the sublattices and set
`starting_magnetization` per label. When the heuristic cannot decide which
sites carry a moment, the warning `magnetic.afm_ordering_unavailable` gives
its reason.
That ordering can need a different cell from the one you uploaded: NiO's
2-atom primitive cell becomes the 4-atom AFM-II cell, and its 8-atom
conventional cell is reduced to the same 4-atom one. The input is then
written for that cell, and everything counted for it (electrons, bands, the
convergence threshold, k-points and the job's memory) is counted on it;
`records.magnetic` names it by formula and atom count. A `nelec` you set
counts the electrons of the cell you uploaded, so it is refused together
with an ordering that changes the cell's size.
pymatgen keeps at most 16 of enumlib's orderings, smallest cells first;
goldilocks has it read enumlib's output in enumlib's own numbering, so the
same 16 are kept wherever the structure is enumerated again with the same
pymatgen-core, spglib and enumlib versions. They are numbered in one order
that depends on the cells alone -- smallest first, then most symmetric --
so a label means the same cell there too; a label
past the listed candidates is refused.
`records.magnetic.ordering` says why the cell was written (`criterion`:
`smallest_cell` for `afm`, `requested` for a label, `identity` when the
uploaded cell is kept) and lists the other candidates with as many sites
(`alternatives`); the `magnetic.afm_ordering_applied` notice names them too.
Smallest-and-most-symmetric is a convention, not a prediction: for Fe2O3 it
picks the Cr2O3-type order (`afm-1`, R3c), not hematite's own (`afm-3`, R-3),
so list the candidates and choose among them.
A slab, a wire or a molecule in a box only gets orderings that keep its
vacuum: a candidate is kept when its cell can be written with the uploaded
vacuum vectors (the `geometry` record's `vacuum_axes`) as cell vectors, and
it is written that way, each vacuum vector where it was and the other
vectors in the plane of the rest. enumlib also offers cells that repeat the structure across the
vacuum -- the GdI2 monolayer's first candidate doubled c, every sheet
ferromagnetic and its only antiparallel Gd 19.94 Å away across the vacuum
-- and those are dropped, so the monolayer gets the in-plane stripe. The
written cell then has the uploaded vacuum, and the slab advice and gates
(one k-point along the vacuum, `isolation`, `fix_bottom_layers`, the
dipole notice) describe one slab. A bulk van der Waals magnet has no vacuum
and keeps its interlayer orderings. When every candidate repeats across
the vacuum, `afm` keeps the ferromagnetic default with a warning saying so.
This needs the external `enumlib` executables (`enum.x` or `multienum.x`,
plus `makeStr.py`, `makestr.x` or `makeStr.x`) on `PATH`. Its cost grows with
the number of moment-bearing sites in your structure's primitive cell, which
is what enumlib orders, not with the atom count: 28-site LiFePO4 has 4 Fe.
Without enumlib, with more than 8 such sites, when enumlib finds no ordering
or a call runs past its 30 s limit, or if no antiferromagnetic ordering
exists for your structure, `afm` degrades to the ferromagnetic default with a warning,
and an `afm-<n>` label is refused with the same reason; any other enumeration
error fails the request. Magnetic moments your file carries
(a magCIF's) are not read; only the seeds above are. Enumeration runs in a
separate worker process, inside a private scratch directory, so it writes
nothing to the current directory and concurrent requests cannot disturb each
other.

`uv run goldilocks magnetic-orderings` lists every candidate this same
enumeration finds -- the ferromagnetic guess plus any antiferromagnetic
ones, by label -- for you to inspect or generate inputs
from with `magnetic_ordering=<label>` on the same structure, optionally
ranked by relaxing each on a frozen mMACE potential
energy surface (`--rank-with-mmace`) rather than picking the ferromagnetic
guess by default. It warns the same way when a structure with a moment gets
no antiferromagnetic candidate, and lists a closed-shell structure's
ferromagnetic guess alone without a warning. See
[Magnetic orderings](cli.md#magnetic-orderings) for the command and its
setup requirements.

## Check dispersion and dimensionality

Dispersion accounts for long-range interactions that common semilocal
functionals can miss. The default D3BJ correction is the D3 method with
Becke–Johnson damping. Goldilocks enables it (`use_vdw=True`) for structures
classified as `molecule`, `1d`, or `2d`, and disables it (`use_vdw=False`) for
`3d`.

D3BJ's damping parameters are fitted per functional, and Quantum ESPRESSO's
DFT-D3 has them only for PBE and PBEsol. With any other functional, LDA
included, a low-dimensional structure gets no correction and the warning
`vdw.d3bj_unavailable_for_functional`, and Goldilocks refuses an explicit
`use_vdw=true` setting before generating the input. pw.x would otherwise stop
at startup with "functional name unknown". The phonon tasks run D3 from
two-body terms only, the terms of the Hessian ph.x reads (see
[the phonon tasks](#check-the-phonon-tasks)).

The classification builds a bond graph and assigns dimensionality with
Larsen's connectivity-rank algorithm. Two atoms are bonded when they are
within pymatgen's JmolNN covalent cutoffs, or when one lies in the other's
nearest-neighbour shell: within 1.1 times that atom's shortest contact,
searched up to 6 Å. The shell bonds the ionic and metallic contacts that
covalent cutoffs miss, so rock-salt NaCl and bcc Na classify as `3d`. In
most molecular crystals and van der Waals layered crystals each atom's
nearest shell lies inside its own molecule or layer, so they classify as
`molecule` and `2d`. It is a heuristic, not a test of whether a dispersion
correction is physically appropriate: a solid held together only by
dispersion, such as a noble-gas crystal, classifies as `3d`, and so does a
molecular crystal whose intermolecular contacts fall inside those bonding
ranges. Check the structure and choose `use_vdw` and `method` accordingly.
A bonding or classification failure reports that dimensionality couldn't be
determined (with a reason) rather than raising an error or silently guessing
-- and the vdW decision itself then becomes unresolved (blocked), not
silently set to `use_vdw=False`.

## Check boundary conditions and vacuum

A molecule, cluster or slab in a periodic cell interacts with its own
periodic images. The `isolation` setting says how the electrostatics treat
them: `periodic` (no correction), `slab` (the Coulomb interaction truncated
along the slab normal) or `isolated` (truncated along all three lattice
vectors). For Quantum ESPRESSO, `slab` writes `assume_isolated='2D'` and
`isolated` writes `assume_isolated='martyna-tuckerman'`; `periodic` writes
neither.

Goldilocks decides from vacuum, not from dimensionality. For each lattice
vector, the `geometry` record reports the widest atom-free slab parallel to
the other two vectors, measured between atom centres
(`vacuum_widths_angstrom`), and lists the vectors with more than 5 Å as
`vacuum_axes`. Only a cell with vacuum along all three lattice vectors is
`isolated` by default. Every other cell is `periodic`, including molecular
crystals such as CO2 dry ice (classified `molecule`), slabs and wires: pw.x has
no 1D truncation for a wire. A layer that is not parallel to two lattice
vectors shows no vacuum, so its cell is treated as periodic.

Martyna-Tuckerman treats the system as a molecule or cluster in a box, so
Goldilocks refuses `isolation='isolated'` on a cell without vacuum along all
three lattice vectors, whoever set it. The correction is exact only when the
electron density lies within half the cell along every axis, which 5 Å of
vacuum does not guarantee, so check the box size. pw.x computes no stress under
Martyna-Tuckerman: the input then omits `tstress`, and Goldilocks refuses a
`vc-relax`. Use `relax` for an isolated system, or set `isolation='periodic'`
for a periodic one. The phonon tasks refuse a molecule or cluster in a box
under any `isolation`: ph.x does not implement Martyna-Tuckerman, and
otherwise computes a periodic array of copies (see
[the phonon tasks](#check-the-phonon-tasks)).

`isolation='slab'` is Quantum ESPRESSO's 2D Coulomb truncation (Sohier,
Calandra and Mauri, Phys. Rev. B 96, 075448 (2017)), which computes energies,
forces and stresses in a two-dimensional framework. It matters for charged,
doped or polar slabs; for a neutral, symmetric monolayer with about 20 Å of
vacuum the periodic default is accurate, and Goldilocks never picks `slab` by
itself. Set it explicitly. Goldilocks refuses it unless the cell to be written
meets pw.x's preconditions: vacuum along c only, a and b in the Cartesian xy
plane, c along z (the only orientation in which pw.x's truncation formula is
exact), a cell at least 21 bohr (11.11 Å) high (pw.x stops when half the height
is below the pseudopotentials' 10 bohr radial cutoff), and vacuum at least 20
bohr (10.58 Å) wider than the slab. The last condition is Quantum ESPRESSO's
safe estimate of a cell more than twice as high as the slab including its
electrons; a monolayer with about 20 Å of vacuum meets it. Under
`slab` only the in-plane stress is meaningful, so a `vc-relax` must use
`cell_dofree='2Dxy'` (the default for such a slab) or `'2Dshape'`. The
refusal's remedies set `'2Dxy'`, or `isolation='periodic'` with `cell_dofree`
unset, since an explicit `all` kept under `periodic` would relax the vacuum.
This refusal is given only for a slab with its vacuum along c and a and b in
the xy plane, whose default is `'2Dxy'`; on any other cell Goldilocks refuses
`slab` itself, with `isolation='periodic'` as the remedy.

A slab can carry a dipole along its normal only if no symmetry operation
reverses that normal: an inversion centre, a mirror in the sheet, a two-fold
axis in the sheet or a rotoinversion axis along the normal cancels it. The
`symmetry` record lists the lattice vectors whose normal some operation
reverses as `reversible_axes`. For a polar slab with `periodic` boundaries,
such as a Janus MoSSe sheet, the images' dipoles add a spurious field across
the vacuum, and Goldilocks adds the `boundary.dipole_correction_suggested`
notice. It names Quantum ESPRESSO's dipole correction (`tefield` and
`dipfield` with `eamp = 0`) along the vacuum axis (`edir`), with the
sawtooth's drop (`emaxpos`, `eopreg`) in the middle of the vacuum, where QE
requires it. The notice offers `isolation='slab'` only when the slab meets
every precondition of that setting. It does not set the
correction itself, because pw.x then uses no symmetry and computes no stress.
The notice describes the cell that is written, which an antiferromagnetic
`magnetic_ordering` writes with the uploaded vacuum (see
[magnetism](#check-magnetism-and-spin-orbit-coupling)), turned and with its
origin moved as [the written cell](#check-the-written-cell) describes. The
`geometry` record's `slab` field (`vacuum_center`, `vacuum_fraction`,
`fits_2d_truncation`) describes the uploaded cell, so it can differ from the
written one when the cell was turned or its origin moved; the `geometry_eff`
record's `slab` field is the written cell's, the one the notice reads.
Symmetric monolayers and bulk crystals get no notice: a bulk layered crystal
such as graphite classifies as `2d` but has no vacuum.

## Check Hubbard +U

A Hubbard +U correction counters the self-interaction error that semilocal
functionals make for localized d and f electrons. Goldilocks applies it when
the `needs_correlation` fact is true -- by default, a compound of a
transition metal, lanthanide, or actinide with O or F, the Materials Project
screening rule -- and never with a hybrid functional. Each element in the
built-in table below then gets its Dudarev U_eff (U - J, in eV) on its 3d,
4d, 5d, 4f, or 5f shell, written as one `U <species>-<manifold> <value>`
line per species under `HUBBARD (ortho-atomic)`, or `HUBBARD (atomic)` with
`hubbard_projectors=atomic` (below):

| Source                              | U_eff (eV)                                                                         |
| ----------------------------------- | ---------------------------------------------------------------------------------- |
| Materials Project                   | V 3.25, Cr 3.7, Mn 3.9, Fe 5.3, Co 3.32, Ni 6.2, Mo 4.38, W 6.2                     |
| Wang et al. 2006 / Jain et al. 2011 | Cu 4.0                                                                             |
| Loschen et al. 2007                 | Ce 5.0                                                                             |
| Topsakal & Wentzcovitch 2014        | Pr 4.0, Nd 3.1, Pm 3.4, Sm 3.3, Eu 3.0, Gd 4.6, Tb 5.0, Dy 5.0, Ho 4.9, Er 4.2, Tm 4.8, Yb 3.0 |
| OQMD qmpy configuration (hubbards.yml) | Pa 4.0                                                                          |
| OQMD (Kirklin et al. 2015)          | U 4.0, Np 4.0, Pu 4.0                                                              |
| Suzuki et al. 2013                  | Am 4.0, Cm 4.0                                                                     |
| Chen & Kaltsoyannis 2025            | Bk 3.54                                                                            |

The other d-block elements, La, Lu, and Th get no U and no warning: the
Materials Project applies none to those d elements, and La3+, Lu3+, and Th4+
have empty or full shells. Ac, Cf, Es, Fm, Md, No, and Lr have no published
U; they also get plain DFT, with a `hubbard.u_value_missing` warning that
names the element and the setting to use (for Ac, why no setting can apply
one). When no element gets a U, the input has no HUBBARD card.

These values come from different codes and fits, and none was derived with
the ortho-atomic projectors the generated input uses by default: every
built-in U then carries a `hubbard.projector_mismatch` warning that lists
the VASP-derived values.
Every applied U, built-in or from `u_by_element`, carries a
`hubbard.starting_ns_eigenvalue_missing` warning, since +U calculations can
converge to a metastable occupation matrix and Goldilocks supplies no
initial guess; a `u_by_element` value gets no projector warning, because
Goldilocks does not know how it was derived. U also depends on oxidation
state and environment, so treat one value per element as a starting point:
test your property against U, or calibrate it (for example by linear
response with `hp.x`, which Goldilocks does not set up).

`u_by_element` replaces the table: only the listed elements present in the
structure get +U, e.g. `--set 'u_by_element={"Ti": 4.0}'`, and listed
elements the structure does not contain are ignored with a
`hubbard.u_by_element_unused` warning. Keys must be element symbols and
values finite and positive. La and Ac are rejected: no installed La
pseudopotential has an occupied 4f channel and the only Ac one has no 5f
channel, so pw.x stops on any U for them. `hubbard_needs_correlation=false`
runs without +U. The `hubbard` record in `goldilocks explain --json` and
`goldilocks.json` lists every applied U with its `value_source` (`table` or
`human`), citation, and DOI.

`hubbard_projectors` chooses the projectors the HUBBARD card names, for every
task: `ortho-atomic`, the default, which Quantum ESPRESSO recommends, or
`atomic`, the only type with which ph.x computes phonons with a U, so the
phonon tasks need it with +U (see [the phonon
tasks](#check-the-phonon-tasks)). pw.x computes forces and stress with either.
A U value is tied to the projectors it was derived with (Timrov et al., Phys.
Rev. B 102, 235159 (2020)), so switching projectors changes what a given U
means; the built-in table is used unchanged with either, and so is a
`u_by_element` value. The Pr-Yb values were fitted in Quantum ESPRESSO with
atomic projectors, so with `atomic` they carry no `hubbard.projector_mismatch`
warning, which then names the VASP-derived and the all-electron (Am, Cm, Bk)
values and appears only where one of those is applied. A structure relaxed
with one projector type is not at equilibrium with the other, so relax and
compute phonons with the same setting. The `hubbard` record holds the type in
`projectors`, with its source in `field_sources`, and `null` when no element
gets a U, where the setting changes nothing.

## Check SCF convergence

The SCF energy-convergence threshold (`conv_thr`) and total-energy threshold
(`etot_conv_thr`) scale with atom count rather than being flat defaults;
density-mixing strength (`mixing_beta`) and the iteration limit
(`electron_maxstep`) are flat defaults carried over unchanged. None of these
are model predictions. Inspect the actual QE convergence history and adjust
these settings if needed. Reaching the SCF threshold does not demonstrate
convergence with respect to k-points or cutoffs.

The density-mixing mode (`mixing_mode`) is `local-TF`, Quantum ESPRESSO's
screening for highly inhomogeneous densities, for a cell with vacuum along any
lattice vector (a slab, a wire or a molecule in a box). Every other cell gets
QE's default `plain`, including bulk layered crystals such as graphite, which
classify as `2d` but have no vacuum.

Goldilocks writes no `mixing_fixed_ns` for +U inputs unless you set it, so
pw.x uses its own default of 0 and converges the Hubbard occupation matrix
together with the density. For the first `mixing_fixed_ns` iterations pw.x
holds that matrix at its starting value, and it can report convergence before
the window ends. The energy, forces and stress are then those of the starting
occupations, not a self-consistent DFT+U result, and the stress calculation
can abort with "non-symmetric stress contribution". A value you set is
written as given. On an input with a HUBBARD card, a nonzero value carries a
`convergence.mixing_fixed_ns_freezes_hubbard_occupations` warning; without a
card, pw.x ignores the keyword. Set a nonzero value only for a preparatory
run whose output seeds a separate run with the occupations free. If a +U SCF
needs more than `electron_maxstep` iterations, adjust `mixing_beta` or
`electron_maxstep` rather than freezing the occupations.

## Check relaxation settings

For `relax` and `vc-relax` tasks, and the relaxation that `relax-phonon` and
`vc-relax-phonon` run before their phonons, Goldilocks also picks ionic and
cell relaxation parameters -- `ion_dynamics`, `cell_dofree`, `cell_factor`,
`forc_conv_thr`, `nstep`, `press`, `press_conv_thr`,
`trust_radius_ini`/`trust_radius_max`/`trust_radius_min`, `remove_rigid_rot`,
and `fix_bottom_layers` (fixing the bottom N atomic layers of a slab during
relaxation). Every default is copied verbatim from Quantum ESPRESSO's own
documentation, not derived from a model, except the phonon tasks'
`forc_conv_thr`. See `goldilocks settings` for each key's group, type, and
default.

The phonon tasks relax to `forc_conv_thr` 1e-4 Ry/Bohr,
aiida-quantumespresso's balanced pw protocol (fast 1e-3, stringent 0.5e-4),
ten times tighter than Quantum ESPRESSO's 1e-3, which the `relax` and
`vc-relax` tasks keep: DFPT takes second derivatives at the relaxed geometry,
and leftover forces shift the phonon frequencies, soft modes most (see [the
phonon tasks](#check-the-phonon-tasks)). The `relax` record then reads
`heuristic`, names the protocol in `source_note` and cites it. A
`forc_conv_thr` you set is used as given, and one looser than 1e-4 gets the
warning `phonon.loose_force_threshold`. The other relaxation defaults are the
same in every task, `nstep` 50 included. The final scf of a vc-relax counts
against `nstep`: a vc-relax that converges at its last allowed step has none
left for that scf, and `submit.sh` stops with exit status 3, asking for a
larger `nstep`. The phonon tasks refuse `fix_bottom_layers`
(`phonon.fix_bottom_layers_unsupported`, with the remedy of unsetting it):
pinned atoms keep their forces, while DFPT computes the phonons at an
equilibrium, where every force is zero. That finding replaces the slab rules
below for the same setting.

`fix_bottom_layers` counts atomic layers along the slab's vacuum axis, up from
the upper edge of the vacuum, so a slab that wraps across the cell boundary
keeps its true bottom; atoms within 0.5 Å of each other along the normal share
a layer. Goldilocks refuses the setting unless the cell to be written has
one vacuum gap, along exactly one lattice vector, and at least N layers. A
bulk crystal has no bottom layer to fix, even a layered one that classifies
as `2d`, and nor has a cell holding two slabs, such as a monolayer doubled
along its normal.

The `vc-relax` default for `cell_dofree` comes from the vacuum, not from
dimensionality. A cell without vacuum gets `'all'`, so the stacking axis of a
bulk layered crystal such as graphite relaxes too. `'2Dxy'` moves only the x
and y components of a and b and holds c fixed, so a slab gets it only when its
vacuum lies along c and a and b lie in the Cartesian xy plane, the frame every
slab with its vacuum along c is written in (see
[the written cell](#check-the-written-cell)). The `geometry` record's `slab`
field shows the vacuum axis and whether the uploaded cell is in that frame
(`xy_frame`); the default is decided on the written cell, whose `slab` facts
the `geometry_eff` record shows. A wire, or a slab
with its vacuum along a or b, has no default:
Goldilocks refuses the `vc-relax` until you set `cell_dofree` or reorient the
cell. Whatever its source, `'2Dxy'` or `'2Dshape'` is refused
unless a and b lie in the xy plane and any vacuum lies along c. Otherwise
pw.x would distort the cell, or move a vacuum vector while holding a vector
of the sheet fixed. The refusal offers `cell_dofree='all'` as its remedy
only for a cell without vacuum: with vacuum, `all` would relax the vacuum
too, and the refusal names what holds it fixed instead. That is reorienting
a slab, the constraint that holds a wire's two vacuum vectors fixed and
relaxes only its period in any orientation (`'epitaxial_ab'` for a wire
periodic along c, where `'z'` would move only the z component of c), or the
`relax` task for a molecule in a box, whose every lattice vector is a vacuum
vector. A wire's `vc-relax` without `cell_dofree` is refused naming the same
constraint.

`cell_dofree` accepts only the values pw.x honours under the `ibrav = 0` every
written input has. `'volume'` is refused, because pw.x stops on it unless
`ibrav = 1`. `'ibrav'` and the `'ibrav+...'` forms are refused too: under
`ibrav = 0` pw.x ignores the `ibrav` part and only warns that it has no
effect.

## Check the band structure path

The `band` task runs three steps in one job: an scf; pw.x with
`calculation='bands'` (`bands.in`), which reads the scf's charge density and
Fermi energy and computes the bands at every point of a path of
high-symmetry lines through the Brillouin zone, with no SCF loop and no
reduction of the path by symmetry; and `bands.x`, which collects the bands
for plotting.

The path is read from the symmetry of [the written cell](#check-the-written-cell),
each site typed by its species as pw.x types it, within 1e-3 Å, the
tolerance that cell was idealized to. The `Ni1`/`Ni2` sublattices of an
antiferromagnetic ordering therefore stay distinct, and the run gets the
path of its magnetic cell: NiO's AFM-II cell is rhombohedral (R-3m), so it
gets the rhombohedral path, not rock salt's fcc one. The vertices are
crystal coordinates of the written cell's reciprocal vectors, as
`K_POINTS crystal_b` takes them. A conventional cell or a supercell gets the
path of its primitive cell, written in its own basis, and folded bands: at
each point of the path, the bands of several points of the primitive cell's
zone appear together. The `k_path` record counts the primitive cells
the written cell holds (`primitive_cells`) and, above 1, carries the info
notice `k_path.folded_bands`. The bundled `Si.cif`, diamond's 8-atom
conventional cell, holds 4; upload the primitive cell for unfolded bands. A
slab cut from a conventional cell can repeat its layer's primitive cell in
the plane: pymatgen's `SlabGenerator`, given the 4-atom cell of fcc Cu,
writes Cu(111) and Cu(211) slabs that hold 4 primitive cells of their layer
and a Cu(311) slab that holds 12.

The vacuum of the written cell, measured as for the `geometry` record's
`vacuum_axes` (see
[boundary conditions and vacuum](#check-boundary-conditions-and-vacuum)),
decides the kind of path:

- **Bulk.** Setyawan and Curtarolo's path for the lattice type (Comput.
  Mater. Sci. 49, 299 (2010)), as pymatgen gives it for the standard
  primitive cell, carried into the written cell's basis by the integer
  matrix that maps one lattice onto the other, accepted only where every
  written site lands on a site of its own species. A triclinic path runs
  from Γ to each of the seven time-reversal-invariant points, each taken at
  its equivalent on the boundary of the first Brillouin zone, so that every
  segment stays inside the zone; a triclinic lattice with a right reciprocal
  angle, for which pymatgen gives no path or picks a table by rounding, gets
  Setyawan and Curtarolo's TRI1a table whatever its orientation, though not
  always along the same lines (see the end of this section). A primitive
  monoclinic crystal whose two lattice vectors normal to its unique axis
  are equal in length, as on a C-centred orthorhombic or hexagonal lattice,
  is put in Setyawan and Curtarolo's setting, which pymatgen leaves it out
  of, before its path is read.
- **Slab** (vacuum along one lattice vector). The layer is made contiguous
  about the middle of the vacuum, and its vacuum vector is replaced by its
  component along the normal, so a tilted c or a layer straddling the cell
  boundary keeps the layer's symmetry. The layer's 2D Bravais system is
  read from the point group of its primitive cell, with time reversal, and
  the path is ASE's for that system (table below), as the C2DB database
  uses them (Larsen et al., J. Phys.: Condens. Matter 29, 273002 (2017)).
  Every vertex is at 0 along the vacuum vector, across which electrons do
  not disperse. A monoclinic layer whose unique axis lies in the sheet, such
  as 1T'-WTe2, is rectangular, so its path passes through Γ, which the
  in-plane segments of its 3D path would miss.
- **Wire** (vacuum along two). One segment along the wire, from Γ to Z on
  the zone boundary of the wire's own period; a cell that holds several
  periods gets folded bands.
- **Molecule or cluster in a box** (vacuum along all three). It has no band
  structure, so the band task is refused (`advice.blocked`): use
  `scf_single_point` or `relax`.

| Slab's 2D Bravais system | `lattice_type` | Path              |
| ------------------------ | -------------- | ----------------- |
| Hexagonal                | `HEX2D`        | Γ-M-K-Γ           |
| Square                   | `SQR`          | M-Γ-X-M           |
| Rectangular              | `RECT`         | Γ-X-S-Y-Γ-S       |
| Centred rectangular      | `CRECT`        | Γ-X-A_1-Y-Γ       |
| Oblique                  | `OBL`          | Γ-Y-H-C-H_1-X-Γ   |

The record and the input name the vertices in ASCII: `Gamma`, `X_1`,
`Sigma_1`, `A_1`. `k_path_distance` is the largest spacing between
neighbouring points of the path, in 1/Å with 2π included as for
`k_distance`: each segment takes the fewest equal steps no longer than it
(see [band path spacing](conventions.md#band-path-spacing)), and pw.x
interpolates those points between the vertices the `K_POINTS crystal_b` card
lists, each row ending with its vertex's label as a `! label` comment. The
default, 0.025 Å⁻¹, is aiida-quantumespresso's `bands.yaml` (balanced); it
gives diamond Si 306 points. Vertices that coincide in a particular cell are
merged, since bands.x writes no plot file for two equal consecutive points,
and a path that would turn back along the segment it came by is split into
two branches there. `k_path` records the branches (each vertex's
`label` and crystal coordinates `k`, and the `steps` between them),
`n_kpoints`, the points pw.x runs per spin channel, the table (`convention`,
`lattice_type`), the space group of the typed cell it was read on (for a
slab, its layer's primitive cell) and `primitive_cells`. A bundle's
`CITATIONS.md` cites the table. pw.x holds at most 40000 k-point/spin pairs,
so a path with more is refused (`k_path.too_many_kpoints`); only a
`k_path_distance` near its lower bound, 0.001 Å⁻¹, on a cell with lattice
vectors shorter than about 1.4 Å reaches that.

The phonon tasks' `dispersion` step follows the same path on the same
written cell, at the same `k_path_distance`, with the same notices, and
publishes it under the same name, `k_path`, as matdyn.x runs it (see
[the phonon tasks](#check-the-phonon-tasks)); pw.x's limit does not apply
there.

A band structure shows empty bands, so unless you set `nbnd` the bands step
computes three times the occupied bands (aiida-quantumespresso's
`bands.yaml`): the largest of int(3 nelec/e) and int(nelec/e) + 4, where e
is 1 for a noncollinear run and 2 otherwise, and pw.x's own default for the
run, which leaves room for a seeded moment (see
[magnetism](#check-magnetism-and-spin-orbit-coupling)). Primitive diamond
Si (8 electrons) gets 12 bands against its scf step's 4, 24 spinor bands
with spin-orbit coupling, and NiO's AFM-II cell (48 electrons) 72 per spin
channel. The `bands_nbnd` record names the protocol in `source_note`;
`steps.bands.nbnd` replaces the count and `extra_bands` adds to it. pw.x
checks no band count in a bands run, but Goldilocks keeps its floors there
(see [magnetism](#check-magnetism-and-spin-orbit-coupling)).

The bands step takes the scf step's occupations (`bands_occupations`, whose
warnings stay on the `occupations` record): a bands run only weights its
bands at the Fermi energy the scf found, so they do not change the bands. A
`tetrahedra_opt` scf is the exception: pw.x stops on tetrahedra without an
automatic k-point mesh, so the bands step is written with cold smearing at
0.01 Ry, and `bands_occupations` says why in `source_note`.
`occupations`, `smearing_type` and `degauss` set the scf step;
`steps.bands.occupations` is refused. `conv_thr` sets the bands step's
diagonalization threshold (see
[override precedence](conventions.md#override-precedence)); the SCF-loop
settings do not reach it.

Any `tot_magnetization` gives a collinear run two Fermi energies, which the
scf writes to its save and the bands step reads from there whatever its own
input says, and `bands.x` stops on them ("The bands code with constrained
magnetization has not been tested") after both pw.x steps have run. So the
band task's scf derives no `tot_magnetization = 0` for a compensated
magnetic ordering: a compensated antiferromagnetic non-metal, which the
other tasks run on fixed occupations with that 0, runs on smearing, and the
`occupations` record's `source_note` says why. A `tot_magnetization` you set
on a collinear band task is refused
(`occupations.bands_x_refuses_tot_magnetization`), with the remedy
`occupations=smearing` and `tot_magnetization` unset, and so is
`occupations=fixed` on a collinear spin-polarized band task, for want of a
moment, with the remedy `occupations=smearing`. A noncollinear run takes no
`tot_magnetization`.

`bands.x` runs once for each spin channel of a collinear spin-polarized run
(`bands_x_up.in` and `bands_x_down.in`, writing `bands_up.dat` and
`bands_down.dat`) and once otherwise (`bands_x.in`, writing `bands.dat`).
Each also writes a `.gnu` file of every band's energy in eV against the
distance along the path, for plotting; it draws the gap between two branches
as a segment when they lie at most five steps apart, so take the branch ends
from `k_path`. bands.x runs without its symmetry analysis
(`lsym=.false.`), which can stop it after it has written the bands; only its
`.rap` file of symmetry labels is lost. It runs on one task
(`srun --nodes=1 --ntasks=1`) in the walltime the two pw.x steps leave, and
passes when its output says `JOB DONE`. The bands step usually sizes the job
and takes most of its walltime: a few hundred points, twice that for a
collinear run, at three times the bands.

Both tables choose a path by lattice type, not by space group. In R3 and
R-3 with a rhombohedral angle below 90°, such as ilmenite FeTiO3, Setyawan
and Curtarolo's B, B_1, P, P_1, Q and X are general points of the zone
boundary, not points of special symmetry, and `k_path` carries the info
notice `k_path.non_special_vertices`. ASE's oblique loop encloses about a
third of the zone, and its corners H and H_1 are general points too. The
typing ignores the moments' directions, and the path assumes E(k) = E(-k),
which the moments of a spin-polarized run with spin-orbit coupling can
break: such a run gets the warning `k_path.magnetic_noncollinear_symmetry`.
Where the lattice is more symmetric than the crystal, as for a P1 or P-1
cell on an orthorhombic, monoclinic or hexagonal lattice, a monoclinic
crystal on an orthorhombic lattice or with two equal axes normal to its
unique axis, or a slightly distorted cubic crystal, several settings of the
table, or several equally short equivalents of a vertex, fit the lattice
alike, and which one the path takes can depend on the orientation and basis
of the uploaded cell. The labels can then move, and a segment can follow a
line that the crystal's symmetry does not relate to the line another
orientation gives: for P2_1/c ZrO2 with a = c, Γ-Y runs along c* in one
orientation and along a* in another. Every vertex is still a special point
on the zone boundary.

## Check the phonon tasks

The three phonon tasks compute phonons with density-functional perturbation
theory (DFPT; Baroni et al., Rev. Mod. Phys. 73, 515 (2001)), Quantum
ESPRESSO's ph.x, and from them the phonon density of states and the phonon
dispersion. They differ only in their first step, the pw.x run whose save
ph.x reads:

| Task              | Name in the task list        | First step | Geometry ph.x reads                      |
| ----------------- | ---------------------------- | ---------- | ---------------------------------------- |
| `phonon`          | Phonon (no relaxation)       | `scf`      | the written cell                         |
| `relax-phonon`    | Phonon (incl. relaxation)    | `relax`    | the written cell, with relaxed positions |
| `vc-relax-phonon` | Phonon (incl. vc-relaxation) | `vc-relax` | the relaxed cell and positions           |

Each task runs as one job on one prefix and outdir: the first step, then
`d3hess.x` under DFT-D3 (below); `ph.x` on a Γ-centred q-point mesh, which
writes one dynamical matrix per irreducible q-point (`pwscf.dyn1`,
`pwscf.dyn2`, ..., which `pwscf.dyn0` lists); `q2r.x`, which turns them into
interatomic force constants (`pwscf.fc`); `matdyn.x`, which interpolates the
force constants on a fine mesh into the phonon DOS (`pwscf.phdos`); and
`matdyn.x` again, which interpolates them along the band task's
high-symmetry path into the phonon dispersion (`pwscf.freq`, below). ph.x
reads a relaxation's save directly, without a separate scf. The first step
keeps its pw.x calculation, so everything this page says about an scf, a
relax or a vc-relax applies to it.

DFPT takes second derivatives of the energy at the geometry it is given, so
leftover forces shift the frequencies, soft modes most. `phonon` takes the
written geometry as it is, and its phonon record carries the info notice
`phonon.relax_first`: relax the structure first with the same settings,
`hubbard_projectors` included, and `forc_conv_thr` at most 1e-4 Ry/Bohr, or
use `relax-phonon` or `vc-relax-phonon`, which relax it in the same job, by
default to 1e-4 Ry/Bohr (see
[relaxation settings](#check-relaxation-settings)). The scf of `phonon`
prints the forces and the stress on the written geometry. In
`vc-relax-phonon` the q-mesh, the k-mesh and the dispersion path are
decided on the input cell: the meshes keep their divisions on the relaxed
cell, so their spacings change with it, and the path keeps its vertices'
crystal coordinates (see the dispersion, below). The vc-relax makes one
pass: no relaxation follows its final scf on the relaxed cell, so check the
forces and the stress that scf prints, and run the task again from the
relaxed structure if they are large (aiida-quantumespresso instead repeats
the vc-relax until the volume stops changing). Its phonon record carries the
info notice `phonon.vc_relax_input_cell`.

ph.x needs a q-point mesh that every symmetry operation pw.x keeps maps onto
itself. Unless you set one, the mesh comes from `q_distance`, 0.3 Å⁻¹ with 2π
included (aiida-quantumespresso's ph protocol, balanced; fast 0.6, stringent
0.2), on the written cell, as `k_distance` gives the k-mesh (see [k-point
spacing](conventions.md#k-point-spacing-and-shifts)): one division along each
vacuum axis, and the larger count on lattice vectors a symmetry operation
mixes. `q_grid` sets the mesh directly and wins over `q_distance`, with the
info notice `q_sampling.grid_and_distance_conflict` when both are given. The
`q_sampling` record holds the mesh, the spacing it came from, `n_irr_q`, the
irreducible q-points as ph.x counts them under pw.x's operations, and `work`,
ph.x's own estimate of its run in scf-equivalents: (3 nat + 1) nsym/nsymq
summed over the irreducible q-points, where nsymq of the nsym operations leave
the q-point unchanged up to a reciprocal lattice vector. The primitive cell of
diamond Si gets 7×7×7, 20 q-points and a work of 2401; alpha-U's primitive
cell 9×9×5, 75 and 2835; graphene 10×10×1, 14 and 700. Zincblende AlAs at
4×4×4 has 8 q-points and a work of 336, as in Quantum ESPRESSO's PHonon
example02.

A `q_grid` is refused (`phonon.q_grid_breaks_symmetry`, with the remedy of
unsetting it) when it has more than one division along a vacuum axis; when
some operation pw.x keeps does not map it onto itself, on which ph.x stops
with "q-mesh breaks symmetry", such as alpha-U's per-axis 9×8×5, since a
mirror turns a_2 into a_1 + a_2; and when it gives different counts to two
lattice vectors an operation mixes, even where ph.x would accept it.
Alpha-U's 4×8×4 passes ph.x's test, but a smearing run raises its k-mesh to
multiples of the q-mesh (below), and 17×17×9 would become 20×24×12, which
the mirror does not map onto itself; equal counts, such as 8×8×4, are kept.
q2r.x reads at most 1024 divisions along each axis and 1024 dynamical
matrices, one per irreducible q-point. A `q_grid` with an entry above 1024,
or with more than 49152 points, is refused as an invalid setting: an orbit
holds at most 48 q-points, so a mesh of more than 48 × 1024 points always
has more than 1024 irreducible ones. A mesh with more than 1024 irreducible
q-points is refused (`phonon.too_many_q_points`, with the remedy of
unsetting `q_grid` and `q_distance`): `q_distance` 0.1 gives alpha-U
26×26×13, with 1281 of them. A mesh built from a `q_distance` with more
than 49152 points, or more than 1024 divisions along an axis, is refused
without its q-points being counted, as for the 101×101×101 that 0.02 Å⁻¹
gives the primitive cell of Si.

A slab whose vacuum vector is not perpendicular to its periodic axes can
keep symmetry operations that turn the vacuum vector into one with an
in-plane component, which a mesh with a single division along the vacuum
axis can fail. When the mesh built from the spacing fails ph.x's test this
way, the `q_sampling` record is blocked, naming the vacuum axis: upload the
slab with its vacuum vector perpendicular to the periodic axes.

The first step's k-mesh comes from the usual tiers (see [k-point
sampling](#check-k-point-sampling)), and is then held against the q-mesh:
QRF95 predicts the spacing at which scf total energies converge to 1 meV/atom,
and DFPT converges better with two more things of k. With smearing or
`tetrahedra_opt`, each k-axis is raised to the next multiple of its q-axis, so
that every q-point is a difference of k-points, without which the phonons of a
metal converge very slowly in k (Quantum ESPRESSO's PHonon user guide). With
fixed occupations, each k-axis is raised to at least its q-axis, since a
q-mesh denser than the k-mesh can give spurious acoustic frequencies near Γ
(Petretto et al., Comput. Mater. Sci. 144, 331 (2018)). Both are convergence
defaults, not requirements of ph.x, which computes the k+q states of every q
itself and runs any pair of meshes; only EPW requires the k-mesh to be a
multiple of the q-mesh, in some of its modes. Set `k_grid`, `k_index` or
`k_distance` to use your own mesh: it is used as given, with a warning where
it is coarser than the q-mesh or, with smearing or tetrahedra, not a multiple
of it. QRF95's 12×12×12 for bcc Fe becomes 22×22×22 against its 11×11×11
q-mesh, and its 4×4×4 for rock-salt NaCl becomes 7×7×7. A raised `k_sampling`
record carries the info notice `phonon.k_mesh_raised` and names the raise in
`source_note`; it keeps the evidence and the shift of the tier that decided
the starting mesh, such as QRF95's prediction, and has no `k_distance`, since
no single spacing gives the raised mesh.

`n_irr_k`, `npool` and the job follow the raised mesh, and in the relaxation
tasks every ionic step runs on it. On 83 periodic structures of an end-to-end
test set, the raise is estimated to make a whole phonon run, the scf and ph.x,
cost a median 2.26 times as much as on the unraised mesh: 2.56 times with
smearing, 1.95 with fixed occupations. A `k_grid`, `k_index` or `k_distance`
you set is used as given, with the warning `phonon.k_grid_coarser_than_q`
where it is coarser than the q-mesh along an axis and, with smearing or
tetrahedra, `phonon.k_grid_not_commensurate` where it is not a multiple of it.
A run with smearing or tetrahedra on a structure that holds a lanthanide or an
actinide gets the info notice `phonon.lanthanide_actinide_k`: if it is a
metal, Nascimento et al. advise `k_distance` 0.10 Å⁻¹ for metals of that kind
(npj Comput. Mater. (2026), doi:10.1038/s41524-026-02097-8). The smearing is
the same as for the other tasks, cold at 0.01 Ry by default.

ph.x symmetrizes in real space and stops with "FFT grid incompatible with
symmetry" unless every operation pw.x keeps maps the dense FFT grid onto
itself, a test pw.x never runs. A rotation that mixes lattice vectors of
different lengths can fail it, as in a centred lattice written in its
primitive basis or an antiferromagnetic supercell: pw.x's own grid for
alpha-U's primitive cell at its default cutoffs, 40×45×64, is not mapped
onto itself by the mirror that turns a_2 into a_1 + a_2. Goldilocks
reproduces pw.x's grid and ph.x's test on the written cell (the `fft_grid`
record: `pw_grid`, `compatible`). Where ph.x would refuse pw.x's grid, the
first step writes `nr1`, `nr2` and `nr3` (`written`): of the grids ph.x
accepts that are at least pw.x's own along each axis, have no prime factor
above 5 and are multiples of the fractional translations' factors, the one
with the fewest points. Alpha-U gets 45×45×64, 1.12 times the points;
La2CuO4's primitive cell 120×120×120 for 64×64×120, 3.52 times; the
antiferromagnetic NiO cell 64×64×64 for 40×64×40, 2.56 times. pw.x uses
them as given, for the smooth grid too when `ecutrho` is 4 × `ecutwfc`,
keeps them through every ionic step of a fixed-cell relaxation and stores
them in the save ph.x reads. The record's `source_note` gives the ratio of
points; the job's memory estimate does not include the written grid yet,
since it sizes pw.x on its own.

A vc-relax's final scf drops `nr1`-`nr3` and rebuilds pw.x's own grid for
the relaxed cell, so `vc-relax-phonon` writes none. That grid passes ph.x's
test on every symmetric strain of a cell whose mixed lattice vectors are
pairs that some operation exchanges, with equal fractional-translation
factors. A cell with a mixed pair that is not such a pair is fragile
(`fft_grid.fragile`, with the pairs in `fragile_axes`): a strain can give
pw.x's own grid counts on which ph.x stops. The fragile cells include the
primitive cells of alpha-U, alpha-S and La2CuO4, a MnPS3 monolayer, and the
antiferromagnetic cells of Ni, NiO, MnO, Fe2O3 and UO2. `vc-relax-phonon`
is refused on a fragile cell (`phonon.vc_relax_fft_grid_unsupported`)
whether or not pw.x's grid passes on the input cell, since the MnPS3
monolayer's passes under some strains and fails under others, and with no
remedy, since no setting keeps `nr1`-`nr3` through the final scf. Use
`relax-phonon`, which relaxes the atoms in the written cell and keeps a grid
written for ph.x, or run the `vc-relax` task and then the `phonon` task on
the relaxed structure.

ph.x takes the DFT-D3 part of the dynamical matrices (see
[dispersion](#check-dispersion-and-dimensionality)) from a Hessian that
`d3hess.x` computes from the first step's save into `out/pwscf.hess`, so
under DFT-D3 the d3hess step runs before ph.x. d3hess.x builds that Hessian
from two-body terms only, while pw.x includes D3's three-body terms by
default, so the phonon tasks' first step writes `dftd3_threebody = .false.`:
the energy, the forces and any relaxation use the same two-body D3 as the
dynamical matrices. The phonon record carries the info notice
`phonon.d3_two_body`. The `relax` and `vc-relax` tasks keep the three-body
terms, so a geometry they relaxed is not at this equilibrium: relax with
`relax-phonon` or `vc-relax-phonon` instead. Quantum ESPRESSO 7.3's CMake
build does not build d3hess.x (its Makefile build and 7.5's CMake build do),
so check that your installation has it.

ph.x treats a run on smearing or tetrahedra as a metal. Only with fixed
occupations does it compute the high-frequency dielectric constant and the
Born effective charges at Γ, from which q2r.x and matdyn.x build the
long-range part of a polar insulator's force constants, which splits its LO
and TO modes (Quantum ESPRESSO 7.3 `PHonon/PH/prepare_q.f90`). And at q = 0
it shifts the Fermi energy by the charge each perturbation induces divided
by the density of states at the Fermi energy (`PHonon/PH/solve_linter.f90`,
`LR_Modules/efermi_shift.f90`), which with smearing is nearly zero when the
Fermi energy lies in a gap: a wurtzite ZnO `relax-phonon` run at the
defaults, on smearing, completed its relaxation, and then ph.x diverged at
its first q-point, Γ. Unless you confirm a metal, such an insulator can pass
for a metal: the classifier's threshold is set to catch 97% of metals (its
model card), for the k-point sampling a missed metal would undersample, so
it calls many insulators metals, among them SrTiO3, TiO2, ZnO, ThO2, La2O3,
LiCoO2, bulk MoS2, a CrI3 monolayer and Bi2Se3, and it scores correlated
oxides such as NiO, UO2, MnO and CeO2 high whatever the threshold; the
heuristic never says `non_metal`. So a phonon task whose first step runs on
smearing or `tetrahedra_opt` on a composition that is not all-metallic is
refused (`phonon.metallicity_unconfirmed`) until you set `is_metal=metal` or
the first step runs on fixed occupations. `is_metal=non_metal` passes only
where it puts the first step on fixed occupations (see
[occupations](#check-electronic-occupations)), so the refusal says why the
run is not on them, names what to set, and offers only remedies that resolve
it, with `is_metal=metal` for a metal in every case:

- Where fixed occupations can run, the insulator's remedy is
  `is_metal=non_metal`. If you set `occupations` yourself, `is_metal` does
  not change it, and the remedy is `occupations=fixed`.
- A collinear spin-polarized run takes fixed occupations only with an integer
  `tot_magnetization` of the electron count's parity, or the 0 of an
  antiferromagnetic ordering compensated by symmetry. A magnetic insulator
  without one needs its moment, which only you can give, so the message names
  `tot_magnetization` and no remedy sets it. For a material without magnetic
  moments the refusal also offers `is_magnetic=non_magnetic`, where that runs
  it without spin polarization on fixed occupations: not where your request
  or the LLM decides the spin polarization, nor where a Hubbard U acts on an
  odd d or f count, such as Mn2+ d5 in MnO or Cu2+ d9 in La2CuO4, which keeps
  the run spin-polarized (see
  [magnetism](#check-magnetism-and-spin-orbit-coupling)), nor where the
  electron count is odd. A U on an even count, such as NiO's Ni2+ d8 or
  LiCoO2's Co3+ d6, leaves that answer to decide. Ferromagnetic
  NiO and MnO at the default ordering, CrI3, EuO, GdI2, solid O2, and MoS2,
  WSe2 and PtSe2 monolayers, which the `is_magnetic` heuristic
  spin-polarizes, stay on smearing for this reason.
- Without spin polarization an odd electron count, such as TiN's or LaB6's,
  leaves a band half filled, as in a metal, which fixed occupations cannot
  describe; a magnetic insulator with one needs spin polarization and, on a
  collinear run, its moment.
- If you set `occupations=fixed` yourself on a run that cannot take them for
  one of these reasons, the same refusal replaces that of the occupations
  rules, whose remedy, smearing, needs `is_metal=metal` here: for a metal it
  offers `is_metal=metal` with `occupations=smearing`, and with your
  `tot_magnetization` unset, which ph.x refuses on smearing.

A run on fixed occupations, such as one the classifier calls a non-metal,
and an all-metallic composition need no answer, and the other tasks take the
classifier's answer as before.

A slab with `isolation='periodic'` and fixed occupations gets the warning
`phonon.slab_lo_to_needs_2d_truncation`: q2r.x and matdyn.x would build its
long-range term in the 3D form, which for a two-dimensional material depends
on the vacuum width. With `isolation='slab'` (see
[boundary conditions](#check-boundary-conditions-and-vacuum)) they write
`loto_2d` and take the 2D form (Sohier et al., Phys. Rev. B 96, 075448
(2017)).

ph.x computes phonons with a Hubbard U only with atomic projectors, so a
phonon task with +U needs `hubbard_projectors=atomic` (see
[Hubbard +U](#check-hubbard-u)) and is otherwise refused
(`phonon.hubbard_projectors_unsupported`, with the remedies
`hubbard_projectors=atomic` and `hubbard_needs_correlation=false`). Its
DFPT+U treats collinear spins only, so a U with spin-orbit coupling is
refused, with or without magnetic moments
(`phonon.noncollinear_hubbard_unsupported`, with the remedies
`spin_orbit_coupling=false` and no +U). Quantum ESPRESSO's PHonon examples
describe phonons with a Hubbard U, and those of magnetic systems with
spin-orbit coupling, as experimental, and such runs get the warnings
`phonon.hubbard_experimental` (Floris et al., Phys. Rev. B 101, 064305
(2020)) and `phonon.magnetic_noncollinear_experimental` (Urru and Dal Corso,
Phys. Rev. B 100, 045115 (2019)). A `tot_magnetization` on a collinear run
with smearing or tetrahedra gives the scf two Fermi energies, which ph.x
refuses, so it is refused too (`phonon.pinned_moment_with_smearing`), with
the remedy of unsetting it, or `occupations=fixed` for an integer moment of
the electron count's parity. With `occupations=fixed`, a moment that is not
an integer of that parity is refused as in the other tasks on an all-metallic
composition or with `is_metal=metal`, and the remedy, smearing, unsets it
too; otherwise the metallicity refusal above replaces it.

A molecule or cluster in a box, a written cell with vacuum along all three
lattice vectors, is refused with no remedy, whatever `isolation`
(`phonon.isolated_boundary_unsupported`). ph.x does not implement the
Martyna-Tuckerman correction of `isolation='isolated'`: Quantum ESPRESSO
7.3's ph.x drops it and computes a periodic array of copies, and 7.5's
applies it only in part. Under any other `isolation` ph.x computes such an
array by design, whose phonons include the interactions between the copies,
while a molecule has no phonon dispersion. A molecule's vibrations need a
Γ-only calculation with dynmat.x's `asr='zero-dim'`, which these tasks do
not set up. In `vc-relax-phonon` this refusal replaces those of a vc-relax on
an isolated system and of a 2D `cell_dofree` on a box, whose advice, the
`relax` task, would not help, and under `isolation='slab'` that of the 2D
truncation on such a cell, whose remedy, `isolation='periodic'`, is refused
here too. `fix_bottom_layers` is refused in the relaxation tasks (see
[relaxation settings](#check-relaxation-settings)), and the `vc-relax` task's
own rules apply to `vc-relax-phonon` unchanged.

ph.x converges its linear response to `tr2_ph` 1e-18, mixing with
`alpha_mix(1)` 0.4 over `nmix_ph` 8 iterations: aiida-quantumespresso's ph
protocol, balanced, whose fast and stringent `tr2_ph` are 1e-16 and 1e-20;
Quantum ESPRESSO's own defaults are 1e-12, 0.7 and 4. A value you set must
pass ph.x's own checks, `tr2_ph` > 0 and 0 ≤ `alpha_mix` ≤ 1, and `nmix_ph`
must be at least 1. ph.x runs on the whole allocation with the first step's
`-npool` and `-ndiag` and no images, always with `recover` on. q2r.x and
matdyn.x apply the acoustic sum rule `asr`, by default `simple`, which
corrects the on-site force constants and so shifts every q alike; set
`asr=crystal` for matdyn.x's optimized correction by projection. The largest
violation of the sum rule is usually the error of the exchange-correlation
term on the FFT grid (the egg-box effect), which is on-site and the same at
every q. The projection spreads its correction evenly over the force
constants of the q-mesh supercell, which in q-space is zero at every q-mesh
point but Γ, so it leaves that violation at every other computed q. On
bcc Li it gives the lowest Γ–N branch a minimum of −1.16 THz at the default
`ecutrho` and −0.74 THz at twice that, where `simple` gives no imaginary
modes at either and the two cutoffs agree within 0.0012 THz. With `crystal`,
then, a soft branch can turn imaginary, and raising `ecutrho` seems to change
it, although the dispersion is converged. q2r.x applies the same rule to the
effective charges only, where `simple` subtracts their mean, the correction
`crystal` gives a 3D crystal. q2r.x, matdyn.x and d3hess.x each run on one
task. matdyn.x
interpolates the phonon DOS on a Γ-centred mesh of `dos_q_distance`
0.10 Å⁻¹, the dos task's nscf spacing (aiida-quantumespresso's `pdos.yaml`),
built as the q-mesh is (the primitive cell of Si gets 21×21×21, graphene
30×30×1), with tetrahedra and every 1 cm⁻¹. It only interpolates, so a fine
mesh is cheap. `pwscf.phdos` lists the frequency in cm⁻¹, the total DOS and
each atom's projection.

The `dispersion` step runs matdyn.x again, on the same force constants with
the same `asr` and `loto_2d`, along the path the `band` task takes on the
same written cell (see
[the band structure path](#check-the-band-structure-path)): the same
vertices and labels, at the same `k_path_distance`, 0.025 Å⁻¹ unless you set
it, one setting for both tasks. `dispersion.in` lists the path after the
namelist as the band task's `K_POINTS crystal_b` rows, which matdyn.x, with
`q_in_band_form` and `q_in_cryst_coord`, expands as pw.x does, in the
reciprocal vectors of the cell the force constants belong to: the written
cell, or the relaxed one in `vc-relax-phonon`. matdyn.x reads a label as a
point only through `ibrav`, which is 0 for every written cell, so the labels
stay `! label` comments. The step's `k_path` record holds the path as
matdyn.x runs it, with the band path's notices, of which
`k_path.magnetic_noncollinear_symmetry` means here only that segments the
path treats as equivalent may differ: real force constants give
ω(q) = ω(-q) whatever the moments. A molecule or cluster in a box has no
dispersion: its `k_path` is unavailable, and the task is refused (above).

On fixed occupations, where ph.x computes the effective charges (above),
matdyn.x adds their non-analytic term, which splits the LO from the TO
modes, at every point of the path that is Γ, or another reciprocal lattice
vector, to within 1e-6, taking the direction of approach from the point
before, or from the point after for the path's first point and for a point
whose predecessor is exactly Γ (Quantum ESPRESSO 7.3
`PHonon/PH/matdyn.f90`). The splitting depends on that direction unless the
crystal is cubic, so on such a run each Γ inside a branch is listed twice,
with a count of 0 between, as matdyn.x's own documentation advises for
low-symmetry crystals: the first copy ends one branch with the direction it
arrives from, and the second starts the next with the direction it leaves
along. Γ at the start of the path takes the leaving direction already, and
Γ at its end, or before a jump, has only the arriving one. A run on smearing
or tetrahedra, which only a metal gets (above), has no effective charges, and
under `isolation='slab'` matdyn.x takes the 2D form of the term
(`loto_2d`), which vanishes at Γ, and does not test for Γ: both run the
band task's path unchanged. A slab with `isolation='periodic'` on fixed
occupations gets the 3D term, and Γ listed twice where its path passes
through Γ, as on a rectangular layer such as phosphorene (see
`phonon.slab_lo_to_needs_2d_truncation`, above).

matdyn.x reaches a vertex after n steps as x + (1/n · n)(y − x), with 1/n
rounded, which is exactly Γ only where 1/n · n rounds to exactly 1 in double
precision. After 49, 98, 103, 107, ... steps it stops about 1e-16 short of
Γ, at a point that still counts as Γ but where the long-range sum adds the
term a second time (`PHonon/PH/rigid.f90`), and from which a second copy
would take the arriving direction again. So on fixed occupations without
`loto_2d`, each segment into Γ takes the fewest steps, at least its own,
that land on Γ exactly: 49 becomes 50, and no count up to 4000 gains more
than 4. This relies on matdyn.x rounding as IEEE double precision does,
which a GNU build with Quantum ESPRESSO's default flags does; a build with
value-unsafe floating-point optimizations, such as Intel's default
floating-point model or `-ffast-math`, can still stop short of Γ. The
`k_path` record's `source_note` says when the path differs
from the band task's this way, and its `n_kpoints`, the points matdyn.x
computes, is then the band path's plus one per Γ listed twice and the steps
added: the primitive cell of MgO runs 392 points at the defaults, against
the band task's 391.

In `vc-relax-phonon` the path is built on the input cell, and matdyn.x
applies its crystal coordinates to the relaxed cell's reciprocal vectors.
Where the special points have fixed crystal coordinates, as in cubic, fcc,
bcc, tetragonal, orthorhombic and hexagonal cells, square, rectangular and
hexagonal layers, and wires, the vertices stay the same points. In BCT,
ORCF, ORCI, ORCC, RHL, MCL and MCLC cells and centred-rectangular and
oblique layers, the special points move with the axis ratios and angles, and
the vertices then lie off them: on the same end-to-end test set, with 12
antiferromagnetic orderings added, a 2% deviatoric strain moves them at
most 0.039 Å⁻¹, 1.6 steps at the default
spacing (antiferromagnetic CrO2's ORCC cell), and changes no cell's
subtype. A cell near a boundary between two of Setyawan and Curtarolo's
subtypes can still change subtype, and a triclinic path keeps its
time-reversal-invariant points, which the relaxed cell's table can name
differently. The
`phonon.vc_relax_input_cell` notice says so; for the relaxed cell's own
path, run the `vc-relax` task, then a phonon task on the relaxed structure.

A conventional cell or a supercell gives folded phonon branches, as it gives
folded bands (`k_path.folded_bands`). Where such a path reaches a reciprocal
lattice vector of the written cell other than Γ, matdyn.x counts that point
as Γ too, but it is not listed twice, since matdyn.x takes the leaving
direction only after a point that is exactly 0, and the long-range sum can
add the term there a second time: upload the primitive cell of a polar
insulator. Neither `asr` imposes the rotational sum rules, only the
translational ones, so the flexural (ZA) branch of a two-dimensional
material can dip below zero near Γ, which the closely spaced points of the
dispersion show and the phonon DOS mesh can miss.

matdyn.x writes the frequencies in cm⁻¹, negative where a mode is imaginary,
to `pwscf.freq`, in the format plotband.x reads, with each point's Cartesian
coordinates in units of 2π/alat, and to `pwscf.freq.gp`, one line per point:
the length along the path, jumps between branches included, then every
frequency; take the branch ends from `k_path`. It writes no modes (`flvec`
is blank), which would add 5 + 3 nat (nat + 1) lines per point. The `.freq`
header gives the number of points in four digits, so plotband.x cannot read
a path of 10000 points or more, which only a `k_path_distance` near its
lower bound reaches; `.freq.gp` has no such limit, and no such path is
refused. matdyn.x holds 96 nat² bytes per point of the path, which the job's
memory estimate leaves out: 61 MB for Nd2Fe14B's 68 atoms on its 138 points
at the default spacing, but 4.4 GB for 68 atoms at 9999 points, more than
one task's share of a SCARF node. The step runs last, so a dispersion that
does not fit fails the job after ph.x has finished: write `dispersion.in`
again with a larger `k_path_distance` and run that step alone (see
[submit and resume a phonon job](cli.md#submit-and-resume-a-phonon-job)).

No input of a phonon task carries `max_seconds`. The job record's
`max_seconds_by_step` is empty, and `timer_seconds`, 95% of the walltime,
is when the job timer of `submit.sh` creates `pwscf.EXIT` in the working
directory: pw.x and ph.x look for that file there first, delete it and stop
cleanly, so the relaxation takes the time it needs and ph.x the rest. The
script deletes a leftover `pwscf.EXIT` before the first step, since pw.x
would stop at once on it, and stops the timer when it ends. d3hess.x, q2r.x
and matdyn.x never look for the file: one created while they run stops the
next pw.x or ph.x step at once, or is deleted by the next job. A pw.x step
stopped there cannot resume, since Goldilocks writes no pw.x restart input,
and its message says to raise `walltime_h`.

ph.x saves its progress after every irreducible representation, and every
ph.in sets `recover`. `submit.sh` passes the ph step only when ph.x exited
with 0 and wrote a complete dynamical matrix for every q-point `pwscf.dyn0`
lists: its exit code alone says nothing, since ph.x stopped during the
non-scf calculation of a q-point exits with 0. Otherwise the script names
why it stopped and the q-points without a matrix, and prints the command
that resumes the job at the ph step (see
[submit and resume a phonon job](cli.md#submit-and-resume-a-phonon-job)).
The steps before it are skipped: rerunning the relaxation would rewrite the
save that ph.x's data belongs to, at a geometry equal to the first only
within the thresholds, and the dynamical matrices would mix two ground
states. For the same reason a job that starts at the first step deletes
`out/_ph0` and `pwscf.dyn*` first, ph.x's data from any earlier run, which
ph.x would otherwise resume from after checking only its flags and q-mesh.

ph.x's memory is not estimated. The job is sized on the first step's pw.x
estimate, as the job record's `source_note` says, and ph.x also holds arrays
that estimate leaves out, such as projections for each of its k-points, so
a large cell can need more memory than the job requests.

## Read the reasons and warnings

Every analysis fact and every advisor decision -- occupations, k-point
sampling, pseudopotential selection, and every other record in
`goldilocks explain`/`goldilocks.json` -- resolves to one of three states:
`resolved`, `unavailable`, or `blocked`. A resolved record carries a `source`
of `human`, `ml`, `llm`, or `heuristic`, in that priority order (highest
first); an unavailable record carries a `reason` instead of a value; a
blocked record carries `blocked_by`, naming the upstream fact that could not
be resolved. There is no separate "provenance block" distinct from structure
analysis -- both use this same shape.

A decision that applies several settings (the magnetic decision,
occupations, k-point sampling, Hubbard +U, convergence, relaxation, the
`dos.x` settings, and a phonon task's q-point mesh, ph.x, q2r.x and
phonon-DOS settings) also carries `field_sources`, one source per setting it
applied, keyed by the setting's override name: `human` (or `llm`) for a value
that tier set, otherwise the tier that chose it. The record's `source` is the
highest of them, so `mixing_beta=0.3` alone makes `convergence` `human` while
`field_sources` keeps `conv_thr` `heuristic`, and `spin_orbit_coupling=true`
makes `magnetic` `human` while spin polarization still reads `heuristic`. A
setting the decision did not apply has no entry and cannot make the record
`human`: a `degauss` under fixed occupations, a `smearing_type` on a `dos`
task's `tetrahedra_opt` nscf step, or a `magnetic_ordering` that an explicit
`spin_polarized=false` ignores. Hubbard's switch is keyed `needs_correlation`,
its override field, though `--set` calls it `hubbard_needs_correlation`, and
`hubbard_projectors` has an entry only when a U is applied. A
pinned `pseudo_table_id` makes `pseudo_table` `human`. The other records that
apply several settings (`cutoffs`, `job`, `nbnd`, `parallelisation`, `vdw`)
carry one `source` and no `field_sources`: their `human` means the request set
at least one of their settings.

A record whose own rule followed another record's answer keeps the tier that
applied the rule, `heuristic`, and names that record in `derived_from`:
`magnetic` names `is_magnetic` when that fact decided spin polarization (or
`hubbard` when a U on an odd d or f count did),
`occupations` and a heuristic `k_sampling` name `is_metal`, `hubbard` names
`needs_correlation` (or `functional` for a hybrid functional), an
automatically selected `pseudo_table` names `functional` and `magnetic`,
`relativistic` names `magnetic`, `pseudopotentials` names
`pseudo_table`, a `band` task's `k_path` names `magnetic`, whose cell
it reads, and its `bands_occupations` names `occupations`, the scf step's
decision it follows. A phonon task's `q_sampling` and `phonon_dos` name
`magnetic`, whose cell they mesh, `fft_grid` names `cutoffs` and `magnetic`,
`q2r` names `boundary`, whose isolation decides `loto_2d`, and the
dispersion step's `k_path` names `magnetic`, `occupations` and `q2r`, whose
occupations and `loto_2d` decide whether matdyn.x adds the non-analytic
term. A non-metal's
`occupations` also names the records that
decided whether fixed occupations can run: `magnetic`, and `electron_count`
where its parity was tested. An `occupations` that pins a `tot_magnetization`
names `magnetic` too, whichever tier chose the occupations (a requested
`occupations` reads `human` and still names it): the moment is the request
that record admitted, or the 0 of its compensated ordering, which also names
`electron_count`, since that 0 needs an even count. The upstream record's
`source` is not copied: `occupations`
reads `heuristic` even when the classifier decided `is_metal` (`ml`), and you
follow `derived_from` to find that. `human` only ever means a value set in the
request: a `dos` task's nscf protocol values (`nscf_k_sampling`'s k_distance,
`nscf_occupations`) read `heuristic`, with `source_note` naming the protocol,
and so do a `band` task's bands-step defaults (`bands_nbnd`, and
`k_path`'s `k_path_distance`) and a phonon task's protocol values: the
relaxation's `forc_conv_thr` 1e-4, `q_distance` 0.3, the ph.x settings,
`dos_q_distance` and the dispersion's `k_path_distance`. A `k_sampling` the
phonon rule raised keeps the source of
the tier that decided its starting mesh (`ml` for QRF95's `k_distance`), and
names the raise in `source_note`, though its `k_distance` is `null`. A phonon
task's `job` record names its job timer in `source_note`, and says there that
ph.x's memory is not estimated.
Per-decision warnings live inside that decision's own value (e.g.
`job.warnings`, `cutoffs.warnings`), and every run, whatever its task, also
carries one aggregated top-level `warnings` list: every record's warnings, in
record-name order, each naming the record it came from in `record`, then the
request's routing notices (a setting given without a step that reached several
steps), under the `record` `overrides`. A `dos` task's nscf step keeps its
own, under `nscf_`-prefixed records, and a `band` task's bands step under
`bands_`-prefixed ones and its path's under `k_path`: a notice on
`nscf_parallelisation` is about the nscf step's npool, not the scf step's.
A phonon task's steps have records of their own names (`q_sampling`,
`phonon`, `q2r`, `phonon_dos`, and the dispersion step's path under
`k_path`, as for the band task), so their warnings name those.

A resolved record also carries the rest of its provenance: `source_note`,
the advisor's rationale where it gives one (such as why a molecule gets a
Coulomb cutoff), and `citations`, what to cite for it. A record that a
machine-learning model decided, whole or in one setting (`source` or
`field_sources` `ml`: `is_metal`, `is_magnetic`, `k_sampling`'s
`k_distance`), names the model in `model`: `model_id` (goldilocks-ml's id and
feature contract, such as `metallicity.is_metal.cgcnn@crystal_graph.v1`),
`asset` (the installed release, such as `models/is-metal-classifier@1`),
`target_contract`, the model's own `value`, its `details` as returned (a
classifier's `score` and `threshold`, QRF95's `interval`) and its `warnings`.
Each model warning, such as the is_magnetic classifier's "has not been
externally validated", is also in the top-level `warnings` list as
`<record>.model_warning`. A bundle's `CITATIONS.md` and the manifest's
`citations` list every record's citations: the selected pseudopotential table,
every model that decided a record, the source of the path of a `band` task
or of a phonon task's dispersion for a bulk crystal or a slab, and, for a
phonon task, aiida-quantumespresso's
protocols (Huber et al., npj Comput. Mater. 7, 136 (2021)) where their
defaults are used and DFPT (Baroni et al.). `CITATIONS.md` also names the table's
licence file under `licences/`, which lists SSSP's per-family references. Read analysis and selection warnings
as well as advice; do not treat a `resolved` status as scientific validation.
