from __future__ import annotations

from dataclasses import dataclass

from goldilocks_core.advice.convergence import ConvergenceAdvice, advise_convergence
from goldilocks_core.advice.magnetism import MagnetismAdvice, advise_magnetism
from goldilocks_core.advice.pseudo import (
    PseudopotentialRequirements,
    advise_pseudopotential_requirements,
)
from goldilocks_core.advice.smearing import SmearingAdvice, advise_smearing
from goldilocks_core.advice.soc import SpinOrbitAdvice, advise_spin_orbit
from goldilocks_core.advice.vdw import VdwAdvice, advise_vdw
from goldilocks_core.analysis import StructureAnalysisRecord
from goldilocks_core.calculation import CalculationHints, CalculationIntent


@dataclass(frozen=True, slots=True)
class ParameterAdvice:
    smearing: SmearingAdvice
    magnetism: MagnetismAdvice
    spin_orbit: SpinOrbitAdvice
    pseudopotential_requirements: PseudopotentialRequirements
    convergence: ConvergenceAdvice
    vdw: VdwAdvice


def advise_parameters(
    analysis: StructureAnalysisRecord,
    intent: CalculationIntent | None = None,
    hints: CalculationHints | None = None,
) -> ParameterAdvice:
    intent = intent or CalculationIntent()
    hints = hints or CalculationHints()

    spin_orbit = advise_spin_orbit(analysis, hints)

    return ParameterAdvice(
        smearing=advise_smearing(analysis, hints),
        magnetism=advise_magnetism(analysis, hints),
        spin_orbit=spin_orbit,
        pseudopotential_requirements=advise_pseudopotential_requirements(
            intent, hints, spin_orbit
        ),
        convergence=advise_convergence(hints),
        vdw=advise_vdw(analysis, hints),
    )


__all__ = ["ParameterAdvice", "advise_parameters"]
