"""How matdyn.x reads the phonon dispersion's path (#215), ported from QE 7.3
independently of how the path was built (``PHonon/PH/matdyn.f90``, the same
in 7.5): it reads each row after its namelist as x y z n (``:485-501``),
converts the crystal coordinates to Cartesian ones with the reciprocal
vectors of the force-constant file's cell (``:538``), expands them as
``generate_k_along_lines`` does (``:546``; ``support.points_along_lines``),
and adds the non-analytic term at every point within 1e-6 of a reciprocal
lattice vector along a direction taken from a neighbouring point
(``:621-651``): the next one for the first point and for a point whose
predecessor is exactly 0, else the previous one. A point about 1e-16 off
Gamma still counts as q = 0, and the dipole sum then adds the term a second
time (``rigid.f90:195-217``), so every q = 0 point must be exactly 0."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest
from pymatgen.core import Structure
from support import (
    framed_magnetic_cell,
    geometry_facts,
    phosphorene,
    points_along_lines,
    rutile_titanium_dioxide,
    written_afm_nickel_oxide,
    written_alpha_sulfur,
    written_boron_nitride_monolayer,
    written_gallium_arsenide,
    written_magnetic_cell,
    written_sodium_chloride,
    wurtzite_zinc_oxide,
)

from goldilocks_core.advisors.k_path import KPathDecision, KPathHumanInput, k_path
from goldilocks_core.advisors.magnetic_config import MagneticCell
from goldilocks_core.advisors.occupations import OccupationsDecision
from goldilocks_core.advisors.phonon import Q2rDecision, dispersion_path
from goldilocks_core.analysis.geometry import vacuum_axes
from goldilocks_core.generation.quantum_espresso.bands import path_rows
from goldilocks_core.resolution import Provenance, Resolved

pytestmark = pytest.mark.physics

_GAMMA = (0.0, 0.0, 0.0)

_Q_ZERO_TOLERANCE = 1e-6
"""matdyn.x's ``eps``: how close to an integer each crystal coordinate of a
point must be for the point to count as q = 0 (``matdyn.f90:183``,
``:621-627``)."""

_CELLS = {
    "sodium_chloride": lambda: written_magnetic_cell(written_sodium_chloride()),
    "gallium_arsenide": lambda: written_magnetic_cell(written_gallium_arsenide()),
    "zinc_oxide": lambda: framed_magnetic_cell(wurtzite_zinc_oxide()),
    "alpha_sulfur": lambda: written_magnetic_cell(written_alpha_sulfur()),
    "phosphorene": lambda: framed_magnetic_cell(phosphorene()),
    "afm_nickel_oxide": lambda: written_magnetic_cell(written_afm_nickel_oxide()),
    "rutile_titanium_dioxide": lambda: framed_magnetic_cell(rutile_titanium_dioxide()),
    "boron_nitride_monolayer": lambda: written_magnetic_cell(
        written_boron_nitride_monolayer()
    ),
}
"""Polar crystals and layers, whose paths pass Gamma inside a branch (FCC,
HEX, ORCF1, RECT, RHL1, TET), at a path's end (alpha-S, hBN) and at its
start."""


@dataclass(frozen=True, slots=True)
class _QZero:
    """A point matdyn.x counts as q = 0: whether it is exactly 0, and the
    side of the path the direction of its non-analytic term comes from,
    'previous' or 'next', with that direction as a unit vector."""

    exact: bool
    side: str
    direction: np.ndarray


def _fixed_dispersion(
    cell: Resolved[MagneticCell], distance: float | None = None
) -> KPathDecision:
    """The dispersion path of ``cell`` on fixed occupations without loto_2d,
    where ph.x writes the effective charges and matdyn.x adds the
    non-analytic term."""
    axes = vacuum_axes(cell.value.structure)
    provenance = Provenance(source="heuristic")
    state = dispersion_path(
        cell,
        Resolved(geometry_facts("2d" if axes else "3d", axes), provenance),
        Resolved(
            OccupationsDecision(occupations="fixed", smearing_type=None, degauss=None),
            provenance,
        ),
        Resolved(Q2rDecision(asr="simple", loto_2d=False), provenance),
        KPathHumanInput(k_path_distance=distance),
    )
    assert state.ok, state
    return state.value


def _band_path(
    cell: Resolved[MagneticCell], distance: float | None = None
) -> KPathDecision:
    state = k_path(cell, KPathHumanInput(k_path_distance=distance))
    assert state.ok, state
    return state.value


def _file_cell(structure: Structure) -> tuple[np.ndarray, np.ndarray]:
    """The cell's lattice vectors in alat, |a1|, to the 9 decimals q2r.x
    writes them with (``do_q2r.f90:325``), and their reciprocal vectors in
    2 pi / alat, one per row each."""
    lattice = structure.lattice.matrix
    at = np.round(lattice / np.linalg.norm(lattice[0]), 9)
    return at, np.linalg.inv(at).T


def _matdyn_points(rows: list[str], bg: np.ndarray) -> np.ndarray:
    """The q-points matdyn.x computes from the ``rows`` after its namelist,
    in Cartesian coordinates of 2 pi / alat (module docstring): each vertex
    converted as ``cryst_to_cart`` does, b1 x1 + b2 x2 + b3 x3, then
    expanded."""
    count, *body = rows
    assert len(body) == int(count)
    numbers = [row.split()[:4] for row in body]
    vertices = [
        bg[0] * float(x) + bg[1] * float(y) + bg[2] * float(z) for x, y, z, _ in numbers
    ]
    points, _ = points_along_lines(vertices, [int(n) for *_, n in numbers])
    return points


def _q_zero(points: np.ndarray, at: np.ndarray) -> list[_QZero]:
    """Every point of ``points`` matdyn.x counts as q = 0, in order, with
    the direction its non-analytic term takes (module docstring). Each must
    be Gamma itself: no vertex of these paths is another reciprocal lattice
    vector."""
    zeros = []
    last = len(points) - 1
    for index, q in enumerate(points):
        crystal = at @ q
        if np.abs(crystal - np.rint(crystal)).max() > _Q_ZERO_TOLERANCE:
            continue
        assert not np.rint(crystal).any(), index
        after_zero = index > 0 and not points[index - 1].any()
        if index == 0 or (after_zero and index < last):
            side, other = "next", points[index + 1]
        else:
            side, other = "previous", points[index - 1]
        direction = q - other
        zeros.append(_QZero(not q.any(), side, direction / np.linalg.norm(direction)))
    return zeros


def _gamma_sides(band: KPathDecision, bg: np.ndarray) -> list[tuple[str, np.ndarray]]:
    """The side and the direction the non-analytic term must take at each
    Gamma of the band path, in path order: the leaving segment at the
    path's first point, the arriving and then the leaving segment at a
    Gamma inside a branch, and the arriving segment at a Gamma that ends a
    branch. On a segment between vertex v and Gamma, Gamma minus its
    neighbouring point lies along -v. No branch after the first starts at
    Gamma, where the only direction would come from the jump before it."""
    sides = []
    for number, branch in enumerate(band.branches):
        vertices = branch.vertices
        for index, vertex in enumerate(vertices):
            if vertex.k != _GAMMA:
                continue
            assert index or not number, "a branch starts at Gamma after a jump"
            neighbours = []
            if index:
                neighbours.append(("previous", vertices[index - 1]))
            if index < len(vertices) - 1:
                neighbours.append(("next", vertices[index + 1]))
            for side, neighbour in neighbours:
                towards = -(np.array(neighbour.k) @ bg)
                sides.append((side, towards / np.linalg.norm(towards)))
    return sides


@pytest.mark.parametrize("name", list(_CELLS))
def test_matdyn_x_takes_each_side_s_direction_at_every_gamma(name: str) -> None:
    """Expanded as matdyn.x expands it, the dispersion path holds
    ``n_kpoints`` points; every point it counts as q = 0 is exactly Gamma;
    an interior Gamma gives two consecutive such points, the first along
    the arriving segment and the second along the leaving one, the path's
    first Gamma takes the leaving segment and a last Gamma the arriving
    one."""
    cell = _CELLS[name]()
    dispersion = _fixed_dispersion(cell)
    at, bg = _file_cell(dispersion.cell)

    points = _matdyn_points(path_rows(dispersion), bg)
    zeros = _q_zero(points, at)
    expected = _gamma_sides(_band_path(cell), bg)

    assert len(points) == dispersion.n_kpoints
    assert all(zero.exact for zero in zeros)
    assert [zero.side for zero in zeros] == [side for side, _ in expected]
    for zero, (_, direction) in zip(zeros, expected, strict=True):
        assert np.allclose(zero.direction, direction, atol=1e-9)


def _steps_into_gamma(decision: KPathDecision) -> list[int]:
    return [
        steps
        for branch in decision.branches
        for steps, end in zip(branch.steps, branch.vertices[1:], strict=True)
        if end.k == _GAMMA
    ]


@pytest.mark.parametrize(
    ("name", "steps", "exact"),
    [
        ("sodium_chloride", 49, 50),
        ("sodium_chloride", 98, 99),
        ("sodium_chloride", 196, 198),
        ("boron_nitride_monolayer", 49, 50),
    ],
)
def test_a_count_that_lands_off_gamma_is_raised_to_one_that_lands_on_it(
    name: str, steps: int, exact: int
) -> None:
    """A segment ends at x + (delta * n) * (0 - x), delta = 1 / n, exactly 0
    only where fl(fl(1/n) n) = 1. At a spacing that gives K-Gamma ``steps``
    steps, the band path's rows land about 1e-16 off Gamma, a point matdyn.x
    still counts as q = 0; the dispersion's ``exact`` steps land on it."""
    cell = _CELLS[name]()
    default = _band_path(cell)
    (k,) = {
        vertex.k
        for branch in default.branches
        for vertex in branch.vertices
        if vertex.label == "K"
    }
    reciprocal = default.cell.lattice.reciprocal_lattice.matrix
    distance = float(np.linalg.norm(np.array(k) @ reciprocal)) / (steps - 0.5)
    band = _band_path(cell, distance)
    dispersion = _fixed_dispersion(cell, distance)
    at, bg = _file_cell(dispersion.cell)

    landing = _q_zero(_matdyn_points(path_rows(band), bg), at)
    raised = _q_zero(_matdyn_points(path_rows(dispersion), bg), at)

    assert _steps_into_gamma(band) == [steps]
    assert _steps_into_gamma(dispersion) == [exact]
    assert not all(zero.exact for zero in landing)
    assert all(zero.exact for zero in raised)
