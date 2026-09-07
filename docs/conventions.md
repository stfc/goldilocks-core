# Scientific conventions

Use this reference for units, defaults, and override rules. For what to check
before trusting a recommendation, see [Check your recommendations](science.md).

## Units

| Quantity                  | Unit          | Field                                           |
| ------------------------- | ------------- | ----------------------------------------------- |
| k-point spacing           | Å⁻¹           | `CalculationHints.k_spacing`                    |
| Smearing width            | Rydberg (Ry)  | `smearing_width_ry`; advice `smearing.width_ry` |
| Wavefunction cutoff       | Ry            | selection `pseudopotentials[].ecutwfc_ry`       |
| Charge-density cutoff     | Ry            | selection `pseudopotentials[].ecutrho_ry`       |
| SCF convergence threshold | Ry            | `conv_thr`; advice `convergence.conv_thr`       |
| Density-mixing strength   | Dimensionless | `mixing_beta`                                   |
| SCF iteration limit       | Integer       | `electron_maxstep`                              |

Energies use Quantum ESPRESSO's Rydberg convention, not Hartree: 1 Ha = 2 Ry.
The SCF threshold controls the estimated self-consistency error; it is not a
k-point or cutoff convergence tolerance.

## K-point spacing and shifts

Spacing uses solid-state reciprocal lattice vectors, including the 2π factor, as
in VASP `KSPACING`. For each reciprocal vector `b_i`, the grid size is:

```text
N_i = max(1, ceil(round(|b_i| / k_spacing, 5)))
```

Rounding to five decimal places avoids numerical noise at integer boundaries. A
smaller spacing gives a denser mesh. The built-in spacing and grid paths and
default model use shift `[0, 0, 0]`. In Quantum ESPRESSO's `K_POINTS automatic`
convention this includes Γ (the reciprocal-space origin), even for even-sized
meshes; a shift flag of `1` means a half-grid shift on that axis.

## Defaults

| Setting                                  | Default                            |
| ---------------------------------------- | ---------------------------------- |
| Target                                   | Quantum ESPRESSO, SCF single point |
| Exchange-correlation functional          | `PBEsol`                           |
| Pseudopotential accuracy tier            | `efficiency`                       |
| SCF threshold / mixing / iteration limit | `1e-6` Ry / `0.4` / `80`           |
| Metallic or likely-metallic occupations  | `cold`, width `0.01` Ry            |
| Insulating or unknown occupations        | `fixed`, no width                  |

Spin, dispersion, and electronic-character heuristics are described in
[Check your recommendations](science.md). Pseudopotential compatibility
exceptions belong to the [table guide](pseudopotentials.md#choose-a-table).

## Override precedence

Fields below are on `CalculationHints` unless stated otherwise. `None` leaves
the choice to Goldilocks.

- `k_grid` wins over `k_spacing`; either bypasses the k-point model.
- A non-fixed `smearing_type` requires a positive `smearing_width_ry`. Fixed
  occupations require no width. A smearing override replaces the pair.
- `conv_thr`, `mixing_beta`, and `electron_maxstep` override independently;
  unspecified values retain their defaults.
- `pseudo_accuracy` overrides `CalculationIntent.pseudo_accuracy`. The
  functional comes from `CalculationIntent.functional`.
- `spin_polarized` and `spin_orbit_coupling` override their respective advice.
- `use_vdw` explicitly enables or disables dispersion. `vdw_method` alone
  changes the method only if dispersion is otherwise enabled; it does not enable
  dispersion for a 3D or unknown structure. Enabled dispersion defaults to
  `d3bj` if no method is given.
- On `CalculationDraft`, `pseudo_table`, `pseudo_root`, and `pseudo_metadata`
  are mutually exclusive. An explicit table must match the request; selecting a
  table does not change the requested functional or accuracy tier.

## Relativistic modes

| `relativistic_mode` | Meaning                                           |
| ------------------- | ------------------------------------------------- |
| `scalar`            | Scalar relativistic effects, without explicit SOC |
| `full`              | Fully relativistic data, needed for explicit SOC  |
| `non-relativistic`  | No relativistic treatment                         |

Without an explicit mode, Goldilocks requests `full` when SOC is enabled and
`scalar` otherwise. An explicit mode takes precedence: keep it consistent with
the SOC setting. Fully relativistic files alone do not enable SOC. With SOC
enabled, QE generation writes `noncolin = .true.` and `lspinorb = .true.`;
otherwise spin-polarized advice produces `nspin = 2`.
