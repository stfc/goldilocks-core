import math

from pymatgen.core import Lattice, Structure

from goldilocks_core.calculation import KmeshHints
from goldilocks_core.kmesh.math import (
    build_kmesh_entries,
    generate_candidate_k_distances,
    k_distance_to_mesh,
)
from goldilocks_core.kmesh.resolve import KPointSelection, resolve_kpoints
from goldilocks_core.provenance import Provenance


def _fail_backend(structure: Structure) -> KPointSelection:
    raise AssertionError("k-point backend should not be called when hints are set")


def test_resolve_kpoints_prefers_explicit_grid_hint() -> None:
    structure = Structure(
        lattice=Lattice.cubic(4.0),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )

    selection = resolve_kpoints(
        structure,
        KmeshHints(k_grid=(2, 3, 4), k_spacing=0.25),
        _fail_backend,
    )

    assert selection.grid == (2, 3, 4)
    assert selection.shift == (0, 0, 0)
    assert selection.mesh_type == "monkhorst-pack"
    assert selection.provenance.source == "user_hint"
    assert selection.provenance.data_source is None
    assert selection.provenance.warnings == (
        "Both k_grid and k_spacing were provided; explicit grid wins.",
    )


def test_resolve_kpoints_converts_spacing_hint() -> None:
    structure = Structure(
        lattice=Lattice.cubic(4.0),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )

    selection = resolve_kpoints(
        structure,
        KmeshHints(k_spacing=0.25),
        _fail_backend,
    )

    assert selection.grid == (7, 7, 7)
    assert selection.shift == (0, 0, 0)
    assert selection.mesh_type == "monkhorst-pack"
    assert selection.provenance.source == "user_hint"
    assert selection.provenance.data_source == (
        "pymatgen solid-state reciprocal lattice"
    )


def test_resolve_kpoints_consults_backend_without_hints() -> None:
    structure = Structure(
        lattice=Lattice.cubic(4.0),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )

    def backend(structure: Structure) -> KPointSelection:
        return KPointSelection(
            grid=(5, 5, 5),
            shift=(0, 0, 0),
            mesh_type="monkhorst-pack",
            provenance=Provenance(source="model", reason="stub"),
        )

    selection = resolve_kpoints(structure, KmeshHints(), backend)

    assert selection.grid == (5, 5, 5)
    assert selection.provenance.source == "model"


def test_k_distance_to_mesh_matches_vasp_kspacing_for_cubic_cell() -> None:
    structure = Structure(
        lattice=Lattice.cubic(3.5),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )

    mesh = k_distance_to_mesh(structure, k_distance=1.0)

    assert mesh == (math.ceil(2 * math.pi / 3.5),) * 3


def test_k_distance_to_mesh_tracks_anisotropic_reciprocal_lengths() -> None:
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


def test_build_kmesh_entries_returns_indexed_mesh_entries() -> None:
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
    assert entries[-1].k_index == len(entries)
    # The mesh ordering is load-bearing: the ML k-index maps onto this table.
    meshes = [entry.mesh for entry in entries]
    assert meshes == [(index, index, index) for index in range(1, len(entries) + 1)]
