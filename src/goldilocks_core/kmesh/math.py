from __future__ import annotations

import itertools
import math

from pymatgen.core import Structure

from goldilocks_core.types import KPointGrid


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

    return tuple(
        max(1, math.ceil(round(length / k_distance, 5)))
        for length in reciprocal_lengths
    )


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
) -> list[tuple[int, KPointGrid]]:
    meshes = _candidate_meshes(structure, candidate_distances)
    return list(enumerate(meshes, start=1))


def _candidate_meshes(
    structure: Structure,
    candidate_distances: list[float],
) -> list[tuple[int, int, int]]:
    max_candidate = candidate_distances[0]
    meshes: list[tuple[int, int, int]] = [
        k_distance_to_mesh(structure, max_candidate + 1.0)
    ]
    meshes.extend(
        k_distance_to_mesh(structure, 0.5 * (upper + lower))
        for upper, lower in itertools.pairwise(candidate_distances)
    )
    return meshes
