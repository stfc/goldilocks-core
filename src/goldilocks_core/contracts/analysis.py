from __future__ import annotations

from dataclasses import dataclass

from goldilocks_core.contracts.serial import to_jsonable
from goldilocks_core.contracts.types import (
    Dimensionality,
    ElectronicCharacter,
    JsonDict,
)


@dataclass(frozen=True, slots=True)
class SymmetryUnavailable:
    reason: str


@dataclass(frozen=True, slots=True)
class StructureAnalysisRecord:
    formula: str
    reduced_formula: str
    site_count: int
    elements: tuple[str, ...]
    contains_transition_metals: bool
    contains_lanthanides: bool
    contains_actinides: bool
    contains_heavy_elements: bool
    magnetic_elements: tuple[str, ...]
    heavy_elements: tuple[str, ...]
    disorder_warnings: tuple[str, ...] = ()
    disordered_site_count: int = 0
    space_group_symbol: str | int | SymmetryUnavailable | None = None
    space_group_number: str | int | SymmetryUnavailable | None = None
    crystal_system: str | int | SymmetryUnavailable | None = None
    dimensionality: Dimensionality = "unknown"
    low_dimensional: bool = False
    electronic_character: ElectronicCharacter = "unknown"
    electronic_character_source: str = "heuristic"
    electronic_character_confidence: float | None = None
    analysis_warnings: tuple[str, ...] = ()

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)
