from __future__ import annotations

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.advisors.magnetic_config import (
    MagneticConfigFacts,
    OrderingRecord,
)
from goldilocks_core.advisors.parallelisation import (
    WARNING_CATALOGUE,
    ParallelisationHumanInput,
    best_npool,
    diag_grid_side,
    kpoint_spin_pairs,
    parallelisation,
    qe_spin_layout,
)

_NTASKS = 128
_UNEVEN = ["parallelisation.npool_load_imbalance"]


def _magnetic(*, spin_polarized: bool, spin_orbit_enabled: bool) -> MagneticConfigFacts:
    feco = Structure(
        Lattice.cubic(2.857), ["Fe", "Co"], [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]]
    )
    return MagneticConfigFacts(
        cell=feco,
        ordering=OrderingRecord(
            requested=None, applied="fm" if spin_polarized else None
        ),
        spin_polarized=spin_polarized,
        magnetic_elements=("Co", "Fe") if spin_polarized else (),
        starting_magnetization={"Fe": 0.3, "Co": 0.2} if spin_polarized else None,
        compensated=False,
        tot_magnetization=None,
        spin_orbit_enabled=spin_orbit_enabled,
        angle1=None,
        angle2=None,
    )


def _codes(state) -> list[str]:
    return [warning.code for warning in state.value.warnings]


@pytest.mark.parametrize(
    ("spin_polarized", "spin_orbit_enabled", "layout", "pairs"),
    [
        (False, False, (1, 1, 1), 6),
        (True, False, (2, 1, 2), 12),
        (False, True, (4, 2, 1), 6),
        (True, True, (4, 2, 4), 6),
    ],
)
def test_only_collinear_spin_doubles_the_k_points_pw_x_distributes(
    spin_polarized: bool,
    spin_orbit_enabled: bool,
    layout: tuple[int, int, int],
    pairs: int,
) -> None:
    """Regression for #168: pw.x holds every k-point once per spin for
    collinear nspin=2 (QE 7.3 PW/src/setup.f90:617 doubles nkstot), so
    pools share 2 x n_irr_k pairs. Spin-orbit runs are noncollinear
    (nspin=4, spinors) with one entry per k-point, magnetic or not; only
    a magnetic one has four magnetization components (nspin_mag,
    set_spin_vars.f90:29-41, #148)."""
    magnetic = _magnetic(
        spin_polarized=spin_polarized, spin_orbit_enabled=spin_orbit_enabled
    )

    assert qe_spin_layout(magnetic) == layout
    assert kpoint_spin_pairs(6, magnetic) == pairs


def test_npool_prefers_a_divisor_of_both_ntasks_and_the_pairs() -> None:
    state = parallelisation(_NTASKS, 32)

    assert state.ok
    assert 128 % state.value.npool == 0
    assert 32 % state.value.npool == 0
    assert state.value.npool == 32


@pytest.mark.parametrize(
    ("n_kpoint_spin", "npool", "codes"),
    [
        (12, 4, []),  # Nd2Fe14B (mp-5182): 6 k-points x 2 spins, 3 per pool
        (48, 16, []),  # MnSi B20 (mc3d-50763): 32 pools leave 16 of 64 slots idle
        (112, 64, _UNEVEN),  # FeCo B2 (mc3d-60258): 56 k-points x 2 spins
        (84, 32, _UNEVEN),  # 64 pools would run 2 rounds of 64 slots for 84
        (50, 8, _UNEVEN),  # 32 and 16 pools would both need 64 slots for 50
        (6, 2, []),  # 4 pools would leave 2 of 8 slots idle
    ],
)
def test_npool_is_the_most_pools_that_keep_the_pairs_evenly_loaded(
    n_kpoint_spin: int, npool: int, codes: list[str]
) -> None:
    """#168: more pools than this would leave over a fifth of the pool
    slots idle; a cap at N alone gave MnSi 32 pools, which SCARF ran
    slower than 16."""
    state = parallelisation(64, n_kpoint_spin)

    assert state.source == "heuristic"
    assert state.value.npool == npool
    assert state.value.kpoint_spin_pairs == n_kpoint_spin
    assert _codes(state) == codes


