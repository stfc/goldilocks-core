"""Analyse-stage structure facts for the Core pipeline."""

from __future__ import annotations

from pymatgen.core import Structure
from pymatgen.core.periodic_table import Element

from goldilocks_core.contracts import StructureAnalysisRecord


def analyse_structure(structure: Structure) -> StructureAnalysisRecord:
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
        disorder_warnings=_find_disorder_warnings(structure),
    )


def analyze_structure(structure: Structure) -> StructureAnalysisRecord:
    """Alias for callers using American spelling."""
    return analyse_structure(structure)


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
