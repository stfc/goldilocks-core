"""Smearing advice policy for the Advise stage."""

from __future__ import annotations

from goldilocks_core.contracts import (
    CalculationHints,
    Provenance,
    SmearingAdvice,
    StructureAnalysisRecord,
)

METALLIC_SMEARING_WIDTH_RY = 0.01


def advise_smearing(
    analysis: StructureAnalysisRecord,
    hints: CalculationHints,
) -> SmearingAdvice:
    if hints.smearing_type is not None or hints.smearing_width_ry is not None:
        return SmearingAdvice(
            smearing_type=hints.smearing_type,
            width_ry=hints.smearing_width_ry,
            provenance=Provenance(
                source="user_hint",
                reason="Use operator-provided smearing settings.",
            ),
        )

    if analysis.electronic_character in {"metal", "likely_metal"}:
        return SmearingAdvice(
            smearing_type="cold",
            width_ry=METALLIC_SMEARING_WIDTH_RY,
            provenance=Provenance(
                source="analysis",
                reason="Likely metallic composition benefits from modest smearing.",
                warnings=(
                    "Metallicity is inferred from structure-only heuristics; verify "
                    "against electronic-structure data.",
                ),
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
