from __future__ import annotations

import math

import pytest
from pymatgen.core import Lattice

from goldilocks_core.advisors.size import (
    ResourceEstimate,
    Species,
    memory_estimate,
    resource_estimate,
)

_BOHR_PER_ANGSTROM = 1.8897259886
_SILICON = Lattice.cubic(5.43)
_SILICON_SPECIES = (Species(atoms=2, projectors=4, l_max=1, ultrasoft=False),)
_SILICON_DIAMOND = Lattice(
    [
        [3.326270743, 0.0, 1.920423309],
        [1.108756914, 3.136038131, 1.920423309],
        [0.0, 0.0, 3.840846617],
    ]
)
_MOS2 = Lattice(
    [
        [3.18817952, 0.0, 0.0],
        [-1.59408976, 2.761044456, 0.0],
        [0.0, 0.0, 23.15470209],
    ]
)


def _estimate(**changes) -> ResourceEstimate:
    arguments = {
        "ecutwfc_ry": 40.0,
        "ecutrho_ry": 160.0,
        "nbnd": 8,
        "n_kpoint_spin": 10,
        "nspin": 1,
        "npol": 1,
        "nspin_mag": 1,
        "scf_loop": False,
        "variable_cell": False,
        "local_tf_mixing": False,
    }
    species = changes.pop("species", _SILICON_SPECIES)
    lattice = changes.pop("lattice", _SILICON)
    return resource_estimate(lattice, species, **(arguments | changes))


def _per_process(estimate: ResourceEstimate, ntasks: int, npool: int) -> float:
    return memory_estimate(
        estimate, ntasks=ntasks, npool=npool, diag_side=1
    ).per_process_mb


def _expected_npw(lattice: Lattice, ecut_ry: float) -> int:
    """Independent re-derivation of QE's own npwx formula (memory_report.f90:91,
    npwx_g = NINT(fpi/3 * sqrt(ecutwfc)**3 / (tpi**3/omega))), to cross-check
    the module's constant rather than just re-running its own code."""
    volume_bohr3 = lattice.volume * _BOHR_PER_ANGSTROM**3
    sphere = (4 * math.pi / 3) * ecut_ry**1.5 / ((2 * math.pi) ** 3 / volume_bohr3)
    return math.floor(sphere + 0.5)  # Fortran NINT


def test_plane_wave_and_g_vector_counts_follow_qes_sphere_formula() -> None:
    estimate = _estimate()

    assert estimate.npwx == _expected_npw(_SILICON, 40.0)
    assert estimate.ngm == _expected_npw(_SILICON, 160.0)
    assert estimate.ngms == estimate.ngm  # ecutrho = 4 x ecutwfc: no smooth grid


def test_a_larger_ecutrho_gives_a_separate_smooth_grid() -> None:
    estimate = _estimate(ecutrho_ry=320.0)

    assert estimate.ngms == _expected_npw(_SILICON, 160.0)
    assert estimate.ngm == _expected_npw(_SILICON, 320.0)
    assert estimate.smooth_grid != estimate.dense_grid


@pytest.mark.parametrize(
    ("lattice", "ecutrho_ry", "grid"),
    [
        # TSK03 Si diamond bundle: pw.x printed FFT dimensions (36, 36, 36).
        (_SILICON_DIAMOND, 192.0, (36, 36, 36)),
        # MC2D MoS2 monolayer bundle: pw.x printed (40, 40, 270).
        (_MOS2, 368.0, (40, 40, 270)),
    ],
)
def test_fft_grid_matches_the_planes_pw_x_printed(lattice, ecutrho_ry, grid) -> None:
    """2*floor(sqrt(ecutrho)*|a_i|/2pi)+1 points rounded up to the next
    2,3,5-smooth length (FFTXlib realspace_grid_init, good_fft_order)."""
    estimate = _estimate(
        lattice=lattice, ecutwfc_ry=ecutrho_ry / 4, ecutrho_ry=ecutrho_ry
    )

    assert estimate.dense_grid == grid


