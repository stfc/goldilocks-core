"""Advise-stage parameter recommendations for the Core pipeline."""

from __future__ import annotations

from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    ConvergenceAdvice,
    KPointAdvice,
    MagnetismAdvice,
    ParameterAdvice,
    Provenance,
    PseudopotentialAdvice,
    SmearingAdvice,
    SpinOrbitAdvice,
    StructureAnalysisRecord,
)

DEFAULT_K_SPACING = 0.2
DEFAULT_CONV_THR = 1e-6
DEFAULT_MIXING_BETA = 0.4
DEFAULT_ELECTRON_MAXSTEP = 80
METALLIC_SMEARING_WIDTH_RY = 0.01


def advise_parameters(
    analysis: StructureAnalysisRecord,
    intent: CalculationIntent | None = None,
    hints: CalculationHints | None = None,
) -> ParameterAdvice:
    """Return complete parameter advice with provenance for each choice."""
    intent = intent or CalculationIntent()
    hints = hints or CalculationHints()
    _validate_hints(hints)

    spin_orbit = _advise_spin_orbit(analysis, hints)

    return ParameterAdvice(
        k_points=_advise_k_points(hints),
        smearing=_advise_smearing(analysis, hints),
        magnetism=_advise_magnetism(analysis, hints),
        spin_orbit=spin_orbit,
        pseudopotentials=_advise_pseudopotentials(intent, hints, spin_orbit),
        convergence=_advise_convergence(hints),
    )


def _advise_k_points(hints: CalculationHints) -> KPointAdvice:
    warnings: tuple[str, ...] = ()
    if hints.k_grid is not None:
        if hints.k_spacing is not None:
            warnings = ("Both k_grid and k_spacing were provided; explicit grid wins.",)
        return KPointAdvice(
            spacing=None,
            explicit_grid=hints.k_grid,
            mesh_type="monkhorst-pack",
            provenance=Provenance(
                source="user_hint",
                reason="Use the operator-provided explicit k-point grid.",
                warnings=warnings,
            ),
        )

    if hints.k_spacing is not None:
        return KPointAdvice(
            spacing=hints.k_spacing,
            explicit_grid=None,
            mesh_type="monkhorst-pack",
            provenance=Provenance(
                source="user_hint",
                reason="Use the operator-provided VASP-style k-point spacing.",
            ),
        )

    return KPointAdvice(
        spacing=DEFAULT_K_SPACING,
        explicit_grid=None,
        mesh_type="monkhorst-pack",
        provenance=Provenance(
            source="default",
            reason="Use the default VASP-style k-point spacing.",
        ),
    )


def _advise_smearing(
    analysis: StructureAnalysisRecord,
    hints: CalculationHints,
) -> SmearingAdvice:
    if hints.smearing_type is not None or hints.smearing_width_ry is not None:
        return SmearingAdvice(
            smearing_type=hints.smearing_type,
            width_ry=hints.smearing_width_ry,
            provenance=Provenance(
                source="user_hint",
                reason="Use operator-provided smearing settings.",
            ),
        )

    if analysis.electronic_character in {"metal", "likely_metal"}:
        return SmearingAdvice(
            smearing_type="cold",
            width_ry=METALLIC_SMEARING_WIDTH_RY,
            provenance=Provenance(
                source="analysis",
                reason="Likely metallic composition benefits from modest smearing.",
                warnings=(
                    "Metallicity is inferred from structure-only heuristics; verify "
                    "against electronic-structure data.",
                ),
            ),
        )

    return SmearingAdvice(
        smearing_type="fixed",
        width_ry=None,
        provenance=Provenance(
            source="default",
            reason="Metallicity is unknown; use fixed occupations by default.",
            warnings=("Verify smearing manually for likely metallic systems.",),
        ),
    )


def _advise_magnetism(
    analysis: StructureAnalysisRecord,
    hints: CalculationHints,
) -> MagnetismAdvice:
    if hints.spin_polarized is not None:
        return MagnetismAdvice(
            spin_polarized=hints.spin_polarized,
            magnetic_elements=analysis.magnetic_elements,
            provenance=Provenance(
                source="user_hint",
                reason="Use the operator-provided spin-polarization setting.",
            ),
        )

    if analysis.magnetic_elements:
        return MagnetismAdvice(
            spin_polarized=True,
            magnetic_elements=analysis.magnetic_elements,
            provenance=Provenance(
                source="analysis",
                reason="Magnetic candidate elements are present in the structure.",
            ),
        )

    return MagnetismAdvice(
        spin_polarized=False,
        magnetic_elements=(),
        provenance=Provenance(
            source="default",
            reason="No magnetic candidate elements were detected.",
        ),
    )


