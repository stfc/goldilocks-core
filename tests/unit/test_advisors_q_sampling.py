"""The phonon tasks' q-mesh (#215): the mesh, its provenance, the meshes ph.x
or q2r.x would refuse, and the irreducible q-points and ph.x's work estimate
it records. QE's reference counts and the meshes' invariance on every
embedded written cell and under strain are in
``tests/physics/test_phonon_sampling.py``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from support import (
    alpha_uranium,
    carbon_pair_in_a_box,
    framed_magnetic_cell,
    graphene_monolayer,
    mc3d_42058_silicon,
    tilted_straddling_molybdenum_disulfide,
    written_afm_nickel_oxide,
    written_magnetic_cell,
)

from goldilocks_core.advisors.q_sampling import (
    GRID_AND_DISTANCE_WARNING,
    Q_DISTANCE,
    QSamplingDecision,
    QSamplingHumanInput,
    q_sampling,
)
from goldilocks_core.resolution import Blocked, FieldState, Resolved


def _decision(state: FieldState[QSamplingDecision]) -> QSamplingDecision:
    assert isinstance(state, Resolved), state
    return state.value


def _alpha_uranium(q_grid=None, q_distance=None) -> QSamplingDecision:
    human = QSamplingHumanInput(q_grid=q_grid, q_distance=q_distance)
    return _decision(q_sampling(framed_magnetic_cell(alpha_uranium()), human))


@pytest.mark.parametrize(
    ("cell", "mesh", "n_irr_q", "work"),
    [
        (lambda: framed_magnetic_cell(mc3d_42058_silicon()), (7, 7, 7), 20, 2401),
        (lambda: framed_magnetic_cell(alpha_uranium()), (9, 9, 5), 75, 2835),
        (lambda: framed_magnetic_cell(graphene_monolayer()), (10, 10, 1), 14, 700),
        (
            lambda: written_magnetic_cell(written_afm_nickel_oxide()),
            (9, 9, 9),
            85,
            9477,
        ),
        (lambda: framed_magnetic_cell(carbon_pair_in_a_box()), (1, 1, 1), 1, 7),
    ],
    ids=["silicon", "alpha-uranium", "graphene", "afm-nio", "box"],
)
def test_the_default_mesh_records_its_q_points_and_ph_x_s_work(
    cell, mesh: tuple[int, int, int], n_irr_q: int, work: int
) -> None:
    """0.3 1/A on the written cell, one division along each vacuum axis.
    The work is ph.x's own estimate in scf runs, (3 nat + 1) nsym / nsymq
    summed over the irreducible q-points: with inversion every q-point of
    the mesh is in the star of one of them, so it is (3 nat + 1) times the
    mesh's points here (7 x 343 for Si, 13 x 729 for AFM NiO)."""
    decision = _decision(q_sampling(cell()))

    assert decision.mesh == mesh
    assert decision.q_distance == Q_DISTANCE == 0.3
    assert (decision.n_irr_q, decision.work) == (n_irr_q, work)
    assert decision.refusal is None
    assert decision.warnings == ()


@pytest.mark.parametrize(("q_distance", "mesh"), [(0.6, (5, 5, 3)), (0.2, (13, 13, 7))])
def test_alpha_uranium_gets_one_count_on_the_axes_its_mirror_mixes(
    q_distance: float, mesh: tuple[int, int, int]
) -> None:
    """Its mirror turns a_2 into a_1 + a_2, and the reciprocal lengths of
    a and b differ (2.509 and 2.148 1/A): each takes the count of the
    longer, so the mesh is one the mirror maps onto itself."""
    decision = _alpha_uranium(q_distance=q_distance)

    assert decision.mesh == mesh
    assert decision.q_distance == q_distance
    assert decision.refusal is None


def test_a_q_grid_ph_x_would_refuse_is_refused_with_ph_x_s_reason() -> None:
    """9x8x5 is the per-axis count of 0.3 1/A on alpha-U. The mirror takes
    the q-point (1/9, 0, 0) to (1/9, 1/9, 0), which has no place on 8
    divisions of b, and ph.x stops."""
    decision = _alpha_uranium(q_grid=(9, 8, 5))

    assert decision.mesh == (9, 8, 5)
    assert decision.q_distance is None
    assert decision.refusal is not None
    assert decision.refusal.kind == "breaks_symmetry"
    cause = decision.refusal.cause
    assert "q_grid 9x8x5" in cause
    assert "8 symmetry operations" in cause
    assert "'q-mesh breaks symmetry'" in cause
    assert (decision.n_irr_q, decision.work) == (None, None)


def test_a_q_grid_with_unequal_counts_on_mixed_axes_is_refused() -> None:
    """ph.x accepts 4x8x4 on alpha-U (4 divides 8), but a smearing run's
    k-mesh, raised to multiples of it, can lose the mirror: 17x17x9 would
    become 20x24x12."""
    decision = _alpha_uranium(q_grid=(4, 8, 4))

    assert decision.refusal is not None
    assert decision.refusal.kind == "breaks_symmetry"
    cause = decision.refusal.cause
    assert "axes a and b" in cause
    assert "8x8x4" in cause
    assert (decision.n_irr_q, decision.work) == (None, None)


@pytest.mark.parametrize("q_grid", [(8, 8, 4), (9, 9, 5)])
def test_a_symmetric_q_grid_is_kept(q_grid: tuple[int, int, int]) -> None:
    decision = _alpha_uranium(q_grid=q_grid)

    assert decision.mesh == q_grid
    assert decision.refusal is None
    assert decision.n_irr_q is not None and decision.work is not None