@pytest.mark.parametrize(
    ("pairs", "npool", "buffers"),
    [(1, 1, 1), (12, 4, 4), (13, 4, 5), (12, 12, 1)],
)
def test_scf_wavefunctions_hold_every_k_point_of_the_pool_plus_one(
    pairs: int, npool: int, buffers: int
) -> None:
    """pw.x's scf default io_level=0 keeps nks+1 wavefunction buffers per
    pool, nks = ceil(N/npool), and one when nks = 1 (memory_report.f90:
    105-110). Each buffer is nbnd x npol x npwx_l complex numbers."""
    base = _estimate(scf_loop=True, n_kpoint_spin=npool)
    estimate = _estimate(scf_loop=True, n_kpoint_spin=pairs)
    procs = 64 // npool
    one_buffer_mb = 16 * 8 * (estimate.npwx // procs) / 2**20

    extra = _per_process(estimate, 64, npool) - _per_process(base, 64, npool)

    assert extra == pytest.approx((buffers - 1) * one_buffer_mb)


def test_nscf_holds_one_wavefunction_buffer_whatever_the_k_points() -> None:
    """A non-SCF run defaults to io_level=1 (QE 7.3 input.f90:909-919)."""
    few = _estimate(scf_loop=False, n_kpoint_spin=1)
    many = _estimate(scf_loop=False, n_kpoint_spin=500)

    assert _per_process(many, 64, 1) == _per_process(few, 64, 1)


def test_per_process_memory_falls_as_ranks_per_pool_grow() -> None:
    estimate = _estimate(scf_loop=True, n_kpoint_spin=4)

    figures = [_per_process(estimate, ntasks, 4) for ntasks in (4, 16, 64, 256)]

    assert figures == sorted(figures, reverse=True)
    assert figures[0] > 4 * figures[-1]


def test_total_memory_counts_every_process_and_one_mixing_copy_per_pool() -> None:
    """totram = (ram + scratch) x ntasks + mixing x ntasks / npool
    (memory_report.f90:467): the mixing history lives on pool 0 only."""
    scf = _estimate(scf_loop=True, n_kpoint_spin=4)
    nscf = _estimate(scf_loop=False, n_kpoint_spin=4)

    scf_memory = memory_estimate(scf, ntasks=64, npool=4, diag_side=1)
    nscf_memory = memory_estimate(nscf, ntasks=64, npool=4, diag_side=1)

    assert scf_memory.total_mb > 64 * nscf_memory.per_process_mb
    assert nscf_memory.total_mb == pytest.approx(64 * nscf_memory.per_process_mb)


def test_density_arrays_hold_one_component_per_density_spin() -> None:
    """rho, v and vnew are (16 ngm + 8 nnr) bytes per component and vrs,
    vltot and the like add 8 nnr per component (memory_report.f90:183-192),
    so spin-orbit's nspin=4 holds four, magnetic or not (QE 7.3
    input.f90:718)."""
    collinear = _estimate()
    spin_orbit = _estimate(nspin=4, nspin_mag=1)
    nnr = math.prod(collinear.dense_grid)

    extra = _per_process(spin_orbit, 1, 1) - _per_process(collinear, 1, 1)

    component = 3 * (16 * collinear.ngm + 8 * nnr) + 8 * nnr
    assert extra == pytest.approx(3 * component / 2**20)


def test_a_finer_diagonalization_grid_shrinks_the_subspace_matrices() -> None:
    estimate = _estimate(scf_loop=True, nbnd=600, n_kpoint_spin=1)

    serial = memory_estimate(estimate, ntasks=64, npool=1, diag_side=1)
    grid = memory_estimate(estimate, ntasks=64, npool=1, diag_side=2)

    # 3 subspace matrices of (2 nbnd / s)^2 complex numbers (memory_report.f90:304)
    saved_mb = 16 * 3 * (1200**2 - 600**2) / 2**20
    assert serial.per_process_mb - grid.per_process_mb == pytest.approx(saved_mb)


def test_projectors_count_every_atom_and_angular_channel() -> None:
    """nkb = 2 atoms x nh, nh = number_of_proj x (l_max + 1) = 8 from the
    header, fills vkb (memory_report.f90:165) and <psi|beta> (:306); the
    4 beta functions up to l=1 fill the qrad table, (sqrt(ecutrho)/0.01 +
    4) points x 4*5/2 pairs x (2 l + 1 = 3) for 1 species (:169-177)."""
    bare = _estimate(
        species=(Species(atoms=2, projectors=0, l_max=0, ultrasoft=False),)
    )
    projected = _estimate(
        species=(Species(atoms=2, projectors=4, l_max=1, ultrasoft=False),)
    )

    nkb = 2 * 4 * 2
    qrad = 8 * int(math.sqrt(160.0) / 0.01 + 4) * 10 * 3
    vkb_and_becp = 16 * nkb * projected.npwx + 16 * nkb * 8
    extra = _per_process(projected, 1, 1) - _per_process(bare, 1, 1)
    assert extra == pytest.approx((vkb_and_becp + qrad) / 2**20)


def test_ultrasoft_species_add_the_spsi_workspace() -> None:
    norm_conserving = _estimate(scf_loop=True)
    ultrasoft = _estimate(
        scf_loop=True,
        species=(Species(atoms=2, projectors=4, l_max=1, ultrasoft=True),),
    )

    assert _per_process(ultrasoft, 1, 1) > _per_process(norm_conserving, 1, 1)


def test_hubbard_projectors_are_buffered_like_the_wavefunctions() -> None:
    """Hubbard U adds nwfcU x npol x npwx_l x nk complex numbers
    (memory_report.f90:120-125): 5 d orbitals on each of 2 atoms here."""
    plain = _estimate(scf_loop=True, n_kpoint_spin=4)
    hubbard = _estimate(
        scf_loop=True,
        n_kpoint_spin=4,
        species=(
            Species(atoms=2, projectors=4, l_max=1, ultrasoft=False, hubbard_l=2),
        ),
    )

    extra = _per_process(hubbard, 4, 1) - _per_process(plain, 4, 1)
    assert extra == pytest.approx(16 * 10 * (plain.npwx // 4) * 5 / 2**20)


@pytest.mark.parametrize(("hubbard_l", "orbitals"), [(0, 4), (1, 14), (2, 22), (3, 30)])
def test_spin_orbit_hubbard_projectors_follow_pw_x_s_j_resolved_count(
    hubbard_l: int, orbitals: int
) -> None:
    """With spin-orbit's fully relativistic pseudopotentials pw.x counts
    each of a manifold's two j functions twice, 8l + 6 orbitals per +U
    atom and 4 for s, which has one (offset_atom_wfc.f90:136-150), and
    buffers them like the spinor wavefunctions (memory_report.f90:
    120-125): 2 atoms x orbitals x npol 2 x npwx_l x 5 buffers here."""
    spinor = {
        "nspin": 4,
        "npol": 2,
        "nspin_mag": 1,
        "scf_loop": True,
        "n_kpoint_spin": 4,
    }
    plain = _estimate(**spinor)
    hubbard = _estimate(
        **spinor,
        species=(
            Species(
                atoms=2, projectors=4, l_max=1, ultrasoft=False, hubbard_l=hubbard_l
            ),
        ),
    )

    extra = _per_process(hubbard, 4, 1) - _per_process(plain, 4, 1)

    assert extra == pytest.approx(16 * 2 * orbitals * 2 * (plain.npwx // 4) * 5 / 2**20)


def test_vc_relax_holds_a_shell_per_g_vector_and_a_longer_qrad_table() -> None:
    """A vc-relax gives every G-vector its own shell, so the local
    potential holds 8 x ngm x ntyp bytes (memory_report.f90:157,
    Modules/recvec.f90:194-202), and pw.x tabulates qrad over
    cell_factor = 2 times the q range for the changing cell (memory_
    report.f90:172, input.f90:1245-1249): 4*5/2 beta pairs x (2l+1 = 3)
    for 1 species."""
    fixed = _estimate(scf_loop=True)
    variable = _estimate(scf_loop=True, variable_cell=True)

    extra = _per_process(variable, 1, 1) - _per_process(fixed, 1, 1)

    shells = 8 * fixed.ngm
    points = math.sqrt(160.0) / 0.01 + 4
    qrad = 8 * (int(points * 2) - int(points)) * 10 * 3
    assert extra == pytest.approx((shells + qrad) / 2**20)


def test_workload_counts_pairs_bands_and_plane_waves() -> None:
    estimate = _estimate(nbnd=8, n_kpoint_spin=10, scf_loop=False)

    assert estimate.workload == 10 * 8 * estimate.npwx


@pytest.mark.parametrize(
    "change, factor",
    [
        ({"n_kpoint_spin": 20}, 2),
        ({"nbnd": 16}, 2),
        ({"npol": 2, "nspin": 4}, 2),
        ({"scf_loop": True}, 3),
    ],
)
def test_workload_scales_with_pairs_bands_spinors_and_scf_passes(
    change, factor
) -> None:
    """Linear in k-point/spin pairs, bands and spinor components; a step
    with an SCF loop counts 3 passes over its k-points, an nscf one."""
    base = _estimate()

    assert _estimate(**change).workload == factor * base.workload
