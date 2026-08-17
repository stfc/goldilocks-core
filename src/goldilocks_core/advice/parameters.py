from __future__ import annotations

from goldilocks_core.advice.convergence import advise_convergence
from goldilocks_core.advice.magnetism import advise_magnetism
from goldilocks_core.advice.pseudo import advise_pseudopotential_requirements
from goldilocks_core.advice.smearing import advise_smearing
from goldilocks_core.advice.soc import advise_spin_orbit
from goldilocks_core.advice.vdw import advise_vdw
from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    ParameterAdvice,
    StructureAnalysisRecord,
)


def advise_parameters(
    analysis: StructureAnalysisRecord,
    intent: CalculationIntent | None = None,
    hints: CalculationHints | None = None,
) -> ParameterAdvice:
    intent = intent or CalculationIntent()
    hints = hints or CalculationHints()

    spin_orbit = advise_spin_orbit(analysis, hints.spin)

    return ParameterAdvice(
        smearing=advise_smearing(analysis, hints.smearing),
        magnetism=advise_magnetism(analysis, hints.spin),
        spin_orbit=spin_orbit,
        pseudopotential_requirements=advise_pseudopotential_requirements(
            intent, hints.pseudo, spin_orbit
        ),
        convergence=advise_convergence(hints.convergence),
        vdw=advise_vdw(analysis, hints.vdw),
    )


__all__ = ["advise_parameters"]
