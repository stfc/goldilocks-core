# Scientific conventions

This document records the physical and numerical conventions used by goldilocks-core. These are the invisible choices that affect correctness but are easy to overlook.

## Units

| Quantity | Unit | Where used |
| --- | --- | --- |
| k-point spacing | Å⁻¹ | `CalculationHints.k_spacing` |
| Smearing width | Rydberg | `CalculationHints.smearing_width_ry`, `SmearingAdvice.width_ry` |
| Wavefunction cutoff | Rydberg | `PseudopotentialSelection.ecutwfc_ry` |
| Charge-density cutoff | Rydberg | `PseudopotentialSelection.ecutrho_ry` |
| Convergence threshold | Rydberg | `CalculationHints.conv_thr`, `ConvergenceAdvice.conv_thr` |
| Mixing beta | dimensionless | `CalculationHints.mixing_beta`, `ConvergenceAdvice.mixing_beta` |

All current cutoffs, smearing widths, and SCF energy thresholds follow the
Quantum ESPRESSO convention (Rydberg atomic units), not Hartree. Only Quantum
ESPRESSO SCF generation is currently implemented.

## K-point spacing convention

goldilocks-core uses the **VASP KSPACING convention** for k-point spacing:

- Spacing is in units of Å⁻¹ (inverse angstroms).
- Mesh sizes are computed from **solid-state reciprocal lattice lengths** that include the 2π factor: `reciprocal_lattice.a`, `.b`, `.c` from pymatgen.
- The mesh for each direction is `max(1, ceil(recip_length / k_spacing))`.

This is the same convention as VASP's `KSPACING` tag. It differs from some codes that use 2π/a-style spacing without the 2π factor in the reciprocal lattice vector.

## Default values

| Parameter | Default | Unit | Where defined |
| --- | --- | --- | --- |
| convergence threshold | 1e-6 | Ry | `advice/convergence.py` `DEFAULT_CONV_THR` |
| mixing beta | 0.4 | — | `advice/convergence.py` `DEFAULT_MIXING_BETA` |
| electron max steps | 80 | — | `advice/convergence.py` `DEFAULT_ELECTRON_MAXSTEP` |
| metallic smearing width | 0.01 | Ry | `advice/smearing.py` `METALLIC_SMEARING_WIDTH_RY` |
| smearing type (metallic) | cold | — | `advice/smearing.py` |
| smearing type (unknown) | fixed | — | `advice/smearing.py` |
| pseudo mode | efficiency | — | `CalculationIntent.pseudo_mode` |
| functional | PBEsol | — | `CalculationIntent.functional` |

## Heavy-element heuristic

`contains_heavy_elements` and `heavy_elements` classify period-5-and-heavier
elements as heavy. This includes elements such as iodine that can need SOC
consideration.

## Electronic character classification

Runtime uses the installed metallicity classifier for ordered structures and
records `model` provenance, confidence, and either `metal` or `insulator`.
Without that asset, or for a disordered structure the model cannot represent,
Core falls back to a conservative composition heuristic:

- **`likely_metal`**: all composition elements are metallic according to
  pymatgen. A warning records that this is not confirmed by electronic-structure
  data.
- **`unknown`**: composition alone cannot determine electronic character.
  Callers should verify manually.

The heuristic never returns `metal` or `insulator`; only the model does.

## Spin-orbit coupling policy

SOC is **never enabled automatically**, even when heavy elements are present. Instead:

- `SpinOrbitAdvice.consider` is set to `True` when heavy elements are detected.
- `SpinOrbitAdvice.enabled` remains `False` unless the operator explicitly sets `CalculationHints(spin_orbit_coupling=True)`.

SOC changes calculation cost, convergence, and pseudopotential requirements.
The operator must enable it explicitly. A low-dimensional structure can enable
the lower-cost D3BJ dispersion correction by default; the operator can override
that choice.

## Pseudopotential relativistic modes

| Mode | Meaning |
| --- | --- |
| `scalar` | Scalar relativistic (default for non-SOC calculations) |
| `full` | Fully relativistic (required when SOC is enabled) |
| `non-relativistic` | No relativistic treatment (rarely used) |

When `SpinOrbitAdvice.enabled` is `True` but `CalculationHints.relativistic_mode` is not set, the Advise stage automatically sets `PseudopotentialAdvice.relativistic_mode` to `"full"` and inherits the SOC decision's `user_hint` provenance.