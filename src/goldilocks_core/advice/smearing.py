from __future__ import annotations

from dataclasses import dataclass

from goldilocks_core.advice._hints import has_hint
from goldilocks_core.analysis import StructureAnalysisRecord
from goldilocks_core.calculation import SmearingHints
from goldilocks_core.provenance import Provenance
from goldilocks_core.serialization import to_jsonable
from goldilocks_core.types import JsonDict

METALLIC_SMEARING_WIDTH_RY = 0.01


@dataclass(frozen=True, slots=True)
class SmearingAdvice:
    """Advised occupation treatment.

    ``smearing_type`` ``None`` or ``"fixed"`` means fixed occupations; a
    named smearing type activates ``width_ry``, which is in Rydberg and
    ``None`` only alongside fixed occupations. ``provenance`` states the
    source precedence: an operator hint wins over the structure analysis,
    which wins over the package default.
    """

    smearing_type: str | None
    width_ry: float | None
    provenance: Provenance

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)


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

    if analysis.electronic_character == "metal":
        return SmearingAdvice(
            smearing_type="cold",
            width_ry=METALLIC_SMEARING_WIDTH_RY,
            provenance=Provenance(
                source="analysis",
                reason=(
                    "Model-classified metallic systems benefit from modest smearing."
                ),
            ),
        )

    if analysis.electronic_character == "likely_metal":
        return SmearingAdvice(
            smearing_type="cold",
            width_ry=METALLIC_SMEARING_WIDTH_RY,
            provenance=Provenance(
                source="analysis",
                reason="Likely metallic composition benefits from modest smearing.",
                warnings=("Metallicity was inferred from structure-only heuristics.",),
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
        ),
    )
