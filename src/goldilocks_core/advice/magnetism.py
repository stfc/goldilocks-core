"""Magnetism advice policy for the Advise stage."""

from __future__ import annotations

from goldilocks_core.contracts import (
    CalculationHints,
    MagnetismAdvice,
    Provenance,
    StructureAnalysisRecord,
)


def advise_magnetism(
    analysis: StructureAnalysisRecord,
    hints: CalculationHints,
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
