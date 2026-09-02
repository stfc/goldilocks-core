from __future__ import annotations

from dataclasses import dataclass

from goldilocks_core.analysis import StructureAnalysisRecord
from goldilocks_core.calculation import SpinHints
from goldilocks_core.provenance import Provenance


@dataclass(frozen=True, slots=True)
class SpinOrbitAdvice:
    enabled: bool
    consider: bool
    heavy_elements: tuple[str, ...]
    provenance: Provenance


def advise_spin_orbit(
    analysis: StructureAnalysisRecord,
    hints: SpinHints,
) -> SpinOrbitAdvice:
    """SOC is never auto-enabled. Heavy elements set ``consider=True``;
    the operator must set ``spin_orbit_coupling=True`` to enable it."""
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