def test_a_per_axis_q_grid_on_the_afm_nickel_oxide_cell_is_refused() -> None:
    """The AFM cell's b is 5.01 A against 2.89 A for a and c, so a per-axis
    count of 0.3 1/A would give 9x5x9, which its rotations do not map onto
    itself."""
    decision = _decision(
        q_sampling(
            written_magnetic_cell(written_afm_nickel_oxide()),
            QSamplingHumanInput(q_grid=(9, 5, 9)),
        )
    )

    assert decision.refusal is not None
    assert decision.refusal.kind == "breaks_symmetry"
    assert "'q-mesh breaks symmetry'" in decision.refusal.cause


@pytest.mark.parametrize(
    ("q_grid", "words"),
    [((10, 10, 2), "2 divisions along vacuum axis c"), ((10, 9, 1), "q_grid 10x9x1")],
    ids=["vacuum-axis", "asymmetric"],
)
def test_a_q_grid_on_graphene_needs_one_division_along_its_vacuum(
    q_grid: tuple[int, int, int], words: str
) -> None:
    decision = _decision(
        q_sampling(
            framed_magnetic_cell(graphene_monolayer()),
            QSamplingHumanInput(q_grid=q_grid),
        )
    )

    assert decision.refusal is not None
    assert decision.refusal.kind == "breaks_symmetry"
    assert words in decision.refusal.cause


def test_q_grid_wins_over_q_distance_with_a_notice() -> None:
    state = q_sampling(
        framed_magnetic_cell(mc3d_42058_silicon()),
        QSamplingHumanInput(q_grid=(4, 4, 4), q_distance=0.2),
    )
    decision = _decision(state)

    assert decision.mesh == (4, 4, 4)
    assert decision.q_distance is None
    assert decision.warnings == (GRID_AND_DISTANCE_WARNING,)
    assert state.provenance.source == "human"
    assert state.provenance.field_sources == {"q_grid": "human"}


def test_the_default_names_its_protocol_and_a_request_reads_human() -> None:
    cell = framed_magnetic_cell(mc3d_42058_silicon())

    default = q_sampling(cell)
    requested = q_sampling(cell, QSamplingHumanInput(q_distance=0.6))

    assert default.provenance.field_sources == {"q_distance": "heuristic"}
    assert default.provenance.derived_from == ("magnetic",)
    assert "aiida-quantumespresso" in default.provenance.source_note
    assert "balanced" in default.provenance.source_note
    assert requested.provenance.field_sources == {"q_distance": "human"}
    assert requested.provenance.source_note is None
    assert _decision(requested).mesh == (4, 4, 4)


def test_a_mesh_with_more_q_points_than_q2r_x_reads_is_refused_after_counting() -> None:
    """q2r.x reads one dynamical-matrix file per irreducible q-point, at most
    1024 (QE 7.3 PHonon/PH/do_q2r.f90:138-139)."""
    decision = _alpha_uranium(q_distance=0.1)

    assert decision.mesh == (26, 26, 13)
    assert decision.refusal is not None
    assert decision.refusal.kind == "too_many_q_points"
    assert "1281 irreducible q-points" in decision.refusal.cause
    assert "1024" in decision.refusal.cause
    assert (decision.n_irr_q, decision.work) == (1281, None)


def test_a_mesh_far_beyond_q2r_x_s_limit_is_refused_without_counting() -> None:
    """Every orbit has at most 48 q-points, so a mesh of more than 48 x 1024
    points has more than 1024 irreducible ones."""
    decision = _decision(
        q_sampling(
            framed_magnetic_cell(mc3d_42058_silicon()),
            QSamplingHumanInput(q_distance=0.02),
        )
    )

    assert decision.mesh == (101, 101, 101)
    assert decision.refusal is not None
    assert decision.refusal.kind == "too_many_q_points"
    assert "1030301 points" in decision.refusal.cause
    assert (decision.n_irr_q, decision.work) == (None, None)


@pytest.mark.parametrize("q_grid", [(1025, 1, 1), (64, 64, 64)], ids=["axis", "points"])
def test_a_q_grid_beyond_q2r_x_s_limits_is_refused_at_input(
    q_grid: tuple[int, int, int],
) -> None:
    with pytest.raises(ValidationError):
        QSamplingHumanInput(q_grid=q_grid)


def test_the_q_grid_limit_names_q2r_x() -> None:
    with pytest.raises(ValidationError, match=r"q2r\.x"):
        QSamplingHumanInput(q_grid=(64, 64, 64))


def test_a_slab_whose_c_leans_off_its_normal_has_no_symmetric_mesh() -> None:
    """The written cell keeps c leaning (1.58, 0.912) A off the sheet's
    normal, and pw.x keeps rotations that turn c into c plus an in-plane
    lattice vector: the 8x8x1 mesh is not mapped onto itself, and no remedy
    of the q settings gives a symmetric one."""
    state = q_sampling(framed_magnetic_cell(tilted_straddling_molybdenum_disulfide()))

    assert isinstance(state, Blocked)
    cause = state.root_cause()
    assert "8x8x1" in cause
    assert "'q-mesh breaks symmetry'" in cause
    assert "vacuum axis c" in cause


def test_an_unresolved_cell_blocks_the_mesh() -> None:
    state = q_sampling(Blocked(by="no written cell"))

    assert isinstance(state, Blocked)
    assert state.root_cause() == "no written cell"
