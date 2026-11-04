# Quantum ESPRESSO SCF Template

Use this only after Goldilocks has already selected the scientific values. The generator should not invent missing pseudos, cutoffs, smearing, spin, SOC, or convergence settings.

```text
&CONTROL
  calculation = 'scf'
  prefix = '<prefix>'
  pseudo_dir = './pseudo'
  outdir = './out'
  tstress = .true.                    ! omit for isolation='isolated'
  tprnfor = .true.
/

&SYSTEM
  ibrav = 0
  nat = <site_count>
  ntyp = <species_count>
  ecutwfc = <cutoffs_ecutwfc_ry>
  ecutrho = <cutoffs_ecutrho_ry>
  occupations = '<fixed_or_smearing>'
  smearing = '<smearing_type>'        ! omit if fixed occupations
  degauss = <smearing_width_ry>       ! omit if fixed occupations
  nspin = 2                           ! only for collinear spin-polarized non-SOC
  tot_magnetization = <moment>        ! only with nspin = 2, when occupations pin one
  noncolin = .true.                   ! only when SOC/noncollinear is enabled
  lspinorb = .true.                   ! only when SOC is enabled
  angle1(<i>) = <polar_deg>           ! only for a magnetic SOC run, per species
  angle2(<i>) = <azimuth_deg>         ! only for a magnetic SOC run, per species
  assume_isolated = '<2D_or_martyna-tuckerman>'  ! '2D' for isolation='slab', 'martyna-tuckerman' for 'isolated'; omit for 'periodic'
/

&ELECTRONS
  conv_thr = <conv_thr>
  mixing_beta = <mixing_beta>
  electron_maxstep = <electron_maxstep>
/

ATOMIC_SPECIES
  <species_label>  <atomic_mass>  <selected_pseudo_filename>

CELL_PARAMETERS angstrom
  <a_x>  <a_y>  <a_z>
  <b_x>  <b_y>  <b_z>
  <c_x>  <c_y>  <c_z>

ATOMIC_POSITIONS crystal
  <species_label>  <f_x>  <f_y>  <f_z>

K_POINTS automatic
  <nk1>  <nk2>  <nk3>  <s1>  <s2>  <s3>
```

`<species_label>` is the QE species name: the real element (`Fe`), or the
element numbered (`Fe1`/`Fe2`) when its sites start with different
magnetizations -- an applied `magnetic_ordering`, or a
`starting_magnetization` giving them different values. The input is written
for the simulated cell (`advice.system.cell.value.structure`): the uploaded
structure, or the cell of the applied antiferromagnetic ordering, which can
hold a different number of atoms. Its site labels are already those species
(the uploaded file's own site labels are not kept). `write_qe_scf` (`generation/quantum_espresso/scf.py`) already
handles this distinction -- this template documents what it produces, it is
not something to reimplement by hand.

`CELL_PARAMETERS` holds the simulated cell's lattice vectors in the frame
where pw.x, which tests fixed Cartesian rotations only, keeps the most of the
cell's point group (a supercell, a slab with its vacuum along a or b, or a
sheet whose in-plane symmetry axes lie off x can keep less than all of it):
idealized to its space group, and turned rigidly (a cell without vacuum into
its standard orientation, a slab with its vacuum along c so that a lies along
x and a, b in the xy plane) or its origin moved when that is what it takes.
The lattice basis is kept, so `ATOMIC_POSITIONS` and the k-grid keep their
meaning; `advice.system.magnetic.value.frame` records the rotation and
shift. Copying the uploaded structure's own Cartesian lattice into the card
instead can hide symmetry from pw.x, which then runs more k-points than
`n_irr_k` counts.

## Mapping from Goldilocks records

```text
site_count          -> len(advice.system.cell.value.structure)  (the simulated cell)
species_count       -> len({site.label for site in advice.system.cell.value.structure})
k-grid              -> advice.step.kpoints.k_sampling.value.mesh
k-shift             -> advice.step.kpoints.k_sampling.value.shift
pseudos             -> advice.system.pseudo.metadata.value  (one entry per element)
ecutwfc / ecutrho   -> advice.system.cutoffs.value (max across elements; ecutrho is
                       charge_density_dual x ecutwfc where the table publishes none)
occupations         -> advice.step.kpoints.occupations.value
tot_magnetization   -> advice.step.kpoints.occupations.value.tot_magnetization  (None writes none)
spin / SOC          -> advice.system.magnetic.value, advice.system.pseudo.relativistic
moment direction    -> advice.system.magnetic.value.moment_direction (angle1/angle2)
convergence         -> advice.step.kpoints.convergence.value
assume_isolated     -> advice.system.boundary.value.isolation
warnings            -> advice.warnings()
```

## Minimal Python extraction pattern

```python
from pymatgen.core.periodic_table import Element

from goldilocks_core.examples.structures import structure
from goldilocks_core.inputs.hpc import load_hpc_profile
from goldilocks_core.inputs.structure import PathStructureSource, normalize_structure
from goldilocks_core.resolution import Resolved
from goldilocks_core.service import advise

source = PathStructureSource(structure("Si.cif"))
silicon = normalize_structure(source).structure
hpc = load_hpc_profile("scarf")

advice = advise(silicon, hpc=hpc)

pseudo_metadata = advice.system.pseudo.metadata
assert isinstance(pseudo_metadata, Resolved)
pseudo_by_element = {pseudo.element: pseudo for pseudo in pseudo_metadata.value}
elements = tuple(sorted(pseudo_by_element))

cutoffs = advice.system.cutoffs
assert isinstance(cutoffs, Resolved)
ecutwfc = cutoffs.value.ecutwfc_ry
ecutrho = cutoffs.value.ecutrho_ry

k_sampling = advice.step.kpoints.k_sampling
assert isinstance(k_sampling, Resolved)
grid = k_sampling.value.mesh
shift = k_sampling.value.shift

for element in elements:
    pseudo = pseudo_by_element[element]
    print(element, float(Element(element).atomic_mass), pseudo.filename)
```

`advice.system.pseudo.metadata` is `Unavailable`/`Blocked`, not `Resolved`,
if pseudopotential selection failed for any element -- check `.ok` (or use
`check(advice)`/`report.blocking`, see [workflows.md](workflows.md)) before
assuming a runnable input can be generated. Do not proceed to a runnable
input if any selected pseudopotential's `filename` is `None` or
`advice.system.cutoffs` is not `Resolved`. Take both cutoffs from that record:
a PseudoDojo file's own `cutoffs["ecutrho_ry"]` is `None`, because PseudoDojo
publishes no density cutoff, and the record carries the derived value with a
`cutoffs.ecutrho_derived_from_dual` notice.
