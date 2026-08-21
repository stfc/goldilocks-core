from __future__ import annotations

from dataclasses import dataclass

from goldilocks_core.contracts.serial import to_jsonable
from goldilocks_core.contracts.types import JsonDict

Vector3 = tuple[float, float, float]
Matrix3 = tuple[Vector3, Vector3, Vector3]


@dataclass(frozen=True, slots=True)
class StructureSourceDocument:
    name: str
    format: str
    sha256: str
    size_bytes: int

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
    source: StructureSourceDocument
    formula: str
    reduced_formula: str
    site_count: int
    lattice: LatticeDocument
    periodicity: tuple[bool, bool, bool]
    sites: tuple[StructureSiteDocument, ...]

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)
