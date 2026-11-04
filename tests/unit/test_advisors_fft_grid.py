"""The first step's FFT-grid record for ph.x (#215): pw.x's own dense grid,
whether ph.x accepts it, the nr1-nr3 a phonon task's first step writes
instead, and the axis pairs that make a cell fragile under a vc-relax. The
grids of every fragile written cell are in ``tests/unit/test_pw_fft.py``."""

from __future__ import annotations

import pytest
from support import (
    alpha_uranium,
    framed_magnetic_cell,
    mc3d_42058_silicon,
    written_afm_nickel_oxide,
    written_magnetic_cell,
)

from goldilocks_core.advisors.cutoffs import CutoffsDecision
from goldilocks_core.advisors.fft_grid import fft_grid
from goldilocks_core.resolution import Blocked, Provenance, Resolved, Unavailable


def _cutoffs(ecutrho_ry: float) -> Resolved[CutoffsDecision]:
    return Resolved(
        CutoffsDecision(ecutwfc_ry=ecutrho_ry / 8, ecutrho_ry=ecutrho_ry),
        Provenance(source="human"),
    )


@pytest.mark.parametrize("first_step", ["scf", "relax"])
def test_alpha_uranium_writes_the_grid_ph_x_accepts(first_step: str) -> None:
    """Its mirror turns a_2 into a_1 + a_2, which needs nr1 to be a
    multiple of nr2; pw.x's 40x45x64 at 480 Ry is not, and ph.x would stop
    with 'FFT grid incompatible with symmetry'. pw.x keeps a written grid
    through a fixed-cell relaxation and stores it in the save ph.x reads."""
    state = fft_grid(framed_magnetic_cell(alpha_uranium()), _cutoffs(480.0), first_step)

    assert state.ok
    decision = state.value
    assert decision.pw_grid == (40, 45, 64)
    assert decision.compatible is False
    assert decision.written == (45, 45, 64)
    assert decision.fragile_axes == (("b", "a"),)
    assert decision.fragile is True
    assert state.source == "heuristic"
    assert state.provenance.derived_from == ("cutoffs", "magnetic")
    note = state.provenance.source_note
    assert "40x45x64" in note
    assert "45x45x64" in note
    assert "1.12 times" in note
    assert "memory" in note


def test_an_antiferromagnetic_cell_is_read_with_its_spins_split() -> None:
    """AFM NiO's written cell (a = c = 2.89 A, b = 5.01 A) has a species per
    spin; operations that mix b with a and c fail pw.x's 40x64x40 at 440 Ry,
    and the cube ph.x accepts has 2.56 times its points."""
    state = fft_grid(
        written_magnetic_cell(written_afm_nickel_oxide()), _cutoffs(440.0), "relax"
    )

    decision = state.value
    assert (decision.pw_grid, decision.compatible) == ((40, 64, 40), False)
    assert decision.written == (64, 64, 64)
    assert decision.fragile_axes == (("b", "a"), ("b", "c"))
    assert "2.56 times" in state.provenance.source_note


def test_a_vc_relax_first_step_writes_no_grid() -> None:
    """A vc-relax's final scf rebuilds pw.x's own grid for the relaxed cell
    and drops nr1-nr3 (QE 7.3 run_pwscf.f90:404-405): the cell stays
    fragile, which the gate refuses for vc-relax-phonon."""
    state = fft_grid(framed_magnetic_cell(alpha_uranium()), _cutoffs(480.0), "vc-relax")

    decision = state.value
    assert (decision.pw_grid, decision.compatible) == ((40, 45, 64), False)
    assert decision.written is None
    assert decision.fragile_axes == (("b", "a"),)
    assert decision.fragile is True
    assert "vc-relax" in state.provenance.source_note


@pytest.mark.parametrize("first_step", ["scf", "relax", "vc-relax"])
def test_silicon_keeps_pw_x_s_own_grid_and_is_not_fragile(first_step: str) -> None:
    state = fft_grid(
        framed_magnetic_cell(mc3d_42058_silicon()), _cutoffs(240.0), first_step
    )

    decision = state.value
    assert decision.pw_grid == (36, 36, 36)
    assert decision.compatible is True
    assert decision.written is None
    assert decision.fragile_axes == ()
    assert decision.fragile is False
    assert state.provenance.source_note is None


@pytest.mark.parametrize(
    ("cell", "cutoffs"),
    [
        (
            lambda: Blocked(by="no compatible pseudopotential table"),
            lambda: _cutoffs(240.0),
        ),
        (
            lambda: framed_magnetic_cell(mc3d_42058_silicon()),
            lambda: Unavailable(reason="pseudopotential table sssp is not installed"),
        ),
    ],
    ids=["cell", "cutoffs"],
)
def test_an_unresolved_cell_or_cutoff_blocks_the_record(cell, cutoffs) -> None:
    assert isinstance(fft_grid(cell(), cutoffs(), "scf"), Blocked)
