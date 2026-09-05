from __future__ import annotations

from dataclasses import dataclass

from goldilocks_core.contracts.provenance import Provenance
from goldilocks_core.contracts.serial import to_jsonable
from goldilocks_core.contracts.types import JsonDict, KPointGrid, KPointShift


@dataclass(frozen=True, slots=True)
class KMeshEntry:
    """One rung of a structure's ordered k-mesh ladder.

    ``k_index`` is 1-based: rung 1 is the Γ-only ``(1, 1, 1)`` mesh, and each
    step up is the next denser mesh the reciprocal lattice admits. A model
    trained against a 0-based record predicts a rung one lower than this
    ladder names, so the base belongs to the record and must be read from it.
    """

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