def _advise_spin_orbit(
    analysis: StructureAnalysisRecord,
    hints: CalculationHints,
) -> SpinOrbitAdvice:
    if hints.spin_orbit_coupling is not None:
        return SpinOrbitAdvice(
            enabled=hints.spin_orbit_coupling,
            consider=hints.spin_orbit_coupling,
            heavy_elements=analysis.heavy_elements,
            provenance=Provenance(
                source="user_hint",
                reason="Use the operator-provided SOC setting.",
            ),
        )

    if analysis.heavy_elements:
        return SpinOrbitAdvice(
            enabled=False,
            consider=True,
            heavy_elements=analysis.heavy_elements,
            provenance=Provenance(
                source="analysis",
                reason="Period-5-or-heavier elements make SOC worth considering.",
                warnings=(
                    "SOC is not enabled automatically because it changes cost "
                    "and setup.",
                ),
            ),
        )

    return SpinOrbitAdvice(
        enabled=False,
        consider=False,
        heavy_elements=(),
        provenance=Provenance(
            source="default",
            reason="No period-5-or-heavier elements were detected.",
        ),
    )


def _advise_pseudopotentials(
    intent: CalculationIntent,
    hints: CalculationHints,
    spin_orbit: SpinOrbitAdvice,
) -> PseudopotentialAdvice:
    pseudo_mode = hints.pseudo_mode or intent.pseudo_mode
    relativistic_mode = hints.relativistic_mode or (
        "full" if spin_orbit.enabled else "scalar"
    )
    source = "user_hint" if _has_pseudo_hint(hints) else "default"
    warnings: tuple[str, ...] = ()

    if spin_orbit.enabled and hints.relativistic_mode is None:
        source = "analysis"
    elif spin_orbit.consider and not spin_orbit.enabled:
        warnings = (
            "Heavy elements are present; fully-relativistic pseudos may be needed "
            "if SOC is enabled.",
        )

    return PseudopotentialAdvice(
        functional=intent.functional,
        pseudo_mode=pseudo_mode,
        pseudo_type=hints.pseudo_type,
        relativistic_mode=relativistic_mode,
        provenance=Provenance(
            source=source,
            reason="Resolve pseudopotential intent from calculation intent and hints.",
            warnings=warnings,
        ),
    )


def _advise_convergence(hints: CalculationHints) -> ConvergenceAdvice:
    """Return SCF convergence advice with user hints applied."""
    if _has_convergence_hint(hints):
        return ConvergenceAdvice(
            conv_thr=hints.conv_thr or DEFAULT_CONV_THR,
            mixing_beta=hints.mixing_beta or DEFAULT_MIXING_BETA,
            electron_maxstep=hints.electron_maxstep or DEFAULT_ELECTRON_MAXSTEP,
            provenance=Provenance(
                source="user_hint",
                reason="Use operator-provided convergence settings where supplied.",
            ),
        )

    return ConvergenceAdvice(
        conv_thr=DEFAULT_CONV_THR,
        mixing_beta=DEFAULT_MIXING_BETA,
        electron_maxstep=DEFAULT_ELECTRON_MAXSTEP,
        provenance=Provenance(
            source="default",
            reason="Use package default SCF convergence settings.",
        ),
    )


def _has_convergence_hint(hints: CalculationHints) -> bool:
    """Return whether any convergence-specific hint was provided."""
    return any(
        hint is not None
        for hint in (hints.conv_thr, hints.mixing_beta, hints.electron_maxstep)
    )


def _has_pseudo_hint(hints: CalculationHints) -> bool:
    """Return whether any pseudopotential-specific hint was provided."""
    return any(
        hint is not None
        for hint in (hints.pseudo_mode, hints.pseudo_type, hints.relativistic_mode)
    )


def _validate_hints(hints: CalculationHints) -> None:
    """Validate hints before they become provenance-backed advice."""
    if hints.k_spacing is not None and hints.k_spacing <= 0:
        raise ValueError("k_spacing must be positive when provided")

    if hints.k_grid is not None and any(value < 1 for value in hints.k_grid):
        raise ValueError("k_grid values must be positive integers")

    if hints.smearing_width_ry is not None and hints.smearing_width_ry < 0:
        raise ValueError("smearing_width_ry must be non-negative when provided")

    if hints.conv_thr is not None and hints.conv_thr <= 0:
        raise ValueError("conv_thr must be positive when provided")

    if hints.mixing_beta is not None and hints.mixing_beta <= 0:
        raise ValueError("mixing_beta must be positive when provided")

    if hints.electron_maxstep is not None and hints.electron_maxstep < 1:
        raise ValueError("electron_maxstep must be positive when provided")
