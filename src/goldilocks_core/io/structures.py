from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from pymatgen.core import Structure

from goldilocks_core.contracts.structure import (
    InlineStructureSource,
    InMemoryStructureSource,
    LatticeDocument,
    PathStructureSource,
    SpeciesOccupancy,
    StructureDocument,
    StructureFormat,
    StructureInspection,
    StructureSiteDocument,
    StructureSource,
    StructureSourceDocument,
)


class StructureInputError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class NormalizedStructure:
    structure: Structure
    source: StructureSourceDocument
    canonical_structure: StructureDocument
    canonical_cif: str

    @property
    def inspection(self) -> StructureInspection:
        return StructureInspection(
            source=self.source,
            structure=self.canonical_structure,
            canonical_cif=self.canonical_cif,
        )


def normalize_structure(source: StructureSource) -> NormalizedStructure:
    if isinstance(source, InMemoryStructureSource):
        structure = source.structure
        source_document = StructureSourceDocument(
            origin="generated",
            name="generated-structure",
            format="pymatgen",
            content=None,
            sha256=None,
            size_bytes=None,
        )
    else:
        if isinstance(source, InlineStructureSource):
            content, name, format_hint = source.content, source.name, source.format
            origin = "inline"
        elif isinstance(source, PathStructureSource):
            path = Path(source.path)
            if not path.exists():
                raise FileNotFoundError(f"Structure file not found: {path}")
            if not path.is_file():
                raise StructureInputError(f"Structure path is not a file: {path}")
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError as error:
                raise StructureInputError(
                    f"Structure file must contain UTF-8 text: {path}"
                ) from error
            name, format_hint = path.name, None
            origin = "path"
        else:
            raise TypeError(
                "source must be an InlineStructureSource, PathStructureSource, "
                "or InMemoryStructureSource"
            )
        if not content.strip():
            raise StructureInputError("Structure content must be non-empty text.")
        resolved_format = _resolve_format(name, content, format_hint)
        try:
            structure = Structure.from_str(content, fmt=resolved_format)
        except (IndexError, KeyError, TypeError, ValueError) as error:
            raise StructureInputError(
                f"Could not parse {resolved_format.upper()} structure: {error}"
            ) from error
        source_bytes = content.encode("utf-8")
        source_document = StructureSourceDocument(
            origin=origin,
            name=name,
            format=resolved_format,
            content=content,
            sha256=hashlib.sha256(source_bytes).hexdigest(),
            size_bytes=len(source_bytes),
        )
    return NormalizedStructure(
        structure=structure,
        source=source_document,
        canonical_structure=structure_document(structure),
        canonical_cif=structure.to(fmt="cif"),
    )


def load_structure(structure: Structure | str | Path) -> Structure:
    """Load one structure from a path, or pass a Structure through.

    Raises FileNotFoundError when the path does not exist,
    StructureInputError when it is not a file or pymatgen cannot parse it,
    and TypeError for input types outside the contract.
    """
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


def structure_document(structure: Structure) -> StructureDocument:
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


def _resolve_format(
    name: str, content: str, format_hint: StructureFormat | None
) -> StructureFormat:
    if format_hint is not None:
        return format_hint
    lower_name = name.lower()
    if lower_name == "poscar" or lower_name.endswith(".poscar"):
        return "poscar"
    first_data_line = next(
        (
            line.strip()
            for line in content.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ),
        "",
    )
    if lower_name.endswith(".cif") or first_data_line.startswith("data_"):
        return "cif"
    return "poscar"


def _vector(values: object) -> tuple[float, float, float]:
    x, y, z = values
    return float(x), float(y), float(z)
