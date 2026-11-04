"""fft_grid: the dense FFT grid of the phonon tasks' first step, for ph.x
(#215).

ph.x stops with "FFT grid incompatible with symmetry" unless every operation
pw.x keeps maps the dense FFT grid onto itself (QE 7.3
``PHonon/PH/phq_setup.f90:211-212``), a test pw.x itself never runs;
``pw_fft`` reproduces pw.x's own grid and that test. The record holds pw.x's
own grid for the written cell at the density cutoff (``pw_grid``) and
whether ph.x accepts it (``compatible``). When it does not, ``written`` is
the grid the first step writes as nr1, nr2 and nr3 (``pw_fft.ph_fft_grid``):
pw.x uses them as given, for the smooth grid too when ecutrho is 4 ecutwfc
(``PW/src/input.f90:1785-1797``), keeps them through a fixed-cell relaxation
and stores them in the save ph.x reads (``PW/src/pw_restart_new.f90:398-400``).
A vc-relax first step writes none: its final scf drops nr1-nr3 and rebuilds
pw.x's own grid for the relaxed cell (``PW/src/run_pwscf.f90:404-405``).

``fragile_axes`` are the pairs of lattice axes, by letter, on which a
symmetric strain can give pw.x's own grid counts ph.x refuses
(``pw_fft.fragile_axis_pairs``): (b, a) when an operation turns b into a
vector with a component along a and no operation exchanges the two.
``fragile`` says whether there are any: on such a cell the grid a vc-relax
rebuilds can fail ph.x, and ``checks`` refuses the vc-relax-phonon task
there. pw.x's own grid stays compatible under every symmetric strain of a
cell that is not fragile, so a grid ph.x refuses on the input cell makes the
cell fragile.

The written grid is not in the job's memory estimate yet:
``advisors/size.py`` sizes pw.x on its own approximate grid, and the record's
note says so.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from goldilocks_core.advisors.cutoffs import CutoffsDecision
from goldilocks_core.advisors.magnetic_config import MagneticCell
from goldilocks_core.analysis.geometry import LATTICE_AXES, LatticeAxis
from goldilocks_core.pw_fft import (
    dense_fft_grid,
    fragile_axis_pairs,
    grid_is_compatible,
    ph_fft_grid,
)
from goldilocks_core.pw_symmetry import pw_rotations
from goldilocks_core.resolution import (
    Blocked,
    FieldState,
    Provenance,
    Resolved,
    blocked_by,
)


@dataclass(frozen=True, slots=True)
class FftGridDecision:
    """The first step's dense FFT grid for ph.x (module docstring):
    ``pw_grid`` is pw.x's own (nr1, nr2, nr3), ``compatible`` whether ph.x
    accepts it, ``written`` the nr1-nr3 the first step writes, ``None`` when
    it writes none; ``fragile_axes`` the lattice-axis pairs that make the
    cell fragile under a vc-relax, and ``fragile`` whether there are any."""

    pw_grid: tuple[int, int, int]
    compatible: bool
    written: tuple[int, int, int] | None
    fragile_axes: tuple[tuple[LatticeAxis, LatticeAxis], ...]
    fragile: bool


def fft_grid(
    cell: FieldState[MagneticCell],
    cutoffs: FieldState[CutoffsDecision],
    first_step: Literal["scf", "relax", "vc-relax"],
) -> FieldState[FftGridDecision]:
    """pw.x's dense FFT grid for the written ``cell`` at the ``cutoffs``'
    ecutrho, under the operations pw.x keeps in it, and the grid the
    phonon task's ``first_step`` writes when ph.x would refuse pw.x's own
    (module docstring). ``Blocked`` when ``cell`` or ``cutoffs`` is not
    resolved."""
    for state in (cell, cutoffs):
        if not state.ok:
            return Blocked(by=blocked_by(state))
    structure = cell.value.structure
    rotations = pw_rotations(structure, cell.value.moment_axis)
    ecutrho = cutoffs.value.ecutrho_ry
    own = dense_fft_grid(structure, ecutrho)
    compatible = grid_is_compatible(rotations, own)
    written = None
    if not compatible and first_step != "vc-relax":
        written = ph_fft_grid(structure, rotations, ecutrho)
    fragile_axes = tuple(
        (LATTICE_AXES[i], LATTICE_AXES[j])
        for i, j in fragile_axis_pairs(structure, rotations)
    )
    decision = FftGridDecision(
        pw_grid=own,
        compatible=compatible,
        written=written,
        fragile_axes=fragile_axes,
        fragile=bool(fragile_axes),
    )
    return Resolved(
        decision,
        Provenance(
            source="heuristic",
            source_note=_note(decision, len(rotations)),
            derived_from=("cutoffs", "magnetic"),
        ),
    )


def _grid(grid: tuple[int, int, int]) -> str:
    """``grid`` as text, e.g. '45x45x64'."""
    return "x".join(str(length) for length in grid)


def _note(decision: FftGridDecision, operations: int) -> str | None:
    """Why a grid is written, or none can be, when ph.x would refuse pw.x's
    own; ``None`` when it accepts it."""
    if decision.compatible:
        return None
    refused = (
        f"pw.x's own dense FFT grid, {_grid(decision.pw_grid)}, is not mapped onto "
        f"itself by the {operations} symmetry operations pw.x keeps in the written "
        "cell, so ph.x would stop with 'FFT grid incompatible with symmetry'"
    )
    if decision.written is None:
        return (
            f"{refused}; a vc-relax's final scf drops nr1-nr3 and rebuilds pw.x's "
            "own grid for the relaxed cell, so none can be written."
        )
    ratio = math.prod(decision.written) / math.prod(decision.pw_grid)
    return (
        f"{refused}. nr1-nr3 = {_grid(decision.written)} are written instead: of "
        "the grids ph.x accepts that are at least pw.x's own along each axis, the "
        f"one with the fewest points, {ratio:.2f} times as many. The job's memory "
        "estimate does not include it yet, since it sizes pw.x on its own grid."
    )
