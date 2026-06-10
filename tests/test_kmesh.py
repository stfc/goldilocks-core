import math

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.contracts import CalculationHints, KPointAdvice, Provenance
from goldilocks_core.kmesh import (
    build_k_distance_intervals,
    build_kmesh_entries,
    generate_candidate_k_distances,
    k_distance_to_mesh,
    resolve_kpoints_from_advice,
)


def test_resolve_kpoints_from_advice_prefers_explicit_grid_hint() -> None:
    """Use explicit operator grids before advice-derived spacing."""
    structure = Structure(
        lattice=Lattice.cubic(4.0),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )
    advice = KPointAdvice(
        spacing=0.2,
        explicit_grid=None,
        mesh_type="monkhorst-pack",
        provenance=Provenance(
            source="user_hint",
            reason="explicit grid",
            warnings=("Both k_grid and k_spacing were provided; explicit grid wins.",),
        ),
    )

    selection = resolve_kpoints_from_advice(
        structure,
        CalculationHints(k_grid=(2, 3, 4)),
        advice,
    )

    assert selection.grid == (2, 3, 4)
    assert selection.provenance.source == "user_hint"
    assert selection.provenance.warnings == (
        "Both k_grid and k_spacing were provided; explicit grid wins.",
    )


def test_resolve_kpoints_from_advice_converts_spacing_hint() -> None:
    """Convert operator k-spacing through the Kmesh stage."""
    structure = Structure(
        lattice=Lattice.cubic(4.0),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )
    advice = KPointAdvice(
        spacing=0.2,
        explicit_grid=None,
        mesh_type="monkhorst-pack",
        provenance=Provenance(source="default", reason="default"),
    )

    selection = resolve_kpoints_from_advice(
        structure,
        CalculationHints(k_spacing=0.25),
        advice,
    )

    assert selection.grid == (7, 7, 7)
    assert selection.provenance.source == "user_hint"


def test_resolve_kpoints_from_advice_converts_advised_spacing() -> None:
    """Convert default/advised spacing when no operator hint is set."""
    structure = Structure(
        lattice=Lattice.cubic(4.0),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )
    advice = KPointAdvice(
        spacing=0.25,
        explicit_grid=None,
        mesh_type="monkhorst-pack",
        provenance=Provenance(source="default", reason="default"),
    )

    selection = resolve_kpoints_from_advice(structure, CalculationHints(), advice)

    assert selection.grid == (7, 7, 7)
    assert selection.provenance.source == "default"


def test_resolve_kpoints_from_advice_rejects_empty_advice() -> None:
    """Require either explicit grid or spacing when no hint is set."""
    structure = Structure(
        lattice=Lattice.cubic(4.0),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )
    advice = KPointAdvice(
        spacing=None,
        explicit_grid=None,
        mesh_type="monkhorst-pack",
        provenance=Provenance(source="default", reason="default"),
    )

    with pytest.raises(ValueError, match="spacing or an explicit grid"):
        resolve_kpoints_from_advice(structure, CalculationHints(), advice)


def test_k_distance_to_mesh_matches_vasp_kspacing_for_cubic_cell() -> None:
    """Use solid-state reciprocal lengths for VASP-style k-spacing."""
    structure = Structure(
        lattice=Lattice.cubic(3.5),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )

    mesh = k_distance_to_mesh(structure, k_distance=1.0)

    assert mesh == (math.ceil(2 * math.pi / 3.5),) * 3


def test_k_distance_to_mesh_tracks_anisotropic_reciprocal_lengths() -> None:
    """Convert k-distance to a non-uniform mesh for anisotropic cells."""
    structure = Structure(
        lattice=Lattice.orthorhombic(3.0, 4.0, 6.0),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )

    mesh = k_distance_to_mesh(structure, k_distance=1.0)

    assert mesh == (
        math.ceil(2 * math.pi / 3.0),
        math.ceil(2 * math.pi / 4.0),
        math.ceil(2 * math.pi / 6.0),
    )


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
