"""pw.x's dense FFT grid, ph.x's test of it and fragile cells (#215).

The QE cells are PHonon examples 02, 03, 16 and 17 of QE 7.3, whose
reference outputs print the grid pw.x chose ("FFT dimensions"). The others
are cells as goldilocks writes them (``tests/support.py``; graphite as built
there) at the ecutrho of their default pseudopotentials: the nine whose
pw.x grid ph.x rejects with "FFT grid incompatible with symmetry", and four
whose grid it accepts.
"""

from __future__ import annotations

import math

import pytest
from pymatgen.core import Lattice, Structure
from support import (
    QE_BOHR_ANGSTROM,
    aluminium_arsenide,
    graphite,
    qe_fcc_lattice,
    written_afm_hematite,
    written_afm_manganese_oxide,
    written_afm_nickel,
    written_afm_nickel_oxide,
    written_afm_uranium_dioxide,
    written_alpha_sulfur,
    written_alpha_uranium,
    written_bcc_iron,
    written_boron_nitride_monolayer,
    written_lanthanum_cuprate,
    written_manganese_thiophosphate_monolayer,
    written_silicon,
)

from goldilocks_core.pw_fft import (
    dense_fft_grid,
    fragile_axis_pairs,
    grid_is_compatible,
    ph_fft_grid,
)
from goldilocks_core.pw_symmetry import fft_factors, mixing_axis_pairs, pw_rotations


def _hexagonal(celldm: float, c_over_a: float) -> Lattice:
    """QE's ibrav = 4 lattice for celldm(1) in bohr and celldm(3)."""
    a = celldm * QE_BOHR_ANGSTROM
    return Lattice([[a, 0, 0], [-a / 2, a * math.sqrt(3) / 2, 0], [0, 0, a * c_over_a]])


def aluminium() -> Structure:
    """PHonon example03's fcc Al, celldm(1) 7.5."""
    return Structure(qe_fcc_lattice(7.5), ["Al"], [[0, 0, 0]])


def example_graphite() -> Structure:
    """PHonon example16's graphite, its crystal coordinates as the input
    gives them."""
    return Structure(
        _hexagonal(4.64630333, 2.58254285),
        ["C"] * 4,
        [
            [0, 0, 0],
            [0.333333333, 0.666666667, 0],
            [0, 0, 0.5],
            [0.666666667, 0.333333333, 0.5],
        ],
    )


def boron_nitride() -> Structure:
    """PHonon example17's hBN monolayer, B and N at (0, +-0.288675135, 0)
    alat."""
    alat = 4.7419 * QE_BOHR_ANGSTROM
    return Structure(
        _hexagonal(4.7419, 4.3),
        ["B", "N"],
        [[0, 0.288675135 * alat, 0], [0, -0.288675135 * alat, 0]],
        coords_are_cartesian=True,
    )


@pytest.mark.parametrize(
    ("build", "ecutrho", "factors", "grid"),
    [
        (aluminium_arsenide, 64.0, (1, 1, 1), (20, 20, 20)),
        (aluminium, 60.0, (1, 1, 1), (15, 15, 15)),
        (example_graphite, 180.0, (1, 1, 2), (20, 20, 54)),
        (example_graphite, 120.0, (1, 1, 2), (18, 18, 48)),
        (boron_nitride, 440.0, (2, 2, 1), (32, 32, 144)),
        (boron_nitride, 220.0, (2, 2, 1), (24, 24, 100)),
    ],
    ids=[
        "alas-dense",
        "al-dense",
        "graphite-dense",
        "graphite-smooth",
        "bn-dense",
        "bn-smooth",
    ],
)
def test_reproduces_the_grids_in_qe_reference_outputs(
    build, ecutrho: float, factors: tuple[int, int, int], grid: tuple[int, int, int]
) -> None:
    """The dense grid at ecutrho, and the smooth grid at 4 ecutwfc where
    ecutrho is larger. graphite's screw axis translates by half of c, and
    operations of example 17's hBN, whose origin is the B-N bond centre, by
    half of a and b: so 54 and 48 are even, and so are 32 and 24."""
    structure = build()

    assert fft_factors(structure) == factors
    assert dense_fft_grid(structure, ecutrho) == grid


@pytest.mark.parametrize(
    ("build", "factors"),
    [
        (written_silicon, (4, 4, 4)),
        (graphite, (1, 1, 2)),
        (written_alpha_uranium, (1, 1, 2)),
    ],
    ids=["silicon", "graphite", "alpha-uranium"],
)
def test_fft_factors_come_from_the_fractional_translations(
    build, factors: tuple[int, int, int]
) -> None:
    """Diamond's glides translate by a quarter along every axis; graphite's
    screw and alpha-U's by half of c."""
    assert fft_factors(build()) == factors


def test_alpha_uranium_mixes_only_b_into_a() -> None:
    """The base-centred lattice in its primitive basis: a mirror turns
    a_2 into a_1 + a_2, and nothing turns a_1 or a_3 off its own line."""
    assert mixing_axis_pairs(pw_rotations(written_alpha_uranium())) == ((1, 0),)


