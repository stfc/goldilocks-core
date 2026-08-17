from __future__ import annotations

from dataclasses import dataclass

from goldilocks_core.contracts.serial import to_jsonable
from goldilocks_core.contracts.types import (
    Dimensionality,
    ElectronicCharacter,
    JsonDict,
)


@dataclass(frozen=True, slots=True)
class SymmetryUnavailable:
    """Typed marker that symmetry facts could not be determined.

    Stored in ``StructureAnalysisRecord`` symmetry fields when spglib cannot
    analyze a structure (e.g. disordered sites). Carries a ``reason`` so the
    manifest records why the field is unavailable instead of a bare null.
    Symmetry is reporting-only; a recommendation stays complete with one of
    these in place of a crystal-system/space-group value.

    Attributes:
        reason: why symmetry analysis was unavailable.
    """

    reason: str


@dataclass(frozen=True, slots=True)
class StructureAnalysisRecord:
    """Facts reported by the Analyze stage without parameter decisions.

    Analysis is read-only: it reports what the structure *is*, not what
    parameters to use. Later stages consume these facts to make
    provenance-backed decisions.

    Attributes:
        formula: full chemical formula (e.g. ``Fe2O31``).
        reduced_formula: reduced formula (e.g. ``Fe2O3``).
        site_count: number of sites in the structure.
        elements: sorted unique element symbols.
        contains_transition_metals: True if any element is a
            transition metal (pymatgen classification).
        contains_lanthanides: True if any element is a lanthanide.
        contains_actinides: True if any element is an actinide.
        contains_heavy_elements: True if any element has
            period ≥ 5 (row ≥ 5 in pymatgen).
        magnetic_elements: elements that are transition metals,
            lanthanides, or actinides — magnetic candidates.
        heavy_elements: elements with period ≥ 5, relevant for
            SOC consideration.
        disorder_warnings: per-site warnings for partial
            occupancies.
        disordered_site_count: number of sites with partial
            occupancies.
        space_group_symbol: Hermann-Mauguin symbol, or
            ``SymmetryUnavailable`` when spglib cannot analyze, or None.
        space_group_number: International space group number
            (1–230), or ``SymmetryUnavailable``, or None.
        crystal_system: crystal system name (e.g. ``cubic``), or
            ``SymmetryUnavailable``, or None.
        dimensionality: structure dimensionality from a bonded-cluster
            analysis (``3d``, ``2d``, ``1d``, ``molecule``), or
            ``unknown`` when detection fails.
        low_dimensional: connectivity-derived low-dimensional heuristic:
            True when bonded dimensionality is below 3D. This is not a
            measured cell-vacuum quantity.
        electronic_character: electronic-character classification from the
            runtime model or structure-only fallback.
        electronic_character_source: origin of the classification, such as
            ``model`` or ``heuristic``.
        electronic_character_confidence: optional confidence score in [0, 1].
        analysis_warnings: warnings about heuristic limitations
            (e.g. metallicity uncertainty).
    """

    formula: str
    reduced_formula: str
    site_count: int
    elements: tuple[str, ...]
    contains_transition_metals: bool
    contains_lanthanides: bool
    contains_actinides: bool
    contains_heavy_elements: bool
    magnetic_elements: tuple[str, ...]
    heavy_elements: tuple[str, ...]
    disorder_warnings: tuple[str, ...] = ()
    disordered_site_count: int = 0
    space_group_symbol: str | int | SymmetryUnavailable | None = None
    space_group_number: str | int | SymmetryUnavailable | None = None
    crystal_system: str | int | SymmetryUnavailable | None = None
    dimensionality: Dimensionality = "unknown"
    low_dimensional: bool = False
    electronic_character: ElectronicCharacter = "unknown"
    electronic_character_source: str = "heuristic"
    electronic_character_confidence: float | None = None
    analysis_warnings: tuple[str, ...] = ()

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)
