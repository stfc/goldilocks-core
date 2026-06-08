"""Structure input and analysis utilities."""

from __future__ import annotations

from pathlib import Path

from pymatgen.core import Structure

from goldilocks_core.analysis import analyse_structure
from goldilocks_core.contracts import StructureAnalysis, StructureInput


def load_structure(structure: StructureInput) -> Structure:
    """Load a structure input into a pymatgen Structure.

    Parameters
    ----------
    structure
        Either a pymatgen Structure object or a path to a structure file.

    Returns
    -------
    Structure
        A pymatgen Structure instance.

    Raises
    ------
    FileNotFoundError
        If the provided structure path does not exist.
    ValueError
        If the file format is not supported as a periodic structure input.
    TypeError
        If the input is neither a Structure nor a valid path-like value.
    """
    if isinstance(structure, Structure):
        return structure

    if isinstance(structure, (str, Path)):
        structure_path = Path(structure)
        if not structure_path.exists():
            raise FileNotFoundError(f"Structure file not found: {structure_path}")

        try:
            return Structure.from_file(structure_path)
        except ValueError as exc:
            raise ValueError(
                "Unsupported structure file format. "
                "goldilocks-core currently supports periodic structure files "
                "readable by pymatgen.Structure."
            ) from exc

    raise TypeError(
        "structure must be a pymatgen Structure or a path to a structure file"
    )


def analyze_structure(structure: Structure) -> StructureAnalysis:
    """Return the legacy structure-analysis summary."""
    analysis = analyse_structure(structure)

    return StructureAnalysis(
        contains_transition_metals=analysis.contains_transition_metals,
        contains_lanthanides=analysis.contains_lanthanides,
        contains_heavy_elements=analysis.contains_heavy_elements,
    )
