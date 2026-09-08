from __future__ import annotations

from typing import TypedDict

from goldilocks_core.analysis import StructureAnalysisRecord
from goldilocks_core.calculation import CalculationHints
from goldilocks_core.provenance import Provenance
from goldilocks_core.types import SmearingType

METALLIC_SMEARING_WIDTH_RY = 0.01


class SmearingAdvice(TypedDict):
    smearing_type: SmearingType | None
    width_ry: float | None
    provenance: Provenance


def advise_smearing(
    analysis: StructureAnalysisRecord,
    hints: CalculationHints,
) -> SmearingAdvice:
    if hints.smearing_type is not None or hints.smearing_width_ry is not None:
        return {
            "smearing_type": hints.smearing_type,
            "width_ry": hints.smearing_width_ry,
            "provenance": Provenance(
                source="user_hint",
                reason="Use operator-provided smearing settings.",
            ),
        }

    if analysis["electronic_character"] == "metal":
        return {
            "smearing_type": "cold",
            "width_ry": METALLIC_SMEARING_WIDTH_RY,
            "provenance": Provenance(
                source="analysis",
                reason=(
                    "Model-classified metallic systems benefit from modest smearing."
                ),
            ),
        }

    if analysis["electronic_character"] == "likely_metal":
        return {
            "smearing_type": "cold",
            "width_ry": METALLIC_SMEARING_WIDTH_RY,
            "provenance": Provenance(
                source="analysis",
                reason="Likely metallic composition benefits from modest smearing.",
                warnings=("Metallicity was inferred from structure-only heuristics.",),
            ),
        }

    if analysis["electronic_character"] == "insulator":
        return {
            "smearing_type": "fixed",
            "width_ry": None,
            "provenance": Provenance(
                source="analysis",
                reason="Insulating electronic character supports fixed occupations.",
            ),
        }

    return {
        "smearing_type": "fixed",
        "width_ry": None,
        "provenance": Provenance(
            source="default",
            reason="Metallicity is unknown; use fixed occupations by default.",
        ),
    }
