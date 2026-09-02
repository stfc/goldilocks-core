from __future__ import annotations

from goldilocks_core.calculation import CalculationHints
from goldilocks_core.provenance import Provenance
from goldilocks_core.types import JsonDict


def advise_magnetism(
    analysis: JsonDict,
    hints: CalculationHints,
) -> JsonDict:
    if hints.spin_polarized is not None:
        return {
            "spin_polarized": hints.spin_polarized,
            "magnetic_elements": analysis["magnetic_elements"],
            "provenance": Provenance(
                source="user_hint",
                reason="Use the operator-provided spin-polarization setting.",
            ),
        }

    if analysis["magnetic_elements"]:
        return {
            "spin_polarized": True,
            "magnetic_elements": analysis["magnetic_elements"],
            "provenance": Provenance(
                source="analysis",
                reason="Magnetic candidate elements are present in the structure.",
            ),
        }

    return {
        "spin_polarized": False,
        "magnetic_elements": [],
        "provenance": Provenance(
            source="default",
            reason="No magnetic candidate elements were detected.",
        ),
    }
