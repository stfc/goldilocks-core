from __future__ import annotations

from goldilocks_core.calculation import CalculationHints
from goldilocks_core.provenance import Provenance
from goldilocks_core.types import JsonDict


def advise_spin_orbit(
    analysis: JsonDict,
    hints: CalculationHints,
) -> JsonDict:
    """SOC is never auto-enabled. Heavy elements set ``consider=True``;
    the operator must set ``spin_orbit_coupling=True`` to enable it."""
    if hints.spin_orbit_coupling is not None:
        return {
            "enabled": hints.spin_orbit_coupling,
            "consider": False,
            "heavy_elements": analysis["heavy_elements"],
            "provenance": Provenance(
                source="user_hint",
                reason="Use the operator-provided SOC setting.",
            ),
        }

    if analysis["heavy_elements"]:
        return {
            "enabled": False,
            "consider": True,
            "heavy_elements": analysis["heavy_elements"],
            "provenance": Provenance(
                source="analysis",
                reason="Period-5-or-heavier elements make SOC worth considering.",
                warnings=(
                    "SOC is not enabled automatically because it changes cost "
                    "and setup.",
                ),
            ),
        }

    return {
        "enabled": False,
        "consider": False,
        "heavy_elements": [],
        "provenance": Provenance(
            source="default",
            reason="No period-5-or-heavier elements were detected.",
        ),
    }
