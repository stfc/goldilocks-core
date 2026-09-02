from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pymatgen.core import Structure

from goldilocks_core.calculation import KmeshHints
from goldilocks_core.kmesh.math import k_distance_to_mesh
from goldilocks_core.provenance import Provenance
from goldilocks_core.serialization import to_jsonable
from goldilocks_core.types import JsonDict, KPointGrid, KPointShift


@dataclass(frozen=True, slots=True)
class KPointSelection:
    grid: KPointGrid
    shift: KPointShift
    mesh_type: str
    provenance: Provenance

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)


type KMeshAdvisor = Callable[[Structure], KPointSelection]


def resolve_kpoints(
    structure: Structure,
    hints: KmeshHints,
    backend: KMeshAdvisor,
) -> KPointSelection:
    """``k_grid`` wins over ``k_spacing``; both bypass the model backend.
    The model is only consulted when no hint is set."""
    if hints.k_grid is not None:
        warnings = (
            ("Both k_grid and k_spacing were provided; explicit grid wins.",)
            if hints.k_spacing is not None
            else ()
        )
        return KPointSelection(
            grid=hints.k_grid,
            shift=(0, 0, 0),
            mesh_type="monkhorst-pack",
            provenance=Provenance(
                source="user_hint",
                reason="Use the operator-provided explicit k-point grid.",
                warnings=warnings,
            ),
        )

    if hints.k_spacing is not None:
        return KPointSelection(
            grid=k_distance_to_mesh(structure, hints.k_spacing),
            shift=(0, 0, 0),
            mesh_type="monkhorst-pack",
            provenance=Provenance(
                source="user_hint",
                reason="Use the operator-provided VASP-style k-point spacing.",
                data_source="pymatgen solid-state reciprocal lattice",
            ),
        )

    return backend(structure)


__all__ = ["KMeshAdvisor", "KPointSelection", "resolve_kpoints"]
