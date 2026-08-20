from __future__ import annotations

from dataclasses import dataclass

from goldilocks_core.contracts.provenance import Provenance
from goldilocks_core.contracts.serial import to_jsonable
from goldilocks_core.contracts.types import JsonDict, KPointGrid, KPointShift


@dataclass(frozen=True, slots=True)
class KMeshEntry:
    """One indexed k-mesh entry produced from a structure scan.

    Used by the ML k-mesh advisor to map a predicted k-index to a
    concrete mesh.

    Attributes:
        k_index: 1-based index into the ordered k-mesh table.
        mesh: uniform k-point grid for this entry.
    """

    k_index: int
    mesh: KPointGrid


@dataclass(frozen=True, slots=True)
class KPointSelection:
    """Concrete k-point grid selected from hints or a model.

    Produced by the Kmesh stage from operator k-point hints or, when no
    hint is set, a model backend.

    Attributes:
        grid: uniform k-point grid (nk1, nk2, nk3).
        shift: Monkhorst-Pack shift (s1, s2, s3), currently
            always (0, 0, 0).
        mesh_type: mesh type label (e.g. ``monkhorst-pack``).
        provenance: how this grid was derived.
    """

    grid: KPointGrid
    shift: KPointShift
    mesh_type: str
    provenance: Provenance

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)