def test_slots_exactly_a_quarter_over_the_pairs_are_still_accepted() -> None:
    # 20 tasks, 16 pairs: 10 pools run 2 rounds of 10 slots, exactly
    # 1.25 x 16; the next divisor down, 5, needs 20 slots as well.
    assert best_npool(20, 16) == 10


def test_npool_names_the_pairs_and_the_pools_that_take_one_more() -> None:
    """pw.x gives the remainder to the first pools
    (PW/src/divide_et_impera.f90:49-56): 47 pairs over 16 pools leave
    15 pools with 3 pairs and one with 2."""
    state = parallelisation(64, 47)

    assert state.value.npool == 16
    (note,) = state.value.warnings
    assert note.code == "parallelisation.npool_load_imbalance"
    assert note.level == "info"
    assert note.message == (
        "npool=16 does not divide the 47 k-point/spin pairs evenly; the "
        "first 15 pool(s) handle one more pair than the rest."
    )


def test_npool_takes_two_pools_for_five_pairs_rather_than_four() -> None:
    # ntasks=128's divisors <= 5 are 1, 2, 4; four pools would run two
    # rounds for 5 pairs (8 slots, 3 idle), two pools three rounds (6).
    state = parallelisation(_NTASKS, 5)

    assert state.value.npool == 2
    (note,) = state.value.warnings
    assert note.code == "parallelisation.npool_load_imbalance"
    assert "the 5 k-point/spin pairs" in note.message
    assert "first 1 pool(s)" in note.message


def test_npool_never_exceeds_the_pairs_even_if_that_means_less_parallelism() -> None:
    # One pair (Gamma only, no collinear spin): the only valid divisor
    # of ntasks that is <= 1 is 1 itself, so npool=1 with no warning.
    state = parallelisation(_NTASKS, 1)

    assert state.value.npool == 1
    assert state.value.warnings == ()


