"""Analyze-stage structure facts for the Core pipeline."""

from __future__ import annotations

from pymatgen.core import Structure
from pymatgen.core.periodic_table import Element
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from goldilocks_core.contracts import StructureAnalysisRecord


def analyze_structure(structure: Structure) -> StructureAnalysisRecord:
    """Return deterministic structure facts used by later pipeline stages."""
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
    symmetry = _analyze_symmetry(structure)
    electronic_character, electronic_warnings = _classify_electronic_character(
        periodic_elements
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
        electronic_character=electronic_character,
        analysis_warnings=electronic_warnings,
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


def _analyze_symmetry(structure: Structure) -> dict[str, str | int | None]:
    """Return stable pymatgen-backed symmetry facts when available."""
    if not structure.is_ordered:
        return {
            "space_group_symbol": None,
            "space_group_number": None,
            "crystal_system": None,
        }

    try:
        analyzer = SpacegroupAnalyzer(structure)
        return {
            "space_group_symbol": analyzer.get_space_group_symbol(),
            "space_group_number": analyzer.get_space_group_number(),
            "crystal_system": analyzer.get_crystal_system(),
        }
    except (TypeError, ValueError):
        return {
            "space_group_symbol": None,
            "space_group_number": None,
            "crystal_system": None,
        }


def _classify_electronic_character(
    elements: tuple[Element, ...],
) -> tuple[str, tuple[str, ...]]:
    """Return a conservative structure-only electronic character heuristic."""
    if elements and all(element.is_metal for element in elements):
        return (
            "likely_metal",
            (
                "All elements are metallic; treat metallicity as likely, not "
                "confirmed without electronic-structure data.",
            ),
        )

    return (
        "unknown",
        (
            "Electronic character is unknown from structure facts alone; verify "
            "smearing manually for metallic systems.",
        ),
    )
