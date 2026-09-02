from __future__ import annotations

import math
from dataclasses import dataclass

from pymatgen.core import Structure

from goldilocks_core.types import KPointGrid


@dataclass(frozen=True, slots=True)
class KMeshEntry:
    k_index: int
    mesh: KPointGrid


def k_distance_to_mesh(
    structure: Structure,
    k_distance: float,
) -> tuple[int, int, int]:
    """``k_distance`` is in Å⁻¹, VASP KSPACING convention:
    mesh = ceil(recip_length / k_distance),
    where recip_length includes the 2π factor."""
    reciprocal_lattice = structure.lattice.reciprocal_lattice
    reciprocal_lengths = (
        reciprocal_lattice.a,
        reciprocal_lattice.b,
        reciprocal_lattice.c,
    )

    mesh = tuple(
        max(1, math.ceil(round(length / k_distance, 5)))
        for length in reciprocal_lengths
    )

    return mesh


def generate_candidate_k_distances(
    structure: Structure,
    max_index: int = 30,
) -> list[float]:
    reciprocal_lattice = structure.lattice.reciprocal_lattice
    reciprocal_lengths = (
        reciprocal_lattice.a,
        reciprocal_lattice.b,
        reciprocal_lattice.c,
    )

    candidates = {
        round(length / index, 8)
        for length in reciprocal_lengths
        for index in range(1, max_index + 1)
    }

    return sorted(candidates, reverse=True)


def build_kmesh_entries(
    structure: Structure,
    candidate_distances: list[float],
) -> list[KMeshEntry]:
    meshes = _candidate_meshes(structure, candidate_distances)
    return [
        KMeshEntry(k_index=index, mesh=mesh)
        for index, mesh in enumerate(meshes, start=1)
    ]


def _candidate_meshes(
    structure: Structure,
    candidate_distances: list[float],
) -> list[tuple[int, int, int]]:
    max_candidate = candidate_distances[0]
    meshes: list[tuple[int, int, int]] = [
        k_distance_to_mesh(structure, max_candidate + 1.0)
    ]
    for upper, lower in zip(
        candidate_distances[:-1], candidate_distances[1:], strict=True
    ):
        meshes.append(k_distance_to_mesh(structure, 0.5 * (upper + lower)))
    return meshes
