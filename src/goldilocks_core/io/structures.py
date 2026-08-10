"""Structure input, parsing, and canonical document utilities."""

from __future__ import annotations

from pathlib import Path

from pymatgen.core import Composition, Structure

from goldilocks_core.contracts import (
    StructureDocument,
    StructureInput,
    StructureLattice,
    StructureSite,
    StructureSourceInfo,
    StructureSpecies,
)


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


def load_structure_from_text(content: str, fmt: str | None = None) -> Structure:
    """Parse inline structure text into a pymatgen Structure.

    When ``fmt`` is None, ``cif`` and ``poscar`` are tried in order. The last
    parse error is raised when no format parses.

    Raises:
        ValueError: If the content cannot be parsed as a supported format.
    """
    formats = (fmt,) if fmt is not None else ("cif", "poscar")
    last_error: Exception | None = None
    for structure_format in formats:
        try:
            return Structure.from_str(content, fmt=structure_format)
        except (IndexError, KeyError, TypeError, ValueError) as error:
            last_error = error
    raise ValueError(f"Could not parse inline structure content: {last_error}")


def structure_to_document(
    structure: Structure,
    *,
    source_format: str | None = None,
) -> StructureDocument:
    """Build a canonical StructureDocument from a pymatgen Structure.

    Preserves every species and occupancy on each site, so mixed-occupancy
    disorder survives transport unchanged.
    """
    lattice = structure.lattice
    matrix = tuple(tuple(float(value) for value in row) for row in lattice.matrix)
    sites = tuple(_structure_site(site) for site in structure)
    return StructureDocument(
        formula=structure.composition.formula,
        reduced_formula=structure.composition.reduced_formula,
        lattice=StructureLattice(
            matrix=matrix,
            a=float(lattice.a),
            b=float(lattice.b),
            c=float(lattice.c),
            alpha=float(lattice.alpha),
            beta=float(lattice.beta),
            gamma=float(lattice.gamma),
            volume=float(lattice.volume),
            pbc=tuple(bool(value) for value in lattice.pbc),
        ),
        sites=sites,
        charge=_structure_charge(structure),
        source=StructureSourceInfo(format=source_format, source="inline"),
    )


def _structure_charge(structure: Structure) -> float | None:
    """Return the cell charge, or None when it is not a real number."""
    charge = structure.charge
    if charge is None or not isinstance(charge, (int, float)):
        return None
    return float(charge)


def _structure_species(composition: Composition) -> tuple[StructureSpecies, ...]:
    """Return one StructureSpecies per element on a site."""
    return tuple(
        StructureSpecies(element=element.symbol, occupancy=float(occupancy))
        for element, occupancy in composition.items()
    )


def _structure_site(site: object) -> StructureSite:
    """Build a canonical StructureSite from a pymatgen PeriodicSite."""
    species = getattr(site, "species")
    composition = (
        species if isinstance(species, Composition) else Composition({species: 1})
    )
    return StructureSite(
        label=str(site.label),
        species=_structure_species(composition),
        abc=tuple(float(value) for value in site.frac_coords),
        xyz=tuple(float(value) for value in site.coords),
    )
