"""The phonon tasks' q-mesh against ph.x and on written cells, and the
first step's k-mesh raised against it (#215).

QE 7.3's PHonon example02 runs ph.x on zincblende AlAs at 4x4x4: it lists 8
q-points whose stars hold 1, 4, 4, 6, 12, 12, 3 and 6 points ("Number of q
in the star", ``PHonon/examples/example02/reference/alas.ph.out``), so the
small groups of q have 24, 6, 6, 4, 2, 2, 8 and 4 of the 24 operations, and
ph.x's work estimate, (3 nat + 1) nsym / nsymq summed over them, is 336.
The other cells are the written cells of ``tests/support.py``.
"""

from __future__ import annotations

import itertools

import numpy as np
import pytest
from pymatgen.core import Lattice, Species, Structure
from support import (
    aluminium_arsenide,
    strained,
    symmetric_strains,
    written_afm_hematite,
    written_afm_manganese_oxide,
    written_afm_nickel,
    written_afm_nickel_oxide,
    written_afm_uranium_dioxide,
    written_alpha_sulfur,
    written_alpha_uranium,
    written_bcc_iron,
    written_boron_nitride_monolayer,
    written_gallium_arsenide,
    written_lanthanum_cuprate,
    written_magnetic_cell,
    written_manganese_thiophosphate_monolayer,
    written_silicon,
    written_sodium_chloride,
)

from goldilocks_core.advisors.k_sampling import (
    KSamplingProtocol,
    PhononKProtocol,
    k_sampling,
)
from goldilocks_core.advisors.occupations import OccupationsDecision
from goldilocks_core.advisors.q_sampling import QSamplingHumanInput, q_sampling
from goldilocks_core.pw_symmetry import (
    PwRotations,
    irreducible_kpoint_count,
    irreducible_kpoints,
    mixing_axis_pairs,
    pw_rotations,
)
from goldilocks_core.resolution import Provenance, Resolved

pytestmark = pytest.mark.physics

_WRITTEN = [
    written_alpha_uranium,
    written_silicon,
    written_bcc_iron,
    written_sodium_chloride,
    written_gallium_arsenide,
    written_boron_nitride_monolayer,
    written_lanthanum_cuprate,
    written_manganese_thiophosphate_monolayer,
    written_alpha_sulfur,
    written_afm_nickel_oxide,
    written_afm_manganese_oxide,
    written_afm_nickel,
    written_afm_hematite,
    written_afm_uranium_dioxide,
]


def _name(value: object) -> str | None:
    return value.__name__ if callable(value) else None


def _actions(rotations: PwRotations) -> np.ndarray:
    """How each operation acts on reciprocal crystal coordinates, as QE's
    ``s`` does: W^T, negated for a time-reversed operation."""
    signs = np.where(rotations.time_reversed, -1, 1)
    return signs[:, None, None] * np.transpose(rotations.rotations, (0, 2, 1))


def _star(rotations: PwRotations, point: np.ndarray) -> set[tuple[float, ...]]:
    """The distinct images of ``point`` under the operations, modulo 1."""
    images = np.mod(_actions(rotations) @ point, 1.0)
    return {tuple(np.round(image, 8) % 1.0) for image in images}


def _orbit(
    rotations: PwRotations, index: tuple[int, ...], mesh: tuple[int, int, int]
) -> set[tuple[int, ...]]:
    """The mesh points the operations map the point ``index`` / ``mesh``
    onto, and their negatives when ``rotations.time_reversal``, as QE's
    ``kpoint_grid`` reduces a mesh, by their indices on the mesh."""
    counts = np.array(mesh)
    images = _actions(rotations) @ (np.array(index) / counts) * counts
    rounded = np.rint(images).astype(int)
    assert np.allclose(images, rounded), "the mesh is not mapped onto itself"
    if rotations.time_reversal:
        rounded = np.concatenate([rounded, -rounded])
    return {tuple(row) for row in np.mod(rounded, counts)}


def _maps_onto_itself(rotations: PwRotations, mesh: tuple[int, int, int]) -> bool:
    """Whether every operation takes each generator e_i / n_i of the
    Gamma-centred mesh to a point of the mesh."""
    counts = np.array(mesh)
    generators = np.diag(1.0 / counts)
    images = np.einsum("oij,jk->oik", _actions(rotations), generators) * counts[:, None]
    return bool(np.allclose(images, np.rint(images), atol=1e-9))


