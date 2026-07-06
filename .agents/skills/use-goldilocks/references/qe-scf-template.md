# Quantum ESPRESSO SCF Template

Use this only after Goldilocks has already selected the scientific values. The generator should not invent missing pseudos, cutoffs, smearing, spin, SOC, or convergence settings.

```text
&CONTROL
  calculation = 'scf'
  prefix = '<prefix>'
  pseudo_dir = './pseudo'
  outdir = './out'
  tstress = .true.
  tprnfor = .true.
/

&SYSTEM
  ibrav = 0
  nat = <site_count>
  ntyp = <element_count>
  ecutwfc = <max_selected_ecutwfc_ry>
  ecutrho = <max_selected_ecutrho_ry>
  occupations = '<fixed_or_smearing>'
  smearing = '<smearing_type>'        ! omit if fixed occupations
  degauss = <smearing_width_ry>       ! omit if fixed occupations
  nspin = 2                           ! only for collinear spin-polarized non-SOC
  noncolin = .true.                   ! only when SOC/noncollinear is enabled
  lspinorb = .true.                   ! only when SOC is enabled
/

&ELECTRONS
  conv_thr = <conv_thr>
  mixing_beta = <mixing_beta>
  electron_maxstep = <electron_maxstep>
/

ATOMIC_SPECIES
  <Element>  <atomic_mass>  <selected_pseudo_filename>

CELL_PARAMETERS angstrom
  <a_x>  <a_y>  <a_z>
  <b_x>  <b_y>  <b_z>
  <c_x>  <c_y>  <c_z>

ATOMIC_POSITIONS crystal
  <Element>  <f_x>  <f_y>  <f_z>

K_POINTS automatic
  <nk1>  <nk2>  <nk3>  <s1>  <s2>  <s3>
```

## Mapping from Goldilocks records

```text
site_count          -> len(structure)
element_count       -> len(structure.composition.elements)
k-grid              -> result.selection.k_points.grid
k-shift             -> result.selection.k_points.shift
pseudos             -> result.selection.pseudopotentials
ecutwfc / ecutrho   -> max selected cutoffs across elements
smearing/degauss    -> result.advice.smearing
spin flags          -> result.advice.magnetism and result.advice.spin_orbit
convergence         -> result.advice.convergence
warnings            -> result.warnings
```

## Minimal Python extraction pattern

```python
from pymatgen.core import Structure
from pymatgen.core.periodic_table import Element

structure = Structure.from_file('structure.cif')
result = recommend(...)

pseudo_by_element = {
    pseudo.element: pseudo for pseudo in result.selection.pseudopotentials
}
elements = tuple(sorted(element.symbol for element in structure.composition.elements))
ecutwfc = max(pseudo.ecutwfc_ry or 0.0 for pseudo in pseudo_by_element.values())
ecutrho = max(pseudo.ecutrho_ry or 0.0 for pseudo in pseudo_by_element.values())
grid = result.selection.k_points.grid
shift = result.selection.k_points.shift

for element in elements:
    pseudo = pseudo_by_element[element]
    print(element, float(Element(element).atomic_mass), pseudo.filename)
```

Do not proceed to a runnable input if any selected pseudopotential has `filename`, `ecutwfc_ry`, or `ecutrho_ry` set to `None`.
