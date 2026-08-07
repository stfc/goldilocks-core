"""Pseudopotential advice policy for the Advise stage."""

from __future__ import annotations

from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    Provenance,
    PseudopotentialAdvice,
    SpinOrbitAdvice,
)


def advise_pseudopotentials(
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
