"""Spin-orbit coupling advice policy for the Advise stage."""

from __future__ import annotations

from goldilocks_core.contracts import (
    CalculationHints,
    Provenance,
    SpinOrbitAdvice,
    StructureAnalysisRecord,
)


def advise_spin_orbit(
    analysis: StructureAnalysisRecord,
    hints: CalculationHints,
) -> SpinOrbitAdvice:
    if hints.spin_orbit_coupling is not None:
        return SpinOrbitAdvice(
            enabled=hints.spin_orbit_coupling,
            consider=False,
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
