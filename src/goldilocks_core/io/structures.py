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

SUPPORTED_STRUCTURE_FORMATS: tuple[StructureFormat, ...] = ("cif", "poscar")


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
    if isinstance(source, InlineStructureSource):
        content = source.content
        name = source.name
        resolved_format = _resolve_format(name, content, source.format)
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
        name = path.name
        resolved_format = _resolve_format(name, content, None)
        origin = "path"
    elif isinstance(source, InMemoryStructureSource):
        return _normalized_structure(
            source.structure,
            _source_document(
                origin="generated",
                name="generated-structure",
                source_format="pymatgen",
                content=None,
            ),
        )
    else:
        raise TypeError(
            "source must be an InlineStructureSource, PathStructureSource, "
            "or InMemoryStructureSource"
        )

    structure, _ = parse_structure_content(content, resolved_format)
    source_document = _source_document(
        origin=origin,
        name=name,
        source_format=resolved_format,
        content=content,
    )
    return _normalized_structure(structure, source_document)


def load_structure(structure: Structure | str | Path) -> Structure:
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

    structure_format = format_hint or _resolve_format("structure", content, None)
    try:
        return Structure.from_str(content, fmt=structure_format), structure_format
    except (IndexError, KeyError, TypeError, ValueError) as error:
        raise StructureInputError(
            f"Could not parse structure content as {structure_format.upper()}: {error}"
        ) from error


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
    if lower_name == "poscar":
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


def _source_document(
    *,
    origin: str,
    name: str,
    source_format: str,
    content: str | None,
) -> StructureSourceDocument:
    source_bytes = content.encode("utf-8") if content is not None else None
    return StructureSourceDocument(
        origin=origin,
        name=name,
        format=source_format,
        content=content,
        sha256=(
            hashlib.sha256(source_bytes).hexdigest()
            if source_bytes is not None
            else None
        ),
        size_bytes=len(source_bytes) if source_bytes is not None else None,
    )


def _normalized_structure(
    structure: Structure, source: StructureSourceDocument
) -> NormalizedStructure:
    canonical_cif = structure.to(fmt="cif")
    return NormalizedStructure(
        structure=structure,
        source=source,
        canonical_structure=structure_document(structure),
        canonical_cif=canonical_cif,
    )


def _vector(values: object) -> tuple[float, float, float]:
    x, y, z = values
    return float(x), float(y), float(z)
