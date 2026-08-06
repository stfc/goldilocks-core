"""Advice-stage parameter recommendation policies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from goldilocks_core.advice.convergence import advise_convergence
from goldilocks_core.advice.kpoints import advise_k_points
from goldilocks_core.advice.magnetism import advise_magnetism
from goldilocks_core.advice.pseudo import advise_pseudopotentials
from goldilocks_core.advice.smearing import advise_smearing
from goldilocks_core.advice.soc import advise_spin_orbit
from goldilocks_core.advice.vdw import advise_vdw
from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    ConvergenceAdvice,
    KPointAdvice,
    MagnetismAdvice,
    ParameterAdvice,
    PseudopotentialAdvice,
    SmearingAdvice,
    SpinOrbitAdvice,
    StructureAnalysisRecord,
    VdwAdvice,
)

KPointsPolicy = Callable[[CalculationHints], KPointAdvice]
"""K-point advice policy signature."""

SmearingPolicy = Callable[[StructureAnalysisRecord, CalculationHints], SmearingAdvice]
"""Smearing advice policy signature."""

MagnetismPolicy = Callable[[StructureAnalysisRecord, CalculationHints], MagnetismAdvice]
"""Magnetism advice policy signature."""

SpinOrbitPolicy = Callable[[StructureAnalysisRecord, CalculationHints], SpinOrbitAdvice]
"""Spin-orbit coupling advice policy signature."""

PseudoPolicy = Callable[
    [CalculationIntent, CalculationHints, SpinOrbitAdvice], PseudopotentialAdvice
]
"""Pseudopotential advice policy signature."""

ConvergencePolicy = Callable[[CalculationHints], ConvergenceAdvice]
"""Convergence advice policy signature."""

VdwPolicy = Callable[[StructureAnalysisRecord, CalculationHints], VdwAdvice]
"""Van der Waals advice policy signature."""


@dataclass(frozen=True, slots=True)
class AdvicePolicies:
    """Composable advice policy backends.

    Construct with no arguments for the built-in Core advice policies;
    override any field to swap that policy backend. Policies are plain
    callables with the policy signature — no base class, no registry.

    Attributes:
        k_points: K-point advice policy.
        smearing: Smearing advice policy.
        magnetism: Magnetism advice policy.
        spin_orbit: Spin-orbit coupling advice policy.
        pseudopotentials: Pseudopotential advice policy.
        convergence: Convergence advice policy.
        vdw: Van der Waals dispersion advice policy.
    """

    k_points: KPointsPolicy = advise_k_points
    smearing: SmearingPolicy = advise_smearing
    magnetism: MagnetismPolicy = advise_magnetism
    spin_orbit: SpinOrbitPolicy = advise_spin_orbit
    pseudopotentials: PseudoPolicy = advise_pseudopotentials
    convergence: ConvergencePolicy = advise_convergence
    vdw: VdwPolicy = advise_vdw


def advise_parameters(
    analysis: StructureAnalysisRecord,
    intent: CalculationIntent | None = None,
    hints: CalculationHints | None = None,
    *,
    policies: AdvicePolicies | None = None,
) -> ParameterAdvice:
    """Return complete parameter advice with provenance for each choice.

    Args:
        analysis: Structure facts produced by the Analyze stage.
        intent: Calculation intent such as target code, task, functional, and
            pseudopotential mode. Defaults to ``CalculationIntent()``.
        hints: Optional operator overrides for k-points, smearing, magnetism,
            SOC, pseudopotentials, convergence, and van der Waals.
        policies: Optional advice policy composition. When omitted,
            ``AdvicePolicies()`` uses the built-in Core advice policies.

    Returns:
        A ``ParameterAdvice`` record containing k-point, smearing, magnetism,
        SOC, pseudopotential, convergence, and van der Waals advice.
    """
    intent = intent or CalculationIntent()
    hints = hints or CalculationHints()
    policies = policies or AdvicePolicies()

    spin_orbit = policies.spin_orbit(analysis, hints)

    return ParameterAdvice(
        k_points=policies.k_points(hints),
        smearing=policies.smearing(analysis, hints),
        magnetism=policies.magnetism(analysis, hints),
        spin_orbit=spin_orbit,
        pseudopotentials=policies.pseudopotentials(intent, hints, spin_orbit),
        convergence=policies.convergence(hints),
        vdw=policies.vdw(analysis, hints),
    )


__all__ = [
    "AdvicePolicies",
    "ConvergencePolicy",
    "KPointsPolicy",
    "MagnetismPolicy",
    "PseudoPolicy",
    "SmearingPolicy",
    "SpinOrbitPolicy",
    "VdwPolicy",
    "advise_parameters",
]
