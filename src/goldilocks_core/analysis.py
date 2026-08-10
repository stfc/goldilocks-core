"""Analyze-stage structure facts for the Core pipeline."""

from __future__ import annotations

from pymatgen.analysis.dimensionality import get_dimensionality_larsen
from pymatgen.analysis.local_env import CrystalNN
from pymatgen.core import Structure
from pymatgen.core.graphs import StructureGraph
from pymatgen.core.periodic_table import Element
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from goldilocks_core._lint import allow_swallow
from goldilocks_core.contracts import (
    Dimensionality,
    ElectronicCharacter,
    StructureAnalysisRecord,
    SymmetryUnavailable,
)


class DimensionalityClassificationError(Exception):
    """Dimensionality could not be classified for a structure.

    Raised when CrystalNN bonding or the Larsen dimensionality algorithm fails.
    The recommendation cannot proceed: ``advise_vdw`` depends on dimensionality,
    so a silent fallback to ``"unknown"`` would produce a partial recommendation.
    The real fix is a goldilocks-side classifier (see #133).
    """

    def __init__(self, structure: Structure, /) -> None:
        self.structure = structure
        super().__init__(
            f"Could not classify dimensionality for "
            f"{structure.composition.reduced_formula!r}."
        )


class SymmetryAnalysisError(Exception):
    """Symmetry facts could not be determined for a structure.

    Raised when spglib cannot analyze a structure. ``analyze_structure`` catches
    this and records a typed ``SymmetryUnavailable`` in the analysis record so
    the recommendation stays complete (symmetry is reporting-only).
    """

    def __init__(self, structure: Structure, /, *, reason: str = "") -> None:
        self.structure = structure
        self.reason = reason or "symmetry analysis failed"
        super().__init__(self.reason)


_DIMENSIONALITY_BY_VALUE: dict[int, Dimensionality] = {
    3: "3d",
    2: "2d",
    1: "1d",
    0: "molecule",
}


def heuristic_metallicity(structure: Structure) -> ElectronicCharacter:
    """Return a conservative structure-only electronic character heuristic.

    Classifies a composition as ``likely_metal`` when every element is metallic
    and ``unknown`` otherwise. Carries no electronic-structure evidence.
    """
    periodic_elements = tuple(
        Element(symbol)
        for symbol in sorted(e.symbol for e in structure.composition.elements)
    )
    if periodic_elements and all(element.is_metal for element in periodic_elements):
        return "likely_metal"
    return "unknown"


@allow_swallow
def analyze_structure(structure: Structure) -> StructureAnalysisRecord:
    """Return deterministic structure facts used by later pipeline stages.

    Args:
        structure: Ordered or disordered pymatgen structure to inspect.

    Returns:
        A ``StructureAnalysisRecord`` with composition, element classes,
        disorder warnings, symmetry facts when available, and conservative
        electronic-character hints.

    Assumes:
        The input structure has already been loaded and normalized by the Load
        stage. This function reports facts only; it does not choose parameters.
    """
    elements = tuple(
        sorted(element.symbol for element in structure.composition.elements)
    )
    periodic_elements = tuple(Element(symbol) for symbol in elements)

    transition_metals = tuple(
        element.symbol for element in periodic_elements if element.is_transition_metal
    )
    lanthanides = tuple(
        element.symbol for element in periodic_elements if element.is_lanthanoid
    )
    actinides = tuple(
        element.symbol for element in periodic_elements if element.is_actinoid
    )
    heavy_elements = tuple(
        element.symbol for element in periodic_elements if element.row >= 5
    )
    magnetic_elements = tuple(sorted({*transition_metals, *lanthanides, *actinides}))
    disorder_warnings = _find_disorder_warnings(structure)
    dimensionality, has_vacuum, dimensionality_warnings = _analyze_dimensionality(
        structure
    )
    try:
        symmetry = _analyze_symmetry(structure)
    except SymmetryAnalysisError as error:
        unavailable = SymmetryUnavailable(reason=error.reason)
        symmetry = {
            "space_group_symbol": unavailable,
            "space_group_number": unavailable,
            "crystal_system": unavailable,
        }
    electronic_character = heuristic_metallicity(structure)
    electronic_warnings = _electronic_character_warnings(electronic_character)

    return StructureAnalysisRecord(
        formula=structure.composition.formula,
        reduced_formula=structure.composition.reduced_formula,
        site_count=len(structure),
        elements=elements,
        contains_transition_metals=bool(transition_metals),
        contains_lanthanides=bool(lanthanides),
        contains_actinides=bool(actinides),
        contains_heavy_elements=bool(heavy_elements),
        magnetic_elements=magnetic_elements,
        heavy_elements=heavy_elements,
        disorder_warnings=disorder_warnings,
        disordered_site_count=len(disorder_warnings),
        space_group_symbol=symmetry["space_group_symbol"],
        space_group_number=symmetry["space_group_number"],
        crystal_system=symmetry["crystal_system"],
        dimensionality=dimensionality,
        has_vacuum=has_vacuum,
        electronic_character=electronic_character,
        electronic_character_source="heuristic",
        electronic_character_confidence=None,
        analysis_warnings=(*electronic_warnings, *dimensionality_warnings),
    )


