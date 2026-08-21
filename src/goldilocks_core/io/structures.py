from __future__ import annotations

import hashlib
from pathlib import Path

from pymatgen.core import Structure

from goldilocks_core.contracts import StructureInput
from goldilocks_core.contracts.structure import (
    LatticeDocument,
    SpeciesOccupancy,
    StructureDocument,
    StructureSiteDocument,
    StructureSourceDocument,
)

SUPPORTED_STRUCTURE_FORMATS = ("cif", "poscar")


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


def parse_structure_content(
    content: str, format_hint: str | None = None
) -> tuple[Structure, str]:
    if not isinstance(content, str) or not content.strip():
        raise StructureInputError("Structure content must be non-empty text.")
    if format_hint is not None and format_hint not in SUPPORTED_STRUCTURE_FORMATS:
        choices = ", ".join(SUPPORTED_STRUCTURE_FORMATS)
        raise StructureInputError(
            f"Unsupported structure format {format_hint!r}; expected one of {choices}."
        )

    formats = (format_hint,) if format_hint is not None else SUPPORTED_STRUCTURE_FORMATS
    errors: list[str] = []
    for structure_format in formats:
        try:
            return Structure.from_str(content, fmt=structure_format), structure_format
        except (IndexError, KeyError, TypeError, ValueError) as error:
            errors.append(f"{structure_format}: {error}")
    raise StructureInputError(
        "Could not parse structure content as CIF or POSCAR: " + "; ".join(errors)
    )


def structure_document(
    structure: Structure,
    *,
    source_name: str,
    source_format: str,
    source_content: str,
) -> StructureDocument:
    source_bytes = source_content.encode("utf-8")
    lattice = structure.lattice
    sites = tuple(
        StructureSiteDocument(
            fractional_coordinates=_vector(site.frac_coords),
            cartesian_coordinates_angstrom=_vector(site.coords),
            species=tuple(
                SpeciesOccupancy(
                    symbol=species.symbol,
                    label=str(species),
                    occupancy=float(occupancy),
                    oxidation_state=(
                        float(species.oxi_state)
                        if getattr(species, "oxi_state", None) is not None
                        else None
                    ),
                )
                for species, occupancy in sorted(
                    site.species.items(), key=lambda item: str(item[0])
                )
            ),
        )
        for site in structure
    )
    return StructureDocument(
        schema_version=1,
        source=StructureSourceDocument(
            name=source_name,
            format=source_format,
            sha256=hashlib.sha256(source_bytes).hexdigest(),
            size_bytes=len(source_bytes),
        ),
        formula=structure.composition.formula,
        reduced_formula=structure.composition.reduced_formula,
        site_count=len(structure),
        lattice=LatticeDocument(
            vectors_angstrom=tuple(_vector(row) for row in lattice.matrix),
            lengths_angstrom=_vector(lattice.abc),
            angles_degrees=_vector(lattice.angles),
            volume_angstrom3=float(lattice.volume),
        ),
        periodicity=(True, True, True),
        sites=sites,
    )


def _vector(values: object) -> tuple[float, float, float]:
    x, y, z = values
    return float(x), float(y), float(z)
