# Scientific conventions

This page records the physical and numerical conventions behind the
recommendations: units, defaults, and the policies that affect correctness.
For how each recommendation is produced and provenanced, see
[How recommendations are made](science.md).

## Units

| Quantity | Unit | Where it appears |
| --- | --- | --- |
| k-point spacing | Å⁻¹ | `CalculationHints.k_spacing` |
| Smearing width | Rydberg | advice `smearing.width_ry`, `CalculationHints.smearing_width_ry` |
| Wavefunction cutoff | Rydberg | selection `pseudopotentials[].ecutwfc_ry` |
| Charge-density cutoff | Rydberg | selection `pseudopotentials[].ecutrho_ry` |
| Convergence threshold | Rydberg | advice `convergence.conv_thr`, `CalculationHints.conv_thr` |
| Mixing beta | dimensionless | advice `convergence.mixing_beta`, `CalculationHints.mixing_beta` |

All cutoffs, smearing widths, and SCF energy thresholds follow the Quantum
ESPRESSO convention (Rydberg atomic units), not Hartree. Quantum ESPRESSO SCF
is the only implemented target code.

## K-point spacing convention

k-point spacing uses the **VASP KSPACING convention**:

- Spacing is in Å⁻¹.
- Mesh sizes come from solid-state reciprocal lattice lengths including the
  2π factor (`reciprocal_lattice.a`, `.b`, `.c` from pymatgen).
- The mesh in each direction is `max(1, ceil(recip_length / k_spacing))`.

This matches VASP's `KSPACING` tag. It differs from conventions that use
2π/a-style spacing without the 2π factor.

## Default values

| Parameter | Default | Unit | Defined in |
| --- | --- | --- | --- |
| convergence threshold | 1e-6 | Ry | `advice/convergence.py` |
| mixing beta | 0.4 | — | `advice/convergence.py` |
| electron max steps | 80 | — | `advice/convergence.py` |
| metallic smearing width | 0.01 | Ry | `advice/smearing.py` |
| smearing type (metallic) | `cold` | — | `advice/smearing.py` |
| smearing type (unknown character) | `fixed` | — | `advice/smearing.py` |
| pseudopotential accuracy | `efficiency` | — | `CalculationIntent.pseudo_accuracy` |
| functional | PBEsol | — | `CalculationIntent.functional` |

## Electronic character classification

The analysis stage classifies each structure as `metal` or `insulator` to
drive the smearing recommendation. With the default metallicity model asset
installed, an ordered structure is classified by the model, and the advice
provenance records `source: analysis` with the model's confidence. Without
that asset, or for a disordered structure the model cannot represent, the
core falls back to a conservative composition heuristic:

- **`likely_metal`**: all composition elements are metallic according to
  pymatgen. A warning records that this is not confirmed by
  electronic-structure data.
- **`unknown`**: composition alone cannot determine electronic character.
  The smearing advice falls back to fixed occupations and callers should
  verify manually.

The heuristic never returns `metal` or `insulator`; only the model does. See
[How recommendations are made](science.md) for when to distrust the model.

## Heavy elements and spin-orbit coupling

`contains_heavy_elements` and `heavy_elements` classify period-5-and-heavier
elements as heavy. Such elements can need SOC consideration.

SOC is **never enabled automatically**, even when heavy elements are present:

- the advice document sets `spin_orbit.consider = True` when heavy elements
  are detected;
- `spin_orbit.enabled` stays `False` unless you set
  `CalculationHints(spin_orbit_coupling=True)`.

SOC changes calculation cost, convergence, and pseudopotential requirements,
so the operator must enable it explicitly. Enabling SOC without an explicit
`CalculationHints.relativistic_mode` makes the pseudopotential requirements
demand fully relativistic (`full`) pseudopotentials with the same
`user_hint` provenance as the SOC decision.

A low-dimensional structure enables the lower-cost D3BJ dispersion correction
by default; the operator can override that choice.

## Pseudopotential relativistic modes

| Mode | Meaning |
| --- | --- |
| `scalar` | Scalar relativistic (default for non-SOC calculations) |
| `full` | Fully relativistic (required when SOC is enabled) |
| `non-relativistic` | No relativistic treatment (rarely used) |

See [Pseudopotential tables](pseudopotentials.md) for which registered tables
provide fully relativistic files.