from __future__ import annotations

from goldilocks_core.advice.convergence import advise_convergence
from goldilocks_core.advice.magnetism import advise_magnetism
from goldilocks_core.advice.pseudo import advise_pseudopotential_requirements
from goldilocks_core.advice.smearing import advise_smearing
from goldilocks_core.advice.soc import advise_spin_orbit
from goldilocks_core.advice.vdw import advise_vdw
from goldilocks_core.calculation import CalculationHints, CalculationIntent
from goldilocks_core.types import JsonDict


class ParameterAdvice:
    """Marker for the parameter-advice record; the value is a dict.

    Keys: smearing, magnetism, spin_orbit, pseudopotential_requirements,
    convergence, vdw — each holding that concern's fields plus
    ``provenance``.
    """


def advise_parameters(
    analysis: JsonDict,
    intent: CalculationIntent | None = None,
    hints: CalculationHints | None = None,
) -> JsonDict:
    intent = intent or CalculationIntent()
    hints = hints or CalculationHints()

    spin_orbit = advise_spin_orbit(analysis, hints)

    return {
        "smearing": advise_smearing(analysis, hints),
        "magnetism": advise_magnetism(analysis, hints),
        "spin_orbit": spin_orbit,
        "pseudopotential_requirements": advise_pseudopotential_requirements(
            intent, hints, spin_orbit
        ),
        "convergence": advise_convergence(hints),
        "vdw": advise_vdw(analysis, hints),
    }


__all__ = ["ParameterAdvice", "advise_parameters"]
