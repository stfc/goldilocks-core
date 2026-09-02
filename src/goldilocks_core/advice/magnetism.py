from __future__ import annotations

from dataclasses import dataclass

from goldilocks_core.analysis import StructureAnalysisRecord
from goldilocks_core.calculation import SpinHints
from goldilocks_core.provenance import Provenance
from goldilocks_core.serialization import to_jsonable
from goldilocks_core.types import JsonDict


@dataclass(frozen=True, slots=True)
class MagnetismAdvice:
    spin_polarized: bool
    magnetic_elements: tuple[str, ...]
    provenance: Provenance

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)


def advise_magnetism(
    analysis: StructureAnalysisRecord,
    hints: SpinHints,
) -> MagnetismAdvice:
    if hints.spin_polarized is not None:
        return MagnetismAdvice(
            spin_polarized=hints.spin_polarized,
            magnetic_elements=analysis.magnetic_elements,
            provenance=Provenance(
                source="user_hint",
                reason="Use the operator-provided spin-polarization setting.",
            ),
        )

    if analysis.magnetic_elements:
        return MagnetismAdvice(
            spin_polarized=True,
            magnetic_elements=analysis.magnetic_elements,
            provenance=Provenance(
                source="analysis",
                reason="Magnetic candidate elements are present in the structure.",
            ),
        )

    return MagnetismAdvice(
        spin_polarized=False,
        magnetic_elements=(),
        provenance=Provenance(
            source="default",
            reason="No magnetic candidate elements were detected.",
        ),
    )