@pytest.mark.parametrize("ntasks", [1, 2, 20, 24, 40, 64, 96, 128, 192])
def test_default_npool_divides_ntasks_and_never_idles_a_pool(ntasks: int) -> None:
    for pairs in range(1, 400):
        npool = best_npool(ntasks, pairs)

        assert ntasks % npool == 0
        assert npool <= pairs
        assert -(-pairs // npool) * npool <= 1.25 * pairs


@pytest.mark.parametrize(
    ("ntasks", "n_kpoint_spin"),
    [(64, 1), (64, 6), (128, 32)],
)
def test_ndiag_is_left_to_pw_x_by_default(ntasks: int, n_kpoint_spin: int) -> None:
    """Regression for #133: with ScaLAPACK the default was the largest
    square <= ntasks/npool (-ndiag 64 for a Gamma-only run on one node,
    -ndiag 16 with npool 4), whatever nbnd was, which aborted or hung
    pw.x for small band counts. Unset, pw.x picks it from nbnd."""
    state = parallelisation(ntasks, n_kpoint_spin)

    assert state.value.ndiag is None
    assert state.source == "heuristic"
    assert not any("ndiag" in warning.code for warning in state.value.warnings)


def test_nimage_is_always_none() -> None:
    state = parallelisation(_NTASKS, 32)

    assert state.value.nimage is None


def test_human_npool_override_is_honored() -> None:
    state = parallelisation(_NTASKS, 32, ParallelisationHumanInput(npool=4))

    assert state.value.npool == 4
    assert state.value.warnings == ()
    assert state.source == "human"


def test_human_npool_that_does_not_divide_ntasks_warns() -> None:
    state = parallelisation(_NTASKS, 32, ParallelisationHumanInput(npool=5))

    assert state.value.npool == 5
    assert _codes(state) == ["parallelisation.npool_does_not_divide_ntasks"]
    assert "refuse" in state.value.warnings[0].message


@pytest.mark.parametrize(("npool", "n_kpoint_spin"), [(8, 12), (16, 16)])
def test_human_npool_within_the_pairs_has_no_idle_pool(
    npool: int, n_kpoint_spin: int
) -> None:
    """Regression for #168: Nd2Fe14B at -npool 8 has 12 pairs, which
    pw.x spreads over all 8 pools; the warning used to count the 6
    k-points and report 2 idle pools."""
    state = parallelisation(64, n_kpoint_spin, ParallelisationHumanInput(npool=npool))

    assert state.value.npool == npool
    assert state.value.kpoint_spin_pairs == n_kpoint_spin
    assert state.value.warnings == ()


def test_human_npool_exceeding_the_pairs_warns_about_real_idle_pools() -> None:
    state = parallelisation(64, 12, ParallelisationHumanInput(npool=16))

    assert state.value.npool == 16
    (warning,) = state.value.warnings
    assert warning.code == "parallelisation.npool_exceeds_kpoints"
    assert warning.level == "warning"
    assert warning.message == (
        "npool=16 exceeds the 12 k-point/spin pairs pw.x distributes; 4 "
        "pool(s) will have no k-point to work on."
    )


def test_human_square_ndiag_is_kept_without_notes() -> None:
    state = parallelisation(_NTASKS, 32, ParallelisationHumanInput(ndiag=16))

    assert state.value.ndiag == 16
    assert state.value.npool == 32
    assert state.value.warnings == ()
    assert state.source == "human"


def test_human_ndiag_that_is_not_a_square_integer_gets_an_info_note() -> None:
    """pw.x never rejects a non-square ndiag; it silently runs the
    largest square grid that fits (#133 corrected the old "may be
    rejected" wording)."""
    state = parallelisation(_NTASKS, 1, ParallelisationHumanInput(ndiag=10))

    assert state.value.ndiag == 10
    (note,) = state.value.warnings
    assert note.code == "parallelisation.ndiag_not_a_square_integer"
    assert note.level == "info"
    assert "ndiag=10" in note.message
    assert "3x3" in note.message


def test_non_square_note_names_the_grid_capped_by_processes_per_pool() -> None:
    # 128 tasks in 32 pools leave 4 processes per pool: a 2x2 grid.
    state = parallelisation(_NTASKS, 32, ParallelisationHumanInput(ndiag=10))

    (note,) = state.value.warnings
    assert "2x2" in note.message


@pytest.mark.parametrize(
    ("ndiag", "procs_per_pool", "side"),
    [
        (10, 128, 3),  # non-square ndiag: the largest square below it
        (64, 4, 2),  # capped by the processes in the pool
        (64, 64, 8),
        (16, 16, 4),
        (15, 64, 3),
        (1, 64, 1),
        (16, 3, 1),
        (4, 0, 1),  # npool > ntasks: LAXlib still uses at least one process
    ],
)
def test_diag_grid_side_matches_laxlib(
    ndiag: int, procs_per_pool: int, side: int
) -> None:
    assert diag_grid_side(ndiag, procs_per_pool, nbnd=1000) == side


@pytest.mark.parametrize(
    ("nbnd", "procs_per_pool", "side"),
    [
        (612, 16, 4),  # nint(6.12) = 6, capped at isqrt(16)
        (250, 64, 3),  # Fortran nint(2.5) = 3; Python round(2.5) = 2
        (350, 64, 4),
        (149, 64, 1),
        (150, 64, 2),
        (120, 64, 1),
        (30, 64, 1),  # nint(0.3) = 0: pw.x keeps a 1x1 grid
        (612, 1, 1),
    ],
)
def test_unset_ndiag_gives_pw_x_s_own_grid(
    nbnd: int, procs_per_pool: int, side: int
) -> None:
    """Without -ndiag, pw.x takes the largest np <= nint(nbnd/100) with
    np^2 <= processes per pool, at least 1 (QE 7.3 setup.f90:827-832), so
    the memory estimate and the ndiag gate share one grid side (#148)."""
    assert diag_grid_side(None, procs_per_pool, nbnd) == side


def test_warning_catalogue_describes_only_the_non_square_note_for_ndiag() -> None:
    ndiag_entries = [w for w in WARNING_CATALOGUE if "ndiag" in w.code]

    assert [(w.code, w.level) for w in ndiag_entries] == [
        ("parallelisation.ndiag_not_a_square_integer", "info")
    ]


def test_warning_catalogue_counts_k_point_spin_pairs() -> None:
    by_code = {w.code: w.message for w in WARNING_CATALOGUE}

    assert "k-point/spin pairs" in by_code["parallelisation.npool_exceeds_kpoints"]
    assert "k-point/spin pairs" in by_code["parallelisation.npool_load_imbalance"]