def test_a_mixed_axis_count_must_divide_the_count_it_is_mixed_into() -> None:
    """The mirror takes the grid point m/n_2 along a_2 to m/n_2 along a_1
    and a_2, so ph.x needs n_1 to be a multiple of n_2, not the reverse."""
    rotations = pw_rotations(written_alpha_uranium())

    assert grid_is_compatible(rotations, (90, 45, 64))
    assert not grid_is_compatible(rotations, (45, 90, 64))


_ALL_PAIRS = ((0, 1), (0, 2), (1, 0), (1, 2), (2, 0), (2, 1))


@pytest.mark.parametrize(
    ("build", "ecutrho", "pw_grid", "written", "pairs"),
    [
        (written_alpha_uranium, 480.0, (40, 45, 64), (45, 45, 64), ((1, 0),)),
        (
            written_lanthanum_cuprate,
            720.0,
            (64, 64, 120),
            (120, 120, 120),
            ((2, 0), (2, 1)),
        ),
        (
            written_manganese_thiophosphate_monolayer,
            432.0,
            (72, 75, 288),
            (75, 75, 288),
            ((1, 0),),
        ),
        (written_alpha_sulfur, 256.0, (144, 128, 96), (144, 144, 144), _ALL_PAIRS),
        (written_afm_nickel_oxide, 440.0, (40, 64, 40), (64, 64, 64), ((1, 0), (1, 2))),
        (
            written_afm_manganese_oxide,
            432.0,
            (40, 40, 72),
            (72, 72, 72),
            ((2, 0), (2, 1)),
        ),
        (written_afm_nickel, 440.0, (32, 54, 32), (54, 54, 54), ((1, 0), (1, 2))),
        (
            written_afm_hematite,
            424.0,
            (60, 72, 60),
            (72, 72, 72),
            ((0, 2), (1, 0), (1, 2), (2, 0)),
        ),
        (
            written_afm_uranium_dioxide,
            480.0,
            (54, 90, 54),
            (90, 90, 90),
            ((0, 2), (1, 0), (1, 2), (2, 0)),
        ),
    ],
    ids=[
        "alpha-uranium",
        "la2cuo4",
        "mnps3-monolayer",
        "alpha-sulfur",
        "afm-nio",
        "afm-mno",
        "afm-ni",
        "afm-fe2o3",
        "afm-uo2",
    ],
)
def test_a_fragile_cell_gets_the_smallest_grid_ph_x_accepts(
    build,
    ecutrho: float,
    pw_grid: tuple[int, int, int],
    written: tuple[int, int, int],
    pairs: tuple[tuple[int, int], ...],
) -> None:
    """pw.x's own grid fails ph.x's test because a rotation mixes two axes
    of different lengths. The grid to write is at least pw.x's on every
    axis and passes."""
    structure = build()
    rotations = pw_rotations(structure)

    assert dense_fft_grid(structure, ecutrho) == pw_grid
    assert not grid_is_compatible(rotations, pw_grid)
    assert ph_fft_grid(structure, rotations, ecutrho) == written
    assert grid_is_compatible(rotations, written)
    assert fragile_axis_pairs(structure, rotations) == pairs


@pytest.mark.parametrize(
    ("build", "factors"),
    [(written_afm_hematite, (2, 2, 1)), (written_afm_uranium_dioxide, (1, 2, 2))],
    ids=["afm-fe2o3", "afm-uo2"],
)
def test_exchanged_axes_with_unequal_factors_are_fragile(
    build, factors: tuple[int, int, int]
) -> None:
    """A rotation exchanges a and c, which are equally long, but their
    factors differ, so pw.x's grid can give them different lengths: the
    pair is fragile although a rotation exchanges it."""
    structure = build()
    rotations = pw_rotations(structure)

    assert structure.lattice.a == pytest.approx(structure.lattice.c)
    assert fft_factors(structure) == factors
    assert {(0, 2), (2, 0)} <= set(mixing_axis_pairs(rotations))
    assert {(0, 2), (2, 0)} <= set(fragile_axis_pairs(structure, rotations))


@pytest.mark.parametrize(
    ("build", "ecutrho", "grid"),
    [
        (written_silicon, 192.0, (36, 36, 36)),
        (written_bcc_iron, 424.0, (30, 30, 30)),
        (graphite, 360.0, (30, 30, 80)),
        (written_boron_nitride_monolayer, 384.0, (30, 30, 240)),
    ],
    ids=["silicon", "bcc-iron", "graphite", "hbn-monolayer"],
)
def test_a_compatible_cell_keeps_pw_x_s_own_grid(
    build, ecutrho: float, grid: tuple[int, int, int]
) -> None:
    structure = build()
    rotations = pw_rotations(structure)

    assert dense_fft_grid(structure, ecutrho) == grid
    assert grid_is_compatible(rotations, grid)
    assert ph_fft_grid(structure, rotations, ecutrho) == grid
    assert fragile_axis_pairs(structure, rotations) == ()
