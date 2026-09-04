from __future__ import annotations

import math

from pymatgen.core import Structure

from goldilocks_core.contracts import KMeshEntry


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
    max_kpoints_per_axis: int = 50,
) -> list[float]:
    """The k-distances at which any axis changes its k-point count.

    ``mesh_i = ceil(|b_i| / k_distance)`` steps from ``n`` to ``n + 1`` exactly
    at ``k_distance = |b_i| / n``, so those quotients are the only distances
    where the mesh can change.

    ``max_kpoints_per_axis`` bounds ``n``, i.e. how many k-points per axis are
    enumerated — it is *not* a bound on the number of rungs, which is roughly
    the number of distinct axis lengths times ``max_kpoints_per_axis``. Because
    the bound is applied per axis and the axes have different ``|b_i|``, they
    exhaust their quotients at different distances: the returned list is a
    complete set of change points only down to ``max(|b_i|) / n_max``. See
    ``_complete_meshes`` for what that implies."""
    reciprocal_lattice = structure.lattice.reciprocal_lattice
    reciprocal_lengths = (
        reciprocal_lattice.a,
        reciprocal_lattice.b,
        reciprocal_lattice.c,
    )

    candidates = {
        round(length / index, 8)
        for length in reciprocal_lengths
        for index in range(1, max_kpoints_per_axis + 1)
    }

    return sorted(candidates, reverse=True)


def build_kmesh_entries(
    structure: Structure,
    candidate_distances: list[float],
) -> list[KMeshEntry]:
    """Build the ordered k-mesh ladder for ``structure``.

    ``k_index`` is 0-based: rung 0 is the Γ-only ``(1, 1, 1)`` mesh, which the
    first probe at ``max(candidate_distances) + 1.0`` always yields because that
    distance exceeds every ``|b_i|``.

    The ladder is gap-free and non-repeating: consecutive rungs differ by one
    k-point on at least one axis, never skip a reachable mesh, and never name the
    same mesh twice."""
    meshes = _complete_meshes(structure, candidate_distances)
    return [KMeshEntry(k_index=index, mesh=mesh) for index, mesh in enumerate(meshes)]


def _complete_meshes(
    structure: Structure,
    candidate_distances: list[float],
) -> list[tuple[int, int, int]]:
    """Probe each interval between candidates, stopping at the first gap and
    skipping a mesh already on the ladder.

    Once the longest axis has used up its enumerated quotients, its count keeps
    rising but no candidate marks the change. Two adjacent candidates then span
    several meshes and probing the midpoint returns only one of them, so the
    rest are lost. An axis count rising by more than one between adjacent rungs
    is exactly that condition: a change point that should have been enumerated
    was not. Truncate there — a short complete ladder is usable, a long one with
    holes is not, and every k_index below the truncation is unaffected by where
    the enumeration happened to stop.

    Axes with equal ``|b_i|`` share their change points, so two consecutive
    intervals can yield the same mesh. Keeping both would give one mesh two
    k_index values, which contradicts a rung being the next denser mesh. Skip
    the repeat: the step to the following rung is still measured against the
    mesh actually probed, so a repeat never hides a gap."""
    meshes = _candidate_meshes(structure, candidate_distances)

    complete: list[tuple[int, int, int]] = []
    seen: set[tuple[int, int, int]] = set()
    previous: tuple[int, int, int] | None = None
    for current in meshes:
        if previous is not None and any(
            now - before > 1 for before, now in zip(previous, current, strict=True)
        ):
            break
        previous = current
        if current in seen:
            continue
        seen.add(current)
        complete.append(current)
    return complete


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
