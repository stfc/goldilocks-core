# Scientific conventions

This document records the physical and numerical conventions used by goldilocks-core. These are the invisible choices that affect correctness but are easy to overlook.

## Units

| Quantity | Unit | Where used |
| --- | --- | --- |
| k-point spacing | Å⁻¹ | `CalculationHints.k_spacing`, `KPointAdvice.spacing` |
| Smearing width | Rydberg | `CalculationHints.smearing_width_ry`, `SmearingAdvice.width_ry` |
| Wavefunction cutoff | Rydberg | `PseudopotentialSelection.ecutwfc_ry` |
| Charge-density cutoff | Rydberg | `PseudopotentialSelection.ecutrho_ry` |
| Convergence threshold | Rydberg | `CalculationHints.conv_thr`, `ConvergenceAdvice.conv_thr` |
| Mixing beta | dimensionless | `CalculationHints.mixing_beta`, `ConvergenceAdvice.mixing_beta` |

All current cutoffs, smearing widths, and SCF energy thresholds follow the Quantum ESPRESSO convention (Rydberg atomic units), not Hartree. These fields are current QE coupling, not a target-neutral unit policy. A second target must keep target-native units and semantically target-specific controls inside typed adapter selections; shared physical quantities must use documented canonical or explicit unit-bearing values. See [target-code adapters](target-code-adapters.md).

## K-point spacing convention

goldilocks-core uses the **VASP KSPACING convention** for k-point spacing:

- Spacing is in units of Å⁻¹ (inverse angstroms).
- Mesh sizes are computed from **solid-state reciprocal lattice lengths** that include the 2π factor: `reciprocal_lattice.a`, `.b`, `.c` from pymatgen.
- The mesh for each direction is `max(1, ceil(recip_length / k_spacing))`.

This is the same convention as VASP's `KSPACING` tag. It differs from some codes that use 2π/a-style spacing without the 2π factor in the reciprocal lattice vector.

## Default values

| Parameter | Default | Unit | Where defined |
| --- | --- | --- | --- |
| k-point spacing | 0.2 | Å⁻¹ | `advice.py` `DEFAULT_K_SPACING` |
| convergence threshold | 1e-6 | Ry | `advice.py` `DEFAULT_CONV_THR` |
| mixing beta | 0.4 | — | `advice.py` `DEFAULT_MIXING_BETA` |
| electron max steps | 80 | — | `advice.py` `DEFAULT_ELECTRON_MAXSTEP` |
| metallic smearing width | 0.01 | Ry | `advice.py` `METALLIC_SMEARING_WIDTH_RY` |
| smearing type (metallic) | cold | — | `advice.py` |
| smearing type (unknown) | fixed | — | `advice.py` |
| pseudo mode | efficiency | — | `CalculationIntent.pseudo_mode` |
| functional | PBE | — | `CalculationIntent.functional` |

## Heavy-element heuristic

`contains_heavy_elements` and `heavy_elements` use a **period-5-and-heavier** heuristic: any element with `row >= 5` in pymatgen's periodic table is considered heavy.

This replaced the earlier heuristic of `Z >= 57` (lanthanum onwards). The period-5 criterion is broader and catches elements like iodine (Z=53, period 5) that are relevant for SOC considerations even though they aren't lanthanides.

## Electronic character classification

The electronic character heuristic is intentionally conservative:

- **`likely_metal`**: all composition elements are metallic according to pymatgen. This is a structure-only heuristic; the character is "likely" because metallicity depends on electronic structure, not just composition. A warning always accompanies this classification.
- **`unknown`**: composition includes non-metallic elements, or the classification is ambiguous. Callers should verify manually.

The heuristic never returns `metal` or `insulator` — those require electronic-structure data that Core does not have.

## Spin-orbit coupling policy

SOC is **never enabled automatically**, even when heavy elements are present. Instead:

- `SpinOrbitAdvice.consider` is set to `True` when heavy elements are detected.
- `SpinOrbitAdvice.enabled` remains `False` unless the operator explicitly sets `CalculationHints(spin_orbit_coupling=True)`.

Rationale: enabling SOC significantly changes calculation cost, convergence behavior, and pseudopotential requirements. The operator must make an informed decision.

This differs intentionally from the vdW policy: a connectivity-derived low-dimensional classification makes D3BJ a conservative package default because dispersion may be important to weak interlayer, surface, and intermolecular interactions and the correction adds relatively little setup and cost. It does not establish that dispersion dominates; the operator can override the setting or method with `CalculationHints(use_vdw=..., vdw_method=...)`. Heavy elements only trigger SOC consideration because SOC has broader cost and setup consequences.

## Pseudopotential relativistic modes

| Mode | Meaning |
| --- | --- |
| `scalar` | Scalar relativistic (default for non-SOC calculations) |
| `full` | Fully relativistic (required when SOC is enabled) |
| `non-relativistic` | No relativistic treatment (rarely used) |

When `SpinOrbitAdvice.enabled` is `True` but `CalculationHints.relativistic_mode` is not set, the Advise stage automatically sets `PseudopotentialAdvice.relativistic_mode` to `"full"` and records `analysis` provenance.