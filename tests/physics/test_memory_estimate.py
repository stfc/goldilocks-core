"""pw.x's own memory report against ``advisors/size.py`` (#148).

Each case is a default bundle that ran on SCARF (QE 7.5, 64 MPI tasks)
in the 2026-10-20 verification batch, at the layout it ran with (its
submit.sh's -npool and -ndiag). The literals are copied from the
bundle: the cell, the atoms per species, the cutoffs, nbnd, nspin and
mixing_mode from scf.in, the +U manifold from its HUBBARD card, and
number_of_proj/l_max/pseudo_type from the PP_HEADER of each
pseudopotential. The k-point count is the one pw.x printed ('number of
k points=', twice that for collinear nspin=2), which can differ from
goldilocks' n_irr_k until pw.x keeps the full symmetry (#140). The
expected figures are pw.x's 'Estimated max dynamical RAM per
process' and 'Estimated total dynamical RAM' lines from the same runs
(issue #148's table). The design's precision bar is +-20%; the port
reproduces these within 1%, so the tests hold it to 3%.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from pymatgen.core import Lattice

from goldilocks_core.advisors.parallelisation import diag_grid_side
from goldilocks_core.advisors.size import Species, memory_estimate, resource_estimate

_NTASKS = 64
_GB = 1024.0
_TOLERANCE = 0.03


@dataclass(frozen=True)
class _Run:
    lattice: tuple[tuple[float, float, float], ...]
    species: tuple[Species, ...]
    ecutwfc_ry: float
    ecutrho_ry: float
    nbnd: int
    nspin: int
    kpoint_spin_pairs: int
    local_tf: bool
    npool: int
    ndiag: int
    per_process_mb: float
    total_mb: float


_RUNS = {
    # MC3D mc3d-29639: Al fcc, PseudoDojo NC.
    "Al": _Run(
        lattice=(
            (2.457676658, 0.0, 1.41894028),
            (0.8192255528, 2.317119775, 1.41894028),
            (0.0, 0.0, 2.837880561),
        ),
        species=(Species(atoms=1, projectors=6, l_max=2, ultrasoft=False),),
        ecutwfc_ry=52.0,
        ecutrho_ry=208.0,
        nbnd=6,
        nspin=1,
        kpoint_spin_pairs=595,
        local_tf=False,
        npool=64,
        ndiag=1,
        per_process_mb=5.70,
        total_mb=278.84,
    ),
    # MC2D mc2d-d25962ea: MoS2 monolayer, PseudoDojo NC, local-TF mixing.
    "MoS2": _Run(
        lattice=(
            (3.18817952, 0.0, 1.952196922e-16),
            (-1.59408976, 2.761044456, 1.952196922e-16),
            (0.0, 0.0, 23.15470209),
        ),
        species=(
            Species(atoms=1, projectors=6, l_max=2, ultrasoft=False),
            Species(atoms=2, projectors=6, l_max=2, ultrasoft=False),
        ),
        ecutwfc_ry=92.0,
        ecutrho_ry=368.0,
        nbnd=13,
        nspin=1,
        kpoint_spin_pairs=24,
        local_tf=True,
        npool=16,
        ndiag=4,
        per_process_mb=53.85,
        total_mb=2.78 * _GB,
    ),
    # MP mp-19961: CeCoIn5, nspin=2, SSSP Ce PAW, Co and In ultrasoft.
    "CeCoIn5": _Run(
        lattice=(
            (4.61176646, 0.0, 2.823892517e-16),
            (-2.823890619e-16, 4.61176336, 2.823890619e-16),
            (0.0, 0.0, 7.53603488),
        ),
        species=(
            Species(atoms=1, projectors=8, l_max=3, ultrasoft=True),
            Species(atoms=1, projectors=6, l_max=2, ultrasoft=True),
            Species(atoms=5, projectors=6, l_max=2, ultrasoft=True),
        ),
        ecutwfc_ry=50.0,
        ecutrho_ry=400.0,
        nbnd=57,
        nspin=2,
        kpoint_spin_pairs=2 * 30,
        local_tf=False,
        npool=16,
        ndiag=4,
        per_process_mb=80.45,
        total_mb=3.98 * _GB,
    ),
    # MP mp-5182: Nd2Fe14B, 68 atoms, nspin=2, SSSP B ultrasoft, Fe and Nd PAW.
    "Nd2Fe14B": _Run(
        lattice=(
            (8.776004, 0.0, 5.373752604e-16),
            (-5.373752604e-16, 8.776004, 5.373752604e-16),
            (0.0, 0.0, 12.119432),
        ),
        species=(
            Species(atoms=4, projectors=4, l_max=1, ultrasoft=True),
            Species(atoms=56, projectors=6, l_max=2, ultrasoft=True),
            Species(atoms=8, projectors=8, l_max=3, ultrasoft=True),
        ),
        ecutwfc_ry=90.0,
        ecutrho_ry=1080.0,
        nbnd=612,
        nspin=2,
        kpoint_spin_pairs=2 * 6,
        local_tf=False,
        npool=4,
        ndiag=16,
        per_process_mb=1.20 * _GB,
        total_mb=71.60 * _GB,
    ),
    # MC3D mc3d-29856: NiO rock salt, nspin=2, PseudoDojo NC, U on Ni 3d
    # (the run without mixing_fixed_ns, which pw.x's memory report does
    # not read).
    "NiO +U": _Run(
        lattice=(
            (2.505730864, 0.0, 1.446684389),
            (0.8352436212, 2.362425714, 1.446684389),
            (0.0, 0.0, 2.893368777),
        ),
        species=(
            Species(atoms=1, projectors=6, l_max=2, ultrasoft=False, hubbard_l=2),
            Species(atoms=1, projectors=5, l_max=2, ultrasoft=False),
        ),
        ecutwfc_ry=110.0,
        ecutrho_ry=440.0,
        nbnd=16,
        nspin=2,
        kpoint_spin_pairs=2 * 366,
        local_tf=False,
        npool=32,
        ndiag=1,
        per_process_mb=23.91,
        total_mb=1.23 * _GB,
    ),
    # H2O in a 20 A box (the GAP01 probe bundle), PseudoDojo NC, local-TF.
    "H2O box": _Run(
        lattice=(
            (20.0, 0.0, 1.224646799e-15),
            (-1.224646799e-15, 20.0, 1.224646799e-15),
            (0.0, 0.0, 20.0),
        ),
        species=(
            Species(atoms=2, projectors=3, l_max=1, ultrasoft=False),
            Species(atoms=1, projectors=5, l_max=2, ultrasoft=False),
        ),
        ecutwfc_ry=96.0,
        ecutrho_ry=384.0,
        nbnd=8,
        nspin=1,
        kpoint_spin_pairs=1,
        local_tf=True,
        npool=1,
        ndiag=64,
        per_process_mb=118.16,
        total_mb=7.39 * _GB,
    ),
}


def _memory(run: _Run):
    estimate = resource_estimate(
        Lattice(run.lattice),
        run.species,
        ecutwfc_ry=run.ecutwfc_ry,
        ecutrho_ry=run.ecutrho_ry,
        nbnd=run.nbnd,
        n_kpoint_spin=run.kpoint_spin_pairs,
        nspin=run.nspin,
        npol=1,
        nspin_mag=run.nspin,
        scf_loop=True,
        variable_cell=False,
        local_tf_mixing=run.local_tf,
    )
    side = diag_grid_side(run.ndiag, _NTASKS // run.npool, run.nbnd)
    return memory_estimate(estimate, ntasks=_NTASKS, npool=run.npool, diag_side=side)


@pytest.mark.parametrize("name", list(_RUNS))
def test_per_process_memory_matches_pw_x(name: str) -> None:
    run = _RUNS[name]

    memory = _memory(run)

    assert memory.per_process_mb == pytest.approx(run.per_process_mb, rel=_TOLERANCE)


@pytest.mark.parametrize("name", list(_RUNS))
def test_total_memory_matches_pw_x(name: str) -> None:
    run = _RUNS[name]

    memory = _memory(run)

    assert memory.total_mb == pytest.approx(run.total_mb, rel=_TOLERANCE)
