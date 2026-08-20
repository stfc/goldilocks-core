from __future__ import annotations

from dataclasses import dataclass

from goldilocks_core.contracts.provenance import Provenance
from goldilocks_core.contracts.serial import to_jsonable
from goldilocks_core.contracts.types import JsonDict, KPointGrid, KPointShift


@dataclass(frozen=True, slots=True)
class KMeshEntry:
    k_index: int
    mesh: KPointGrid


@dataclass(frozen=True, slots=True)
class KPointSelection:
    grid: KPointGrid
    shift: KPointShift
    mesh_type: str
    provenance: Provenance

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)
