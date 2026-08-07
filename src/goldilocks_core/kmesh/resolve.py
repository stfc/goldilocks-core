"""Resolve k-point hints into a mesh selection."""

from __future__ import annotations

from pymatgen.core import Structure

from goldilocks_core.contracts import (
    CalculationHints,
    KMeshAdvisor,
    KPointSelection,
    Provenance,
)
from goldilocks_core.kmesh.math import k_distance_to_mesh


def resolve_kpoints(
    structure: Structure,
    hints: CalculationHints,
    backend: KMeshAdvisor,
) -> KPointSelection:
    """Resolve operator k-point hints into a mesh, else delegate to a model.

    Explicit ``k_grid`` wins over ``k_spacing``; both beat the model backend.
    The model is only consulted when no hint is set, so hint-only requests
    never load a model.
    """
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


__all__ = ["resolve_kpoints"]
