import math

from pymatgen.core import Lattice, Structure

from goldilocks_core.kmesh import (
    build_k_distance_intervals,
    build_kmesh_entries,
    generate_candidate_k_distances,
    k_distance_to_mesh,
)


def test_k_distance_to_mesh_returns_expected_uniform_mesh() -> None:
    """Convert a reciprocal-space distance into a uniform mesh."""
    structure = Structure(
        lattice=Lattice.cubic(3.5),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )

    mesh = k_distance_to_mesh(structure, k_distance=1.0)

    assert mesh == (2, 2, 2)


def test_k_distance_to_mesh_tracks_anisotropic_reciprocal_lengths() -> None:
    """Convert k-distance to a non-uniform mesh for anisotropic cells."""
    structure = Structure(
        lattice=Lattice.orthorhombic(3.0, 4.0, 6.0),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )

    mesh = k_distance_to_mesh(structure, k_distance=1.0)

    assert mesh == (3, 2, 2)


def test_k_distance_to_mesh_currently_ignores_force_parity() -> None:
    """Record that force_parity is currently accepted but not applied."""
    structure = Structure(
        lattice=Lattice.cubic(3.5),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )

    mesh = k_distance_to_mesh(structure, k_distance=1.0, force_parity=True)

    assert mesh == (2, 2, 2)


def test_generate_candidate_k_distances_returns_sorted_values() -> None:
    """Generate reciprocal-length-based candidate k-distances."""
    structure = Structure(
        lattice=Lattice.cubic(3.5),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )

    candidates = generate_candidate_k_distances(structure, max_index=3)

    reciprocal_length = structure.lattice.reciprocal_lattice.a

    assert len(candidates) > 0
    assert candidates == sorted(candidates, reverse=True)
    assert math.isclose(candidates[0], round(reciprocal_length / 1, 8))
    assert math.isclose(candidates[-1], round(reciprocal_length / 3, 8))


def test_build_k_distance_intervals_records_mesh_intervals() -> None:
    """Build k-distance intervals and their corresponding meshes."""
    structure = Structure(
        lattice=Lattice.cubic(3.5),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )

    candidates = generate_candidate_k_distances(structure, max_index=4)
    intervals = build_k_distance_intervals(structure, candidates)

    assert len(intervals) > 0
    assert intervals[0][0] == (1, 1, 1)
    assert math.isinf(intervals[0][1][1])
    assert any(mesh == (2, 2, 2) for mesh, _ in intervals)
    assert any(mesh == (3, 3, 3) for mesh, _ in intervals)
    assert any(mesh == (4, 4, 4) for mesh, _ in intervals)


def test_build_kmesh_entries_returns_indexed_entries() -> None:
    """Build indexed KMeshEntry objects from candidate k-distances."""
    structure = Structure(
        lattice=Lattice.cubic(3.5),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )

    candidates = generate_candidate_k_distances(structure, max_index=4)
    entries = build_kmesh_entries(structure, candidates)

    assert len(entries) > 0
    assert entries[0].k_index == 1
    assert entries[0].mesh == (1, 1, 1)
    assert math.isinf(entries[0].k_distance_interval[1])
    assert entries[0].k_pra == 1.0
    assert entries[0].n_reduced_kpoints == 1
    assert entries[0].k_line_density_interval is not None
