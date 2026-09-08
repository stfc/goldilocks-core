from __future__ import annotations

from typing import TypedDict

from goldilocks_core.advice.soc import SpinOrbitAdvice
from goldilocks_core.calculation import CalculationHints, CalculationIntent
from goldilocks_core.provenance import Provenance
from goldilocks_core.types import PseudoAccuracy, PseudoType, RelativisticTreatment


class PseudopotentialRequirements(TypedDict):
    functional: str
    accuracy: PseudoAccuracy
    pseudo_type: PseudoType | None
    relativistic: RelativisticTreatment
    provenance: Provenance


def advise_pseudopotential_requirements(
    intent: CalculationIntent,
    hints: CalculationHints,
    spin_orbit: SpinOrbitAdvice,
) -> PseudopotentialRequirements:
    accuracy = hints.pseudo_accuracy or intent.pseudo_accuracy
    relativistic = hints.relativistic_mode or (
        "full" if spin_orbit["enabled"] else "scalar"
    )
    hinted = (
        hints.pseudo_accuracy is not None
        or hints.pseudo_type is not None
        or hints.relativistic_mode is not None
    )
    source = "user_hint" if hinted else "default"
    warnings: tuple[str, ...] = ()

    if spin_orbit["enabled"] and hints.relativistic_mode is None:
        source = spin_orbit["provenance"].source
    elif spin_orbit["consider"] and not spin_orbit["enabled"]:
        warnings = (
            "Heavy elements are present; fully-relativistic pseudos may be needed "
            "if SOC is enabled.",
        )

    return {
        "functional": intent.functional,
        "accuracy": accuracy,
        "pseudo_type": hints.pseudo_type,
        "relativistic": relativistic,
        "provenance": Provenance(
            source=source,
            reason=(
                "Derive pseudopotential requirements from calculation intent, "
                "operator hints, and spin-orbit policy."
            ),
            warnings=warnings,
        ),
    }
