from __future__ import annotations

from collections.abc import Callable

from pymatgen.core import Structure

from goldilocks_core.calculation import CalculationHints
from goldilocks_core.kmesh.math import k_distance_to_mesh
from goldilocks_core.provenance import Provenance
from goldilocks_core.types import JsonDict


class KPointSelection:
    """Marker for the k-point-selection record; the value is a dict.

    Keys: grid, shift, mesh_type, provenance.
    """


type KMeshAdvisor = Callable[[Structure], JsonDict]


def resolve_kpoints(
    structure: Structure,
    hints: CalculationHints,
    backend: KMeshAdvisor,
) -> JsonDict:
    """``k_grid`` wins over ``k_spacing``; both bypass the model backend.
    The model is only consulted when no hint is set."""
    if hints.k_grid is not None:
        warnings = (
            ("Both k_grid and k_spacing were provided; explicit grid wins.",)
            if hints.k_spacing is not None
            else ()
        )
        return {
            "grid": list(hints.k_grid),
            "shift": [0, 0, 0],
            "mesh_type": "monkhorst-pack",
            "provenance": Provenance(
                source="user_hint",
                reason="Use the operator-provided explicit k-point grid.",
                warnings=warnings,
            ),
        }

    if hints.k_spacing is not None:
        return {
            "grid": list(k_distance_to_mesh(structure, hints.k_spacing)),
            "shift": [0, 0, 0],
            "mesh_type": "monkhorst-pack",
            "provenance": Provenance(
                source="user_hint",
                reason="Use the operator-provided VASP-style k-point spacing.",
                data_source="pymatgen solid-state reciprocal lattice",
            ),
        }

    return backend(structure)


__all__ = ["KMeshAdvisor", "KPointSelection", "resolve_kpoints"]
