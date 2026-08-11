"""Pure k-point grid math: mesh, k-distance, and density conversions."""

from __future__ import annotations

import math

from pymatgen.core import Structure

from goldilocks_core.contracts import KMeshEntry


def k_distance_to_mesh(
    structure: Structure,
    k_distance: float,
) -> tuple[int, int, int]:
    """Convert a reciprocal-space k-point distance into a uniform mesh.

    The distance is interpreted like VASP ``KSPACING``: the maximum spacing
    between adjacent k-points in units of 1/Angstrom. Mesh sizes are computed
    from solid-state reciprocal lattice lengths that include the 2π factor.
    """
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
    """Generate VASP-style k-distance candidates from reciprocal lengths."""
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
    """Build indexed ``(k_index, mesh)`` entries from candidate k-distance values.

    The ML k-mesh advisor maps a predicted k-index onto this table, so the
    mesh ordering must stay stable: the top interval (above the largest
    candidate) probes just above the max, and each lower interval probes the
    midpoint of its adjacent candidates.
    """
    meshes = _candidate_meshes(structure, candidate_distances)
    return [
        KMeshEntry(k_index=index, mesh=mesh)
        for index, mesh in enumerate(meshes, start=1)
    ]


def _candidate_meshes(
    structure: Structure,
    candidate_distances: list[float],
) -> list[tuple[int, int, int]]:
    """Return the ordered uniform meshes for the k-distance intervals."""
    max_candidate = candidate_distances[0]
    meshes: list[tuple[int, int, int]] = [
        k_distance_to_mesh(structure, max_candidate + 1.0)
    ]
    for upper, lower in zip(
        candidate_distances[:-1], candidate_distances[1:], strict=True
    ):
        meshes.append(k_distance_to_mesh(structure, 0.5 * (upper + lower)))
    return meshes