@pytest.mark.parametrize(
    "build", [aluminium_arsenide, written_gallium_arsenide], ids=_name
)
def test_zincblende_at_4x4x4_has_ph_x_s_q_points_and_work(build) -> None:
    structure = build()
    rotations = pw_rotations(structure)
    decision = q_sampling(
        written_magnetic_cell(structure), QSamplingHumanInput(q_grid=(4, 4, 4))
    ).value

    points = irreducible_kpoints(rotations, (4, 4, 4), (0, 0, 0))
    small_groups = sorted(
        len(rotations) // len(_star(rotations, point)) for point in points
    )

    assert len(rotations) == 24
    assert small_groups == [2, 2, 4, 4, 6, 6, 8, 24]
    assert (decision.n_irr_q, decision.work) == (8, 336)


@pytest.mark.parametrize(
    ("mesh", "n_irr_q", "work"), [((2, 2, 2), 3, 56), ((4, 4, 4), 8, 448)]
)
def test_silicon_counts_its_q_points_as_ph_x_does(
    mesh: tuple[int, int, int], n_irr_q: int, work: int
) -> None:
    """Diamond has inversion, so every q-point is in the star of an
    irreducible one: the work is 7 times the mesh's points."""
    decision = q_sampling(
        written_magnetic_cell(written_silicon()), QSamplingHumanInput(q_grid=mesh)
    ).value

    assert (decision.n_irr_q, decision.work) == (n_irr_q, work)


def _iron_cobalt() -> Structure:
    """B2 FeCo (a = 2.857 A), both atoms carrying a moment."""
    return Structure(
        Lattice.cubic(2.857),
        [Species("Fe", spin=1.0), Species("Co", spin=1.0)],
        [[0, 0, 0], [0.5, 0.5, 0.5]],
    )


@pytest.mark.parametrize(
    ("rotations", "mesh"),
    [
        (lambda: pw_rotations(written_alpha_uranium()), (9, 9, 5)),
        (lambda: pw_rotations(written_afm_nickel_oxide()), (9, 9, 9)),
        (lambda: pw_rotations(written_gallium_arsenide()), (6, 6, 6)),
        (lambda: pw_rotations(written_boron_nitride_monolayer()), (10, 10, 1)),
        (lambda: pw_rotations(written_afm_hematite()), (7, 7, 7)),
        (
            lambda: pw_rotations(_iron_cobalt(), np.array([0.0, 0.0, 1.0])),
            (6, 6, 6),
        ),
    ],
    ids=["alpha-uranium", "afm-nio", "gaas", "hbn", "afm-fe2o3", "feco-noncollinear"],
)
def test_the_irreducible_points_are_one_point_of_each_orbit(
    rotations, mesh: tuple[int, int, int]
) -> None:
    """spglib's orbits, counted as ``kpoint_grid`` counts them: each point
    returned lies on the mesh, their orbits do not overlap, and together
    they cover it. FeCo's moments along c make the run magnetic and
    noncollinear, where time-reversed operations act on q as -W^T and q is
    not paired with -q."""
    kept = rotations()
    points = irreducible_kpoints(kept, mesh, (0, 0, 0))
    indices = np.rint(points * np.array(mesh)).astype(int)

    assert np.allclose(points * np.array(mesh), indices)
    covered: set[tuple[int, ...]] = set()
    for index in indices:
        orbit = _orbit(kept, tuple(index), mesh)
        assert not orbit & covered
        covered |= orbit
    assert covered == set(itertools.product(*(range(n) for n in mesh)))
    assert irreducible_kpoint_count(kept, mesh, (0, 0, 0)) == len(points)


@pytest.mark.parametrize("build", _WRITTEN, ids=_name)
def test_default_meshes_stay_symmetric_on_written_cells_and_their_strains(
    build,
) -> None:
    """At 0.6, 0.3 and 0.2 1/A each mesh gives the axes a kept rotation
    mixes one count, so the rotations map it onto itself. A symmetric strain
    keeps the rotations as they are in the lattice basis, so the mesh a
    vc-relax-phonon run decides on the input cell stays symmetric on the
    relaxed one. With inversion, ph.x's work covers every q-point once."""
    structure = build()
    rotations = pw_rotations(structure)
    cell = written_magnetic_cell(structure)
    meshes = [
        q_sampling(cell, QSamplingHumanInput(q_distance=q_distance)).value
        for q_distance in (0.6, 0.3, 0.2)
    ]

    for decision in meshes:
        mesh = decision.mesh
        assert decision.refusal is None
        assert _maps_onto_itself(rotations, mesh)
        assert all(mesh[i] == mesh[j] for i, j in mixing_axis_pairs(rotations))
        if any(np.array_equal(w, -np.eye(3)) for w in rotations.rotations):
            assert decision.work == (3 * len(structure) + 1) * int(np.prod(mesh))
    kept = {w.tobytes() for w in rotations.rotations}
    for strain in symmetric_strains(structure, rotations):
        strained_rotations = pw_rotations(strained(structure, strain))
        assert {w.tobytes() for w in strained_rotations.rotations} == kept
        for decision in meshes:
            assert _maps_onto_itself(strained_rotations, decision.mesh)


