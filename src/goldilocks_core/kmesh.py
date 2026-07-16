"""Utilities for converting between k-point representations."""

from __future__ import annotations

import math

from pymatgen.core import Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from goldilocks_core.contracts import (
    CalculationHints,
    KMeshEntry,
    KPointAdvice,
    KPointSelection,
    Provenance,
)


def resolve_kpoints_from_advice(
    structure: Structure,
    hints: CalculationHints,
    advice: KPointAdvice,
) -> KPointSelection:
    """Resolve k-point advice and hints into a concrete unshifted mesh."""
    if hints.k_grid is not None:
        return KPointSelection(
            grid=hints.k_grid,
            shift=(0, 0, 0),
            mesh_type=advice.mesh_type,
            provenance=Provenance(
                source="user_hint",
                reason="Use the operator-provided explicit k-point grid.",
                warnings=advice.provenance.warnings,
            ),
        )

    if hints.k_spacing is not None:
        return KPointSelection(
            grid=k_distance_to_mesh(structure, hints.k_spacing),
            shift=(0, 0, 0),
            mesh_type=advice.mesh_type,
            provenance=Provenance(
                source="user_hint",
                reason="Use the operator-provided VASP-style k-point spacing.",
                data_source="pymatgen solid-state reciprocal lattice",
                warnings=advice.provenance.warnings,
            ),
        )

    if advice.explicit_grid is not None:
        return KPointSelection(
            grid=advice.explicit_grid,
            shift=(0, 0, 0),
            mesh_type=advice.mesh_type,
            provenance=Provenance(
                source=advice.provenance.source,
                reason="Use the explicit grid from k-point advice.",
                data_source=advice.provenance.data_source,
                confidence=advice.provenance.confidence,
                warnings=advice.provenance.warnings,
            ),
        )

    # With KPointAdvice's exactly-one invariant, reaching here means spacing is set.
    return KPointSelection(
        grid=k_distance_to_mesh(structure, advice.spacing),
        shift=(0, 0, 0),
        mesh_type=advice.mesh_type,
        provenance=Provenance(
            source=advice.provenance.source,
            reason="Convert advised VASP-style k-point spacing into a mesh.",
            data_source="pymatgen solid-state reciprocal lattice",
            warnings=advice.provenance.warnings,
        ),
    )


def k_distance_to_mesh(
    structure: Structure,
    k_distance: float,
    *,
    force_parity: bool = False,
) -> tuple[int, int, int]:
    """Convert a reciprocal-space k-point distance into a uniform mesh.

    The distance is interpreted like VASP ``KSPACING``: the maximum spacing
    between adjacent k-points in units of 1/Angstrom. Mesh sizes are computed
    from solid-state reciprocal lattice lengths that include the 2π factor.

    Notes
    -----
    The current implementation computes the base mesh from reciprocal lattice
    lengths and does not yet apply the ``force_parity`` option.
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


def build_k_distance_intervals(
    structure: Structure,
    candidate_distances: list[float],
) -> list[tuple[tuple[int, int, int], tuple[float, float]]]:
    """Build finite k-distance intervals and their corresponding meshes.

    Notes
    -----
    The returned intervals include the top unbounded interval and the finite
    intervals between adjacent candidate k-distances. The lower tail below the
    smallest candidate distance is intentionally not included.
    """
    intervals: list[tuple[tuple[int, int, int], tuple[float, float]]] = []

    max_candidate = candidate_distances[0]
    top_probe = max_candidate + 1.0
    top_mesh = k_distance_to_mesh(structure, top_probe)
    intervals.append((top_mesh, (max_candidate, math.inf)))

    for upper, lower in zip(candidate_distances[:-1], candidate_distances[1:]):
        probe = 0.5 * (upper + lower)
        mesh = k_distance_to_mesh(structure, probe)
        intervals.append((mesh, (lower, upper)))

    return intervals


def mesh_to_k_line_density_interval(
    structure: Structure,
    mesh: tuple[int, int, int],
) -> tuple[float, float]:
    """Infer the admissible k-line-density interval for a mesh."""
    reciprocal_lattice = structure.lattice.reciprocal_lattice_crystallographic
    reciprocal_lengths = (
        reciprocal_lattice.a,
        reciprocal_lattice.b,
        reciprocal_lattice.c,
    )

    lower_bounds = [
        max(0.0, (n_k - 0.5) / b_length)
        for n_k, b_length in zip(mesh, reciprocal_lengths, strict=True)
    ]
    upper_bounds = [
        (n_k + 0.5) / b_length
        for n_k, b_length in zip(mesh, reciprocal_lengths, strict=True)
    ]

    lower = max(lower_bounds)
    upper = min(upper_bounds)

    if lower > upper:
        raise ValueError(
            "Mesh does not correspond to a valid scalar "
            f"k-line-density interval: {mesh}."
        )

    return (float(lower), float(upper))


def mesh_to_k_pra(
    structure: Structure,
    mesh: tuple[int, int, int],
) -> float:
    """Compute the k-points-per-reciprocal-atom value for a mesh."""
    n_atoms = len(structure)
    n_kpoints = mesh[0] * mesh[1] * mesh[2]

    return float(n_atoms * n_kpoints)


def mesh_to_n_reduced_kpoints(
    structure: Structure,
    mesh: tuple[int, int, int],
    *,
    is_shift: tuple[float, float, float] = (0, 0, 0),
) -> int:
    """Compute the number of symmetry-reduced k-points for a mesh."""
    sga = SpacegroupAnalyzer(structure)
    ir_kpoints = sga.get_ir_reciprocal_mesh(mesh=mesh, is_shift=is_shift)
    return len(ir_kpoints)


def build_kmesh_entries(
    structure: Structure,
    candidate_distances: list[float],
) -> list[KMeshEntry]:
    """Build indexed k-mesh entries from candidate k-distance values."""
    intervals = build_k_distance_intervals(structure, candidate_distances)
    entries: list[KMeshEntry] = []

    for index, (mesh, k_distance_interval) in enumerate(intervals, start=1):
        try:
            k_line_density_interval = mesh_to_k_line_density_interval(structure, mesh)
        except ValueError:
            k_line_density_interval = None

        lower, upper = k_distance_interval
        entries.append(
            KMeshEntry(
                k_index=index,
                mesh=mesh,
                n_reduced_kpoints=mesh_to_n_reduced_kpoints(structure, mesh),
                k_distance_interval=(lower, None if upper == math.inf else upper),
                k_line_density_interval=k_line_density_interval,
                k_pra=mesh_to_k_pra(structure, mesh),
            )
        )

    return entries
