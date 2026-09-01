"""Pseudopotential advice policy for the Advise stage."""

from __future__ import annotations

from goldilocks_core.advice._hints import has_hint
from goldilocks_core.contracts import (
    CalculationIntent,
    Provenance,
    PseudoHints,
    PseudopotentialAdvice,
    SpinOrbitAdvice,
)


def advise_pseudopotentials(
    intent: CalculationIntent,
    hints: PseudoHints,
    spin_orbit: SpinOrbitAdvice,
) -> PseudopotentialAdvice:
    pseudo_mode = hints.pseudo_mode or intent.pseudo_mode
    relativistic_mode = hints.relativistic_mode or (
        "full" if spin_orbit.enabled else "scalar"
    )
    source = "user_hint" if has_hint(hints) else "default"
    warnings: tuple[str, ...] = ()

    if spin_orbit.enabled and hints.relativistic_mode is None:
        source = spin_orbit.provenance.source
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
