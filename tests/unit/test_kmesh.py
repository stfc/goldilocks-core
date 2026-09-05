import math

from pymatgen.core import Lattice, Structure

from goldilocks_core.contracts import (
    KmeshHints,
    KPointSelection,
    Provenance,
)
from goldilocks_core.kmesh import resolve_kpoints
from goldilocks_core.kmesh.math import (
    build_kmesh_entries,
    generate_candidate_k_distances,
    k_distance_to_mesh,
)


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

    candidates = generate_candidate_k_distances(structure, max_kpoints_per_axis=3)

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

    candidates = generate_candidate_k_distances(structure, max_kpoints_per_axis=4)
    entries = build_kmesh_entries(structure, candidates)

    assert len(entries) > 0
    # Rung 1 is the Gamma-only mesh; the base is load-bearing for every
    # consumer that maps a predicted k-index onto this table.
    assert entries[0].k_index == 1
    assert entries[0].mesh == (1, 1, 1)
    assert entries[-1].k_index == len(entries)
    assert [entry.k_index for entry in entries] == list(range(1, len(entries) + 1))
    # On a cubic cell rung n is an n-point mesh on every axis, so the rung
    # and the count it names cannot drift apart unnoticed.
    assert all(entry.mesh == (entry.k_index,) * 3 for entry in entries)
    # The mesh ordering is load-bearing: the ML k-index maps onto this table.
    meshes = [entry.mesh for entry in entries]
    assert meshes == [(index, index, index) for index in range(1, len(entries) + 1)]


def test_ladder_is_gap_free_for_an_anisotropic_cell() -> None:
    # A cell whose axes differ enough that the long axis exhausts its
    # enumerated quotients while the short axis is still stepping.
    structure = Structure(
        lattice=Lattice.orthorhombic(2.0, 2.0, 8.0),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )

    candidates = generate_candidate_k_distances(structure, max_kpoints_per_axis=30)
    meshes = [entry.mesh for entry in build_kmesh_entries(structure, candidates)]

    assert len(meshes) > 1
    for before, after in zip(meshes[:-1], meshes[1:], strict=True):
        steps = [now - previous for previous, now in zip(before, after, strict=True)]
        # Denser by at least one k-point, and never skipping a reachable mesh.
        assert max(steps) == 1, f"{before} -> {after} skips a mesh"
        assert min(steps) >= 0, f"{before} -> {after} is not monotonic"


def test_raising_the_axis_cap_only_extends_the_ladder() -> None:
    # k_index is published and trained on, so a larger enumeration must never
    # renumber a rung that already existed.
    structure = Structure(
        lattice=Lattice.orthorhombic(2.0, 2.0, 8.0),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )

    short = [
        entry.mesh
        for entry in build_kmesh_entries(
            structure,
            generate_candidate_k_distances(structure, max_kpoints_per_axis=20),
        )
    ]
    long = [
        entry.mesh
        for entry in build_kmesh_entries(
            structure,
            generate_candidate_k_distances(structure, max_kpoints_per_axis=60),
        )
    ]

    assert len(long) > len(short)
    assert long[: len(short)] == short


def test_ladder_never_repeats_a_mesh_for_degenerate_axes() -> None:
    # Two equal reciprocal axes share their change points, so two consecutive
    # candidate intervals yield the same mesh. Keeping both would give one mesh
    # two k_index values. These lengths are those of MC3D 170541 (SiO2).
    structure = Structure(
        lattice=Lattice.from_parameters(
            a=8.9628, b=8.0389, c=8.9628, alpha=90.0, beta=90.0, gamma=90.0
        ),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )
    reciprocal = structure.lattice.reciprocal_lattice
    assert math.isclose(reciprocal.a, reciprocal.c)

    candidates = generate_candidate_k_distances(structure)
    meshes = [entry.mesh for entry in build_kmesh_entries(structure, candidates)]

    assert len(meshes) == len(set(meshes))
    assert meshes[:4] == [(1, 1, 1), (1, 2, 1), (2, 2, 2), (2, 3, 2)]


def test_a_repeated_mesh_does_not_hide_a_gap() -> None:
    # The step to the next rung is measured against the mesh actually probed,
    # not the last one kept, so skipping a repeat cannot mask a missing change
    # point. Every surviving transition is a single step on some axis.
    structure = Structure(
        lattice=Lattice.from_parameters(
            a=8.9628, b=8.0389, c=8.9628, alpha=90.0, beta=90.0, gamma=90.0
        ),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )

    candidates = generate_candidate_k_distances(structure)
    meshes = [entry.mesh for entry in build_kmesh_entries(structure, candidates)]

    for before, after in zip(meshes[:-1], meshes[1:], strict=True):
        steps = [now - previous for previous, now in zip(before, after, strict=True)]
        assert max(steps) == 1, f"{before} -> {after} skips a mesh"
        assert min(steps) >= 0, f"{before} -> {after} is not monotonic"
