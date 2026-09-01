from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Literal

from pymatgen.core import Structure

from goldilocks_core.contracts.serial import to_jsonable
from goldilocks_core.contracts.types import JsonDict

Vector3 = tuple[float, float, float]
Matrix3 = tuple[Vector3, Vector3, Vector3]
StructureFormat = Literal["cif", "poscar"]


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
            or PurePath(self.name).name != self.name
            or "/" in self.name
            or "\\" in self.name
            or any(unicodedata.category(character) == "Cc" for character in self.name)
        ):
            raise ValueError("InlineStructureSource.name must be one filename")
        if not isinstance(self.content, str):
            raise ValueError("InlineStructureSource.content must be text")
        _validate_format(self.format)

    def to_dict(self) -> JsonDict:
        return {
            "kind": "inline",
            "name": self.name,
            "content": self.content,
            "format": self.format,
        }


@dataclass(frozen=True, slots=True)
class PathStructureSource:
    path: str | Path

    def __post_init__(self) -> None:
        if not isinstance(self.path, str | Path) or not str(self.path).strip():
            raise ValueError("PathStructureSource.path must be a non-empty path")

    def to_dict(self) -> JsonDict:
        return {"kind": "path", "path": str(self.path)}


@dataclass(frozen=True, slots=True)
class InMemoryStructureSource:
    structure: Structure

    def __post_init__(self) -> None:
        if not isinstance(self.structure, Structure):
            raise ValueError(
                "InMemoryStructureSource.structure must be a pymatgen Structure"
            )

    def to_dict(self) -> JsonDict:
        return {"kind": "in_memory", "structure": self.structure.as_dict()}


type StructureSource = (
    InlineStructureSource | PathStructureSource | InMemoryStructureSource
)


def _validate_format(format_hint: str | None) -> None:
    if format_hint is not None and format_hint not in ("cif", "poscar"):
        raise ValueError(
            f"Unsupported structure format {format_hint!r}; "
            "expected one of cif, poscar."
        )


@dataclass(frozen=True, slots=True)
class StructureSourceDocument:
    origin: Literal["inline", "path", "generated"]
    name: str
    format: str
    content: str | None
    sha256: str | None
    size_bytes: int | None

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class SpeciesOccupancy:
    symbol: str
    label: str
    occupancy: float
    oxidation_state: float | None = None

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class StructureSiteDocument:
    fractional_coordinates: Vector3
    cartesian_coordinates_angstrom: Vector3
    species: tuple[SpeciesOccupancy, ...]

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class LatticeDocument:
    vectors_angstrom: Matrix3
    lengths_angstrom: Vector3
    angles_degrees: Vector3
    volume_angstrom3: float

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class StructureDocument:
    schema_version: int
    formula: str
    reduced_formula: str
    site_count: int
    lattice: LatticeDocument
    periodicity: tuple[bool, bool, bool]
    sites: tuple[StructureSiteDocument, ...]

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class StructureInspection:
    source: StructureSourceDocument
    structure: StructureDocument
    canonical_cif: str
    schema_version: int = 1

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)