def _find_disorder_warnings(structure: Structure) -> tuple[str, ...]:
    """Return warnings for disordered or partially occupied sites."""
    warnings: list[str] = []

    for index, site in enumerate(structure, start=1):
        if getattr(site, "is_ordered", True):
            continue

        species = ", ".join(
            f"{species.symbol}:{occupancy:g}"
            for species, occupancy in site.species.items()
        )
        warnings.append(f"Site {index} has partial occupancies: {species}.")

    return tuple(warnings)


def _analyze_dimensionality(
    structure: Structure,
) -> tuple[Dimensionality, bool, tuple[str, ...]]:
    """Return dimensionality, a low-dimensional/vacuum heuristic, and warnings.

    Uses pymatgen's CrystalNN graph and Larsen dimensionality algorithm. The
    heuristic is connectivity-derived, not a measurement of cell vacuum.
    Disordered structures are not passed to CrystalNN because its graph path
    does not support them; they get a conservative ``"unknown"`` default with a
    warning. When CrystalNN or Larsen fails on an ordered structure,
    :class:`DimensionalityClassificationError` propagates -- the recommendation
    cannot proceed without dimensionality (see #133).
    """
    if not structure.is_ordered:
        return (
            "unknown",
            False,
            (
                "Dimensionality detection is not supported for disordered "
                "structures; defaulted to unknown with the low-dimensional/vacuum "
                "heuristic disabled. Set CalculationHints(use_vdw=True) explicitly "
                "if a vdW correction is needed.",
            ),
        )

    try:
        bonded = StructureGraph.from_local_env_strategy(structure, CrystalNN())
        dim_value = get_dimensionality_larsen(bonded)
    except (ValueError, RuntimeError) as error:
        raise DimensionalityClassificationError(structure) from error

    dimensionality = _DIMENSIONALITY_BY_VALUE.get(dim_value, "unknown")
    has_vacuum = bool(dimensionality != "unknown" and dim_value < 3)
    return dimensionality, has_vacuum, ()


def _analyze_symmetry(structure: Structure) -> dict[str, str | int]:
    """Return stable pymatgen-backed symmetry facts.

    Raises :class:`SymmetryAnalysisError` when the structure is disordered or
    spglib cannot analyze it; ``analyze_structure`` records the failure as a
    typed ``SymmetryUnavailable`` so the recommendation stays complete.
    """
    if not structure.is_ordered:
        raise SymmetryAnalysisError(structure, reason="disordered structure")

    try:
        analyzer = SpacegroupAnalyzer(structure)
        return {
            "space_group_symbol": analyzer.get_space_group_symbol(),
            "space_group_number": analyzer.get_space_group_number(),
            "crystal_system": analyzer.get_crystal_system(),
        }
    except (TypeError, ValueError) as error:
        raise SymmetryAnalysisError(structure, reason=str(error)) from error


def _electronic_character_warnings(
    character: ElectronicCharacter,
) -> tuple[str, ...]:
    """Return heuristic-uncertainty warnings for a given electronic character.

    Only the structure-only heuristics (``likely_metal``, ``unknown``) carry
    uncertainty warnings; a decided ``metal`` or ``insulator`` carries none.
    """
    if character == "likely_metal":
        return (
            "All elements are metallic; treat metallicity as likely, not "
            "confirmed without electronic-structure data.",
        )
    if character == "unknown":
        return (
            "Electronic character is unknown from structure facts alone; verify "
            "smearing manually for metallic systems.",
        )
    return ()
