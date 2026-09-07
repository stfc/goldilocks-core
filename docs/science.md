# Check your recommendations

Goldilocks suggests starting inputs for a Quantum ESPRESSO self-consistent-field
(SCF) calculation. It does not establish that your energy, forces, or other
properties are converged. Review the choices below before running a calculation,
then test the settings against the accuracy your work needs.

For a first calculation, use the [quickstart](quickstart.md). For exact units,
defaults, and override precedence, see [Scientific conventions](conventions.md).

## Check electronic occupations

Smearing smooths electron occupations near the Fermi energy to help metals
converge. Goldilocks chooses smearing from `electronic_character`:

| Classification            | Default occupations                 |
| ------------------------- | ----------------------------------- |
| `metal` or `likely_metal` | Cold smearing                       |
| `insulator` or `unknown`  | Fixed occupations, without smearing |

With the metallicity model installed, ordered structures receive a `metal` or
`insulator` prediction. Without that asset, or for disordered structures, a
composition rule returns `likely_metal` if every element is metallic according
to pymatgen, and `unknown` otherwise. Neither rule determines a band structure.

Check `electronic_character_source`, `electronic_character_confidence`, and
`analysis_warnings` in the analysis result. A model prediction or an all-metal
composition can still give the wrong occupation choice for your system. Override
it with `smearing_type`; when enabling smearing, also supply
`smearing_width_ry`. Test the width together with the k-point mesh.

## Check k-point sampling

K-points sample the Brillouin zone for reciprocal-space integration. Too sparse
a mesh can leave energies, forces, or electronic properties unconverged.

Without a grid or spacing hint, the default quantile random forest model
(`qrf-kpoints@QRF95`) predicts a spacing and interval from structure features.
The median spacing determines the mesh. The reported `confidence` is the
configured prediction-interval level, not a probability that your calculation
will be accurate.

Compare results on denser meshes. For slabs, wires, or molecules in periodic
cells, check sampling along vacuum directions explicitly; dimensionality advice
does not by itself set those mesh components to one. Use `k_grid` or `k_spacing`
to replace the model recommendation. These hints bypass the k-point model, not
necessarily the separate metallicity classifier used for analysis.

## Check pseudopotentials and cutoffs

A pseudopotential replaces the core-electron potential with an effective
potential for the valence electrons. Check that its functional, valence
configuration, and relativistic treatment suit your system.

Goldilocks selects files and cutoff metadata, not system-specific convergence
limits. Quantum ESPRESSO receives the largest wavefunction cutoff and largest
charge-density cutoff among the selected elements. An `efficiency` or
`precision` table is a library choice, not proof that your target property is
converged. Test both cutoffs. See [Pseudopotential tables](pseudopotentials.md)
for selection rules, installation, and custom files.

## Check magnetism and spin-orbit coupling

Spin polarization allows different spin populations. Goldilocks enables it by
default when transition metals, lanthanides, or actinides are present. This is
an element-based heuristic, not a prediction of magnetic order. The generated
input does not assign starting magnetic moments or magnetic sublattices; review
and complete the magnetic setup for your calculation. Override the heuristic
with `spin_polarized`.

Spin-orbit coupling (SOC) couples electron spin to orbital motion. Goldilocks
flags period-5-and-heavier elements for consideration but does not enable SOC
unless you request it. Whether SOC matters depends on the property, not only the
elements. Enabling it changes the required pseudopotentials and the QE spin
settings. See [relativistic modes](conventions.md#relativistic-modes) and the
[table restrictions](pseudopotentials.md#choose-a-table).

## Check dispersion and dimensionality

Dispersion accounts for long-range interactions that common semilocal
functionals can miss. The default D3BJ correction is the D3 method with
Becke–Johnson damping. Goldilocks enables it for structures classified as 0D,
1D, or 2D, and disables it for 3D or unknown dimensionality.

The classification uses a bond-connectivity analysis from pymatgen's
CrystalNN/Larsen methods. It is a heuristic, not a test of whether a dispersion
correction is physically appropriate. Check the structure and choose `use_vdw`
and `vdw_method` accordingly, including for molecular crystals classified as 3D.
Disordered structures get unknown dimensionality and a warning. A
CrystalNN/Larsen failure on an ordered structure raises an error rather than
silently choosing a dimensionality.

## Check SCF convergence

The SCF threshold, density-mixing strength, and iteration limit are package
defaults, not model predictions. Inspect the actual QE convergence history and
adjust these settings if needed. Reaching the SCF threshold does not demonstrate
convergence with respect to k-points or cutoffs.

## Read the reasons and warnings

Parameter advice, k-point selection, and individual pseudopotential selections
include `provenance`: a source, reason, and optional asset identity, confidence,
details, or warnings. Sources include `default`, `analysis`, `model`, `lookup`,
`user_hint`, and `fallback`. Structure analysis uses its own source and warning
fields instead of a single provenance block.

Provenance describes a decision or group of settings, not necessarily each field
separately. For example, overriding one convergence setting marks the whole
convergence group `user_hint`; the remaining values are still defaults. Model
confidence is not copied into every downstream advice block, and asset
identities are not always populated. Read analysis and selection warnings as
well as advice; do not treat the presence of provenance as scientific
validation.
