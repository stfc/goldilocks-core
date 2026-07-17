# Advise stage

Owner: `advice.py`

The Advise stage chooses scientific and numerical intent for each recommendation category, recording provenance for every choice. It makes intent-level decisions, not concrete k-point grid resolution.

## Input

- `StructureAnalysisRecord` (from Analyze)
- Optional `CalculationIntent`
- Optional `CalculationHints`

## Output

- `ParameterAdvice`

## Decision trees

Each advice category follows a precedence: **hint > analysis > default**.

### k-points

Advise produces `KPointAdvice`, not `KPointSelection`. The Kmesh stage consumes this advice and resolves the concrete grid.

1. If `hints.k_grid` is set → `KPointAdvice(explicit_grid=hint, provenance.source="user_hint")`. If `hints.k_spacing` is also set, emit a warning that explicit grid wins.
2. If `hints.k_spacing` is set → `KPointAdvice(spacing=hint, provenance.source="user_hint")`.
3. Otherwise → `KPointAdvice(spacing=0.2, provenance.source="default")`.

The default Kmesh backend converts the advice to a `KPointSelection`. A model-backed Kmesh backend may use the model instead when no k-point hint is set.

### Smearing

1. If coherent `hints.smearing_type` and `hints.smearing_width_ry` values are set → `SmearingAdvice` from hints, `provenance.source="user_hint"`. Fixed occupations use no width; the canonical `gaussian`, `mp`, and `cold` types require a finite positive width.
2. If `analysis.electronic_character` is `metal` or `likely_metal` → `SmearingAdvice(smearing_type="cold", width_ry=0.01, provenance.source="analysis")`. Warning: metallicity is inferred, not confirmed.
3. Otherwise → `SmearingAdvice(smearing_type="fixed", width_ry=None, provenance.source="default")`. Warning: verify smearing for metallic systems.

### Magnetism

1. If `hints.spin_polarized` is set → `MagnetismAdvice` from hint, `provenance.source="user_hint"`.
2. If `analysis.magnetic_elements` is non-empty → `MagnetismAdvice(spin_polarized=True, provenance.source="analysis")`.
3. Otherwise → `MagnetismAdvice(spin_polarized=False, provenance.source="default")`.

### Spin-orbit coupling

1. If `hints.spin_orbit_coupling` is set → `SpinOrbitAdvice(enabled=hint, consider=False, provenance.source="user_hint")`; the operator has already made the decision.
2. If `analysis.heavy_elements` is non-empty → `SpinOrbitAdvice(enabled=False, consider=True, provenance.source="analysis")`. Warning: SOC is not enabled automatically.
3. Otherwise → `SpinOrbitAdvice(enabled=False, consider=False, provenance.source="default")`.

SOC is never auto-enabled. See [conventions](../conventions.md) for the rationale.

### van der Waals dispersion

1. If `hints.use_vdw` is `True` → enable vdW with `hints.vdw_method`, or `d3bj` when no method is supplied. Record `provenance.source="user_hint"`.
2. If `hints.use_vdw` is `False` → disable vdW. A simultaneous method is rejected as contradictory when `CalculationHints` is constructed.
3. If `hints.use_vdw` is `None` and Analyze reports `has_vacuum=True` from its connectivity-derived low-dimensional/vacuum heuristic → enable vdW with `hints.vdw_method`, or `d3bj` by default. Record `provenance.source="analysis"`.
4. Otherwise → leave vdW off with `provenance.source="default"`. A method supplied without an enabling hint or low-dimensional analysis result is ignored with a provenance warning.

Supported code-agnostic method labels are `d3`, `d3bj`, `ts`, and `mbd`.

A dimensionality-analysis failure therefore remains transparent and conservative: Analyze reports `unknown` with a warning, and Advise does not infer low dimensionality or enable vdW.

The vdW/SOC asymmetry is intentional. A detected low-dimensional classification makes D3BJ a conservative package default because dispersion may be important for weak interlayer, surface, or intermolecular interactions; it does not establish that dispersion dominates. The operator can override the setting or method with `CalculationHints(use_vdw=..., vdw_method=...)`. Heavy elements only trigger SOC consideration because enabling SOC changes calculation cost, setup, and pseudopotential requirements.

### Pseudopotentials

`CalculationIntent` canonicalizes supported functional spellings at construction. `PBEsol`, `PBESOL`, `PBE-sol`, `PBE_SOL`, and `PBE sol` become `PBEsol`; unknown labels are preserved and are not treated as another functional.

1. `pseudo_mode`: `hints.pseudo_mode` if set, otherwise `intent.pseudo_mode`. Defaults to `"efficiency"`.
2. `relativistic_mode`: `hints.relativistic_mode` if set, otherwise `"full"` if SOC is enabled, otherwise `"scalar"`.
3. `pseudo_type`: `hints.pseudo_type` if set, otherwise `None` (accept any).
4. Provenance source is `"user_hint"` if any pseudo-related hint was provided, `"analysis"` if SOC changed the relativistic mode, otherwise `"default"`.
5. Warning emitted when heavy elements are present but SOC is not enabled (fully-relativistic pseudos may be needed later).

### Convergence

1. If any convergence hint is set (`conv_thr`, `mixing_beta`, `electron_maxstep`) → use provided values, fill gaps with defaults. `provenance.source="user_hint"`.

   **Important**: partial overrides use `or` logic. Setting `conv_thr=1e-8` without setting `mixing_beta` produces `conv_thr=1e-8, mixing_beta=0.4`. `CalculationHints` rejects zero or other invalid values at construction before this fallback logic runs.

2. Otherwise → all defaults. `provenance.source="default"`.

## Defaults

| Parameter | Default | Unit |
| --- | --- | --- |
| k_spacing | 0.2 | Å⁻¹ |
| conv_thr | 1e-6 | Ry |
| mixing_beta | 0.4 | — |
| electron_maxstep | 80 | — |
| smearing width (metallic) | 0.01 | Ry |

## Validation

`CalculationHints` raises `ValueError` at construction, before any Advise backend can receive invalid request values, when:

- `k_spacing` is non-finite or non-positive;
- `k_grid` does not contain exactly three positive integers;
- smearing type is unsupported, type and width are inconsistent, or an enabled width is non-finite or non-positive;
- `conv_thr` or `mixing_beta` is non-finite or non-positive;
- `electron_maxstep` is not a positive integer;
- `vdw_method` is not a supported label;
- `vdw_method` is supplied while `use_vdw=False`.

The advice records repeat the relevant output checks in their own constructors. This prevents invalid custom Advise backends from passing malformed values to Kmesh, Select, or Generate.

## Backend contract

A custom Advise backend must satisfy:

```python
AdviseStage = Callable[
    [StructureAnalysisRecord, CalculationIntent, CalculationHints],
    ParameterAdvice,
]
```

Advice should remain intent-level. Concrete k-point grids belong to Kmesh. Concrete target resources and target-specific numerical data belong to Select. Target-code text rendering belongs to Generate.

The current `width_ry`, `conv_thr`, pseudo-family, and SSSP-mode representation
is QE-oriented because only Quantum ESPRESSO SCF generation is implemented.
