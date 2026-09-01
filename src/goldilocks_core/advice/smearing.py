"""Smearing advice policy for the Advise stage."""

from __future__ import annotations

from goldilocks_core.advice._hints import has_hint
from goldilocks_core.contracts import (
    Provenance,
    SmearingAdvice,
    SmearingHints,
    StructureAnalysisRecord,
)

METALLIC_SMEARING_WIDTH_RY = 0.01


def advise_smearing(
    analysis: StructureAnalysisRecord,
    hints: SmearingHints,
) -> SmearingAdvice:
    if has_hint(hints):
        return SmearingAdvice(
            smearing_type=hints.smearing_type,
            width_ry=hints.smearing_width_ry,
            provenance=Provenance(
                source="user_hint",
                reason="Use operator-provided smearing settings.",
            ),
        )

    if analysis.electronic_character in {"metal", "likely_metal"}:
        heuristic_inferred = analysis.electronic_character_source == "heuristic"
        return SmearingAdvice(
            smearing_type="cold",
            width_ry=METALLIC_SMEARING_WIDTH_RY,
            provenance=Provenance(
                source="analysis",
                reason="Likely metallic composition benefits from modest smearing.",
                warnings=(
                    (
                        "Metallicity is inferred from structure-only heuristics; "
                        "verify against electronic-structure data.",
                    )
                    if heuristic_inferred
                    else ()
                ),
            ),
        )

    if analysis.electronic_character == "insulator":
        return SmearingAdvice(
            smearing_type="fixed",
            width_ry=None,
            provenance=Provenance(
                source="analysis",
                reason="Insulating electronic character supports fixed occupations.",
            ),
        )

    return SmearingAdvice(
        smearing_type="fixed",
        width_ry=None,
        provenance=Provenance(
            source="default",
            reason="Metallicity is unknown; use fixed occupations by default.",
            warnings=("Verify smearing manually for likely metallic systems.",),
        ),
    )
