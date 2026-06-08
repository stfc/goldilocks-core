"""Advise-stage parameter recommendations for the Core pipeline."""

from __future__ import annotations

from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    ConvergenceAdvice,
    KPointAdviceRecord,
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
        smearing=_advise_smearing(hints),
        magnetism=_advise_magnetism(analysis, hints),
        spin_orbit=spin_orbit,
        pseudopotentials=_advise_pseudopotentials(intent, hints, spin_orbit),
        convergence=ConvergenceAdvice(
            conv_thr=DEFAULT_CONV_THR,
            provenance=Provenance(
                source="default",
                reason="Use the package default SCF convergence threshold.",
            ),
        ),
    )


def _advise_k_points(hints: CalculationHints) -> KPointAdviceRecord:
    warnings: tuple[str, ...] = ()
    if hints.k_grid is not None:
        if hints.k_spacing is not None:
            warnings = ("Both k_grid and k_spacing were provided; explicit grid wins.",)
        return KPointAdviceRecord(
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
        return KPointAdviceRecord(
            spacing=hints.k_spacing,
            explicit_grid=None,
            mesh_type="monkhorst-pack",
            provenance=Provenance(
                source="user_hint",
                reason="Use the operator-provided VASP-style k-point spacing.",
            ),
        )

    return KPointAdviceRecord(
        spacing=DEFAULT_K_SPACING,
        explicit_grid=None,
        mesh_type="monkhorst-pack",
        provenance=Provenance(
            source="default",
            reason="Use the default VASP-style k-point spacing.",
        ),
    )


def _advise_smearing(hints: CalculationHints) -> SmearingAdvice:
    if hints.smearing_type is not None or hints.smearing_width_ry is not None:
        return SmearingAdvice(
            smearing_type=hints.smearing_type,
            width_ry=hints.smearing_width_ry,
            provenance=Provenance(
                source="user_hint",
                reason="Use operator-provided smearing settings.",
            ),
        )

    return SmearingAdvice(
        smearing_type="fixed",
        width_ry=None,
        provenance=Provenance(
            source="default",
            reason="Metallicity is not inferred yet; use fixed occupations by default.",
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
