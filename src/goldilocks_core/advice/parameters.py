"""Parameter recommendation policy combining all individual advice stages."""

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
    """Return complete parameter advice with provenance for each choice.

    Args:
        analysis: Structure facts produced by the Analyze stage.
        intent: Calculation intent such as target code, task, functional, and
            pseudopotential accuracy. Defaults to ``CalculationIntent()``.
        hints: Optional operator overrides for smearing, magnetism, SOC,
            pseudopotential requirements, convergence, and van der Waals.

    Returns:
        Parameter advice plus pseudopotential selection requirements.
    """
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
