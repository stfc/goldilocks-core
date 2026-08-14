from __future__ import annotations

from collections.abc import Callable

from pymatgen.analysis.dimensionality import get_dimensionality_larsen
from pymatgen.analysis.local_env import CrystalNN
from pymatgen.core import Structure
from pymatgen.core.graphs import StructureGraph
from pymatgen.core.periodic_table import Element
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from goldilocks_core.contracts import (
    Dimensionality,
    ElectronicCharacter,
    StructureAnalysisRecord,
    SymmetryUnavailable,
)


class DimensionalityClassificationError(Exception):
    """Raised when CrystalNN/Larsen fails on an ordered structure.
    Disordered structures get a conservative "unknown" default instead."""

    def __init__(self, structure: Structure, /) -> None:
        self.structure = structure
        super().__init__(
            f"Could not classify dimensionality for "
            f"{structure.composition.reduced_formula!r}."
        )


class SymmetryAnalysisError(Exception):
    """Raised when spglib cannot analyze a structure.
    ``analyze_structure`` catches this and records a ``SymmetryUnavailable``."""

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
    """Returns ``likely_metal`` when all elements are metallic,
    ``unknown`` otherwise. Never returns ``metal`` or ``insulator``
    — those require electronic-structure data."""
    periodic_elements = tuple(
        Element(symbol)
        for symbol in sorted(e.symbol for e in structure.composition.elements)
    )
    if periodic_elements and all(element.is_metal for element in periodic_elements):
        return "likely_metal"
    return "unknown"


def analyze_structure(
    structure: Structure,
    *,
    metallicity_classifier: Callable[
        [Structure], tuple[ElectronicCharacter, str, float | None]
    ]
    | None = None,
) -> StructureAnalysisRecord:
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
    dimensionality, low_dimensional, dimensionality_warnings = _analyze_dimensionality(
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
    if metallicity_classifier is None:
        electronic_character = heuristic_metallicity(structure)
        electronic_character_source = "heuristic"
        electronic_character_confidence = None
    else:
        (
            electronic_character,
            electronic_character_source,
            electronic_character_confidence,
        ) = metallicity_classifier(structure)
    electronic_warnings = _electronic_character_warnings(
        electronic_character, source=electronic_character_source
    )

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
        low_dimensional=low_dimensional,
        electronic_character=electronic_character,
        electronic_character_source=electronic_character_source,
        electronic_character_confidence=electronic_character_confidence,
        analysis_warnings=(*electronic_warnings, *dimensionality_warnings),
    )


def _find_disorder_warnings(structure: Structure) -> tuple[str, ...]:
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
    if not structure.is_ordered:
        return (
            "unknown",
            False,
            (
                "Dimensionality detection is not supported for disordered "
                "structures; defaulted to unknown with the low-dimensional "
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
    low_dimensional = bool(dimensionality != "unknown" and dim_value < 3)
    return dimensionality, low_dimensional, ()


def _analyze_symmetry(structure: Structure) -> dict[str, str | int]:
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
    *,
    source: str,
) -> tuple[str, ...]:
    if source != "heuristic":
        return ()
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
