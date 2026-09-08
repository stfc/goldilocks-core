from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, TypedDict

from pymatgen.core import Structure

from goldilocks_core.failures import ExpectedFailure
from goldilocks_core.serialization import Portable, to_portable
from goldilocks_core.types import JsonDict

Vector3 = tuple[float, float, float]
Matrix3 = tuple[Vector3, Vector3, Vector3]
StructureFormat = Literal["cif", "poscar"]


class SpeciesOccupancy(TypedDict):
    symbol: str
    label: str
    occupancy: float
    oxidation_state: float | None


class StructureSite(TypedDict):
    fractional_coordinates: Annotated[list[float], Portable(Vector3)]
    cartesian_coordinates_angstrom: Annotated[list[float], Portable(Vector3)]
    species: list[SpeciesOccupancy]


class LatticeDocument(TypedDict):
    vectors_angstrom: Annotated[list[list[float]], Portable(Matrix3)]
    lengths_angstrom: Annotated[list[float], Portable(Vector3)]
    angles_degrees: Annotated[list[float], Portable(Vector3)]
    volume_angstrom3: float


class StructureDocument(TypedDict):
    schema_version: int
    formula: str
    reduced_formula: str
    site_count: int
    lattice: LatticeDocument
    periodicity: Annotated[list[bool], Portable(tuple[bool, bool, bool])]
    sites: list[StructureSite]


class StructureSourceDocument(TypedDict):
    origin: Literal["inline", "path", "generated"]
    name: str
    format: str
    content: str | None
    sha256: str | None
    size_bytes: int | None


class StructureInspection(TypedDict):
    source: StructureSourceDocument
    structure: StructureDocument
    canonical_cif: str
    schema_version: int


@dataclass(frozen=True, slots=True)
class InlineStructureSource:
    name: str
    content: str
    format: StructureFormat | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.name, str)
            or not self.name.strip()
            or self.name in {".", ".."}
            or "/" in self.name
            or "\\" in self.name
            or any(unicodedata.category(character) == "Cc" for character in self.name)
        ):
            raise ValueError("InlineStructureSource.name must be one filename")
        if not isinstance(self.content, str):
            raise ValueError("InlineStructureSource.content must be text")
        if self.format is not None and self.format not in ("cif", "poscar"):
            raise ValueError(
                f"Unsupported structure format {self.format!r}; "
                "expected one of cif, poscar."
            )


@dataclass(frozen=True, slots=True)
class PathStructureSource:
    path: str | Path

    def __post_init__(self) -> None:
        if not isinstance(self.path, str | Path) or not str(self.path).strip():
            raise ValueError("PathStructureSource.path must be a non-empty path")


@dataclass(frozen=True, slots=True)
class InMemoryStructureSource:
    structure: Structure

    def __post_init__(self) -> None:
        if not isinstance(self.structure, Structure):
            raise ValueError(
                "InMemoryStructureSource.structure must be a pymatgen Structure"
            )


type StructureSource = (
    InlineStructureSource | PathStructureSource | InMemoryStructureSource
)


@to_portable.register(InlineStructureSource)
def _inline_structure_source_portable(source: InlineStructureSource) -> JsonDict:
    return {
        "kind": "inline",
        "name": source.name,
        "content": source.content,
        "format": source.format,
    }


@to_portable.register(PathStructureSource)
def _path_structure_source_portable(source: PathStructureSource) -> JsonDict:
    return {"kind": "path", "path": str(source.path)}


@to_portable.register(InMemoryStructureSource)
def _in_memory_structure_source_portable(
    source: InMemoryStructureSource,
) -> JsonDict:
    return {"kind": "in_memory", "structure": source.structure.as_dict()}


@dataclass(frozen=True, slots=True)
class NormalizedStructure:
    structure: Structure
    source: StructureSourceDocument
    canonical_structure: StructureDocument
    canonical_cif: str

    @property
    def inspection(self) -> StructureInspection:
        return {
            "source": self.source,
            "structure": self.canonical_structure,
            "canonical_cif": self.canonical_cif,
            "schema_version": 1,
        }


class StructureInputError(ExpectedFailure, ValueError):
    kind = "invalid_structure"


class StructureFileNotFound(ExpectedFailure, FileNotFoundError):
    kind = "invalid_structure"


def normalize_structure(source: StructureSource) -> NormalizedStructure:
    if isinstance(source, InMemoryStructureSource):
        structure = source.structure
        source_document: StructureSourceDocument = {
            "origin": "generated",
            "name": "generated-structure",
            "format": "pymatgen",
            "content": None,
            "sha256": None,
            "size_bytes": None,
        }
    else:
        if isinstance(source, InlineStructureSource):
            content, name, format_hint = source.content, source.name, source.format
            origin = "inline"
        elif isinstance(source, PathStructureSource):
            path = Path(source.path)
            if not path.exists():
                raise StructureFileNotFound(f"Structure file not found: {path}")
            if not path.is_file():
                raise StructureInputError(f"Structure path is not a file: {path}")
            try:
                content = path.read_bytes().decode("utf-8")
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
            structure = Structure.from_str(
                content.replace("\r\n", "\n").replace("\r", "\n"),
                fmt=resolved_format,
            )
        except (IndexError, KeyError, TypeError, ValueError) as error:
            raise StructureInputError(
                f"Could not parse {resolved_format.upper()} structure: {error}"
            ) from error
        source_bytes = content.encode("utf-8")
        source_document = {
            "origin": origin,
            "name": name,
            "format": resolved_format,
            "content": content,
            "sha256": hashlib.sha256(source_bytes).hexdigest(),
            "size_bytes": len(source_bytes),
        }
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
    sites = [
        {
            "fractional_coordinates": list(_vector(site.frac_coords)),
            "cartesian_coordinates_angstrom": list(_vector(site.coords)),
            "species": [
                {
                    "symbol": species.symbol,
                    "label": str(species),
                    "occupancy": float(occupancy),
                    "oxidation_state": (
                        float(species.oxi_state)
                        if getattr(species, "oxi_state", None) is not None
                        else None
                    ),
                }
                for species, occupancy in sorted(
                    site.species.items(), key=lambda item: str(item[0])
                )
            ],
        }
        for site in structure
    ]
    return {
        "schema_version": 1,
        "formula": structure.composition.formula,
        "reduced_formula": structure.composition.reduced_formula,
        "site_count": len(structure),
        "lattice": {
            "vectors_angstrom": [list(_vector(row)) for row in lattice.matrix],
            "lengths_angstrom": list(_vector(lattice.abc)),
            "angles_degrees": list(_vector(lattice.angles)),
            "volume_angstrom3": float(lattice.volume),
        },
        "periodicity": list(lattice.pbc),
        "sites": sites,
    }


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
