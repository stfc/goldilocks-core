from __future__ import annotations

from pathlib import Path

from pymatgen.core import Structure

from goldilocks_core.contracts import StructureInput


class StructureInputError(ValueError):
    pass


def load_structure(structure: StructureInput) -> Structure:
    if isinstance(structure, Structure):
        return structure

    if isinstance(structure, (str, Path)):
        structure_path = Path(structure)
        if not structure_path.exists():
            raise FileNotFoundError(f"Structure file not found: {structure_path}")
        if not structure_path.is_file():
            raise StructureInputError(f"Structure path is not a file: {structure_path}")

        try:
            return Structure.from_file(structure_path)
        except ValueError as exc:
            raise StructureInputError(
                "Unsupported structure file format. "
                "goldilocks-core currently supports periodic structure files "
                "readable by pymatgen.Structure."
            ) from exc

    raise TypeError(
        "structure must be a pymatgen Structure or a path to a structure file"
    )
