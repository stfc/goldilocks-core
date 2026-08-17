from __future__ import annotations

from goldilocks_core.advice._hints import has_hint
from goldilocks_core.contracts import (
    CalculationIntent,
    Provenance,
    PseudoHints,
    PseudopotentialRequirements,
    SpinOrbitAdvice,
)


def advise_pseudopotential_requirements(
    intent: CalculationIntent,
    hints: PseudoHints,
    spin_orbit: SpinOrbitAdvice,
) -> PseudopotentialRequirements:
    accuracy = hints.accuracy or intent.pseudo_accuracy
    relativistic = hints.relativistic_mode or (
        "full" if spin_orbit.enabled else "scalar"
    )
    source = "user_hint" if has_hint(hints) else "default"
    warnings: tuple[str, ...] = ()

    if spin_orbit.enabled and hints.relativistic_mode is None:
        source = "analysis"
    elif spin_orbit.consider and not spin_orbit.enabled:
        warnings = (
            "Heavy elements are present; fully-relativistic pseudos may be needed "
            "if SOC is enabled.",
        )

    return PseudopotentialRequirements(
        functional=intent.functional,
        accuracy=accuracy,
        pseudo_type=hints.pseudo_type,
        relativistic=relativistic,
        provenance=Provenance(
            source=source,
            reason=(
                "Derive pseudopotential requirements from calculation intent, "
                "operator hints, and spin-orbit policy."
            ),
            warnings=warnings,
        ),
    )