_K_DISTANCES = (0.6, 0.5, 0.4, 0.3, 0.25, 0.2, 0.15, 0.12, 0.1)
"""1/A: the spacings a tier's k-mesh is swept over."""

_METAL = Resolved("metal", Provenance(source="heuristic"))


def _occupations(occupied: str) -> Resolved[OccupationsDecision]:
    decision = (
        OccupationsDecision("fixed", None, None)
        if occupied == "fixed"
        else OccupationsDecision("smearing", "cold", 0.01)
    )
    return Resolved(decision, Provenance(source="heuristic"))


def _raised_meshes(
    structure: Structure, q: QSamplingHumanInput | None = None
) -> list[tuple[str, tuple[int, int, int]]]:
    """The k-mesh of each spacing of the sweep on ``structure``, raised
    against the q-mesh of ``q``, with the occupations it was raised for."""
    return [
        (
            occupied,
            k_sampling(
                _METAL,
                structure,
                _occupations(occupied),
                protocol=KSamplingProtocol(k_distance, "A spacing of the sweep."),
                phonon=PhononKProtocol(q),
            ).value.mesh,
        )
        for occupied in ("smearing", "fixed")
        for k_distance in _K_DISTANCES
    ]


def _meets(occupied: str, mesh: tuple[int, ...], q: tuple[int, ...]) -> bool:
    """Whether ``mesh`` is what DFPT asks against the q-mesh ``q``: each
    axis a multiple of its q-axis under smearing, at least it under fixed
    occupations."""
    pairs = zip(mesh, q, strict=True)
    if occupied == "fixed":
        return all(k >= n for k, n in pairs)
    return all(k % n == 0 for k, n in pairs)


@pytest.mark.parametrize("build", _WRITTEN, ids=_name)
def test_raised_k_meshes_stay_symmetric_on_written_cells_and_their_strains(
    build,
) -> None:
    """The tiers' k-meshes and the default q-mesh give the axes a kept
    rotation mixes one count, and raising each axis by its own counts keeps
    them equal, so the rotations map every raised mesh onto itself, on the
    cell and on its symmetric strains: a vc-relax-phonon run keeps the mesh
    it decides on the input cell. Each mesh meets the q record's q-mesh."""
    structure = build()
    rotations = pw_rotations(structure)
    q = q_sampling(written_magnetic_cell(structure)).value.mesh
    raised = _raised_meshes(structure)

    for occupied, mesh in raised:
        assert _meets(occupied, mesh, q)
        assert _maps_onto_itself(rotations, mesh)
    for strain in symmetric_strains(structure, rotations):
        strained_rotations = pw_rotations(strained(structure, strain))
        for _, mesh in raised:
            assert _maps_onto_itself(strained_rotations, mesh)


def test_k_meshes_raised_against_every_accepted_q_grid_stay_symmetric() -> None:
    """alpha-U's kept rotations mix a and b, so of the request q_grids up to
    12x12x7, q_sampling accepts the 84 with equal counts there. Against each,
    the raised k-meshes meet the grid and stay symmetric, as 20x24x12, from
    17x17x9 against 4x8x4, would not."""
    structure = written_alpha_uranium()
    rotations = pw_rotations(structure)
    cell = written_magnetic_cell(structure)
    grids = [
        grid
        for grid in itertools.product(range(1, 13), range(1, 13), range(1, 8))
        if q_sampling(cell, QSamplingHumanInput(q_grid=grid)).value.refusal is None
    ]

    assert len(grids) == 84
    assert all(n1 == n2 for n1, n2, _ in grids)
    for grid in grids:
        for occupied, mesh in _raised_meshes(
            structure, QSamplingHumanInput(q_grid=grid)
        ):
            assert _meets(occupied, mesh, grid)
            assert _maps_onto_itself(rotations, mesh)
