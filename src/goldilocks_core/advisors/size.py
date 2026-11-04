"""size: what one pw.x step needs -- its memory for a given MPI layout
and its relative workload -- as plain arithmetic, with no four-tier
resolution and no human/llm input, unlike every other advisor.

New in v2 (v2 epic 7, #7). goldilocks-core-design.md:1637-1646 asks for
"purely arithmetic, reproduces QE's own memory_report logic... +-10-20%
precision"; the design names walltime and the optimal parallel layout,
not memory, as what needs ml.

**The memory model is a port of QE 7.3 ``PW/src/memory_report.f90``**
(#148), the routine behind pw.x's "Estimated max dynamical RAM per
process" and "Estimated total dynamical RAM". ``resource_estimate``
collects its layout-independent inputs; ``memory_estimate`` evaluates
them for one layout (``ntasks``, ``npool`` and the diagonalization grid
side, which ``advisors/parallelisation.py``'s ``diag_grid_side`` gives)
as pw.x does on its first process, whose pool holds the most k-points.
size.py takes plain values and imports neither job_resources.py nor
parallelisation.py; job_resources.py reads from it.

The terms, in memory_report's order (line numbers of that file):

- wavefunctions, nbnd x npol x npwx_l complex numbers per buffer
  (:105-110). An SCF run holds nks+1 buffers, nks = ceil(N/npool) of the
  N k-point/spin pairs (``divide_et_impera.f90:49-56``), because pw.x's
  default io_level is 0 when there is an SCF loop and 1 otherwise
  (``input.f90:909-919``; the writers never render ``disk_io``); one
  buffer when nks = 1 or without an SCF loop. Hubbard U projectors are
  buffered the same way (:120-125);
- structure factors (:154), and the local potential per G-shell (:157)
  only for vc-relax, which gives every G-vector its own shell
  (``Modules/recvec.f90:194-202``) and reports it for its final scf
  (``run_pwscf.f90:294``). pw.x's startup report runs before the shells
  are counted (``init_run.f90:81``, :109), so it never includes them; a
  fixed cell's real count, one shell per distinct |G| (about half of
  ngm when triclinic), is left out too (0.5% of TiNi mc3d-31340's
  per-process figure);
- beta projectors vkb (:165) and the qrad table (:169-177);
- rho, v and vnew (:183-188), vltot and the other dense-grid arrays
  (:191-192), and with an SCF loop rhoin plus the mixing history, which
  only pool 0 holds (:196-209);
- G-vector index arrays (:215-219);
- the largest scratch block (:301-457): Davidson's psi/hpsi(/spsi) and
  subspace matrices, local-TF's screening arrays, wfcinit, and the
  ultrasoft addusdens/addusforce/addusstress arrays (the writers set
  tprnfor/tstress, so every SCF-loop step computes forces and stress);
- ggen's global sort arrays, a floor on every process (:464-465).

Local sizes on that first process, with P = ntasks/npool processes per
pool: npwx_l = npwx/P as integers (:92); ngm/P and ngms/P G-vectors,
which pw.x spreads evenly over a pool by stick; nr1 x nr2 x ceil(nr3/P)
real-space points, its share of the z planes (``FFTXlib/src/
fft_types.f90:582-590``, :886-888).

**Approximations, all checked against pw.x.** npwx, ngm and ngms come
from the cutoff-sphere volume, ``omega * ecut**1.5 / (6 pi**2)``
(memory_report.f90:91 expanded; within 1% of pw.x's G-vector counts).
Each FFT dimension is the smallest 2,3,5-smooth length >=
2*floor(sqrt(ecut)*|a_i|/2pi)+1 (``realspace_grid_init``,
``fft_support.f90`` good_fft_order), dense for ecutrho and smooth for 4 x
ecutwfc. A species' projectors nh = number_of_proj x (l_max + 1) from its
PP_HEADER, exact when every channel up to l_max has the same number of
projectors (795 of the 1138 installed SSSP/PseudoDojo files). It
overcounts when the low channels have more, or when the header's l_max
exceeds every beta's (83 files, up to 2x for SSSP's H rrkjus), and
undercounts when the high channels have more: 260 of the 284 PseudoDojo
fully relativistic files split each l >= 1 channel by j into four
projectors against two for s, so their nh is 10-14% low and a
spin-orbit estimate about 1.5% low (CrI3 mc2d-da9644c9). wfcinit is
counted with nbnd bands, a lower bound: it needs natomwfc, and headers
give number_of_wfc without each function's l. Spin-orbit is rendered
only with fully relativistic pseudopotentials, which fixes how pw.x
counts Hubbard projectors (``offset_atom_wfc.f90:136-150``).
Martyna-Tuckerman switches pw.x's stress off (``input.f90:1361-1362``);
its ultrasoft stress scratch is still counted. Given pw.x's k-point
count, these terms reproduce its estimate within 2.1%, per process and
in total, on all 115 runs of the 2026-10-20 SCARF batch (QE 7.5, +U and
spin-orbit included; the grid rule gives pw.x's dense grid on 110 of
them); ``tests/physics/test_memory_estimate.py`` holds six. pw.x's figure is
itself a floor: measured MaxRSS exceeded it (MoS2 214 MiB per task
against 53.85 MB), which is why ``advisors/job_resources.py`` adds a
safety factor.

**`workload` is relative, not a time.** A step's diagonalisation work
scales with its k-point/spin pairs x ``nbnd`` x spinor components x
``npwx`` per pass over the k-points; a step with an SCF loop counts
``_SCF_LOOP_PASSES`` passes, an nscf step one.
``advisors/job_resources.py`` uses only the ratio between a task's
steps, to split ``max_seconds``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from pymatgen.core import Lattice

from goldilocks_core.pw_fft import good_fft_order

_BOHR_PER_ANGSTROM = 1.8897259886
_COMPLEX = 16
_REAL = 8
_INTEGER = 4
_BYTES_PER_MB = 1024 * 1024
_DAVIDSON_DIM = 2
"""``diago_david_ndim``'s default; Davidson's workspace holds
``nbndx = 2 x nbnd`` bands (``setup.f90:425-426``)."""
_MIXING_DIM = 8
"""``mixing_ndim``'s default: densities kept in the mixing history."""
_QRAD_STEP = 0.01
"""``dq`` of the qrad interpolation table, in bohr^-1."""
_SCREENING_ARRAYS = 27
"""approx_screening2's G-space arrays (memory_report.f90:360)."""
_SCF_LOOP_PASSES = 3
"""Passes over its k-points counted for a step with an SCF loop, against
one for an nscf step: about 10-20 SCF iterations of 2-3 Davidson sweeps
each, against 15-30 sweeps for one tightly converged nscf
diagonalisation. Uncalibrated (one SCARF Si timing so far); revisit when
timing data exists."""


@dataclass(frozen=True, slots=True)
class Species:
    """One species of the written cell: its atoms and, from its
    pseudopotential's PP_HEADER, ``number_of_proj`` beta functions up to
    angular momentum ``l_max``. ``ultrasoft`` is true for USPP and PAW;
    ``hubbard_l`` is the angular momentum of its +U manifold, if any."""

    atoms: int
    projectors: int
    l_max: int
    ultrasoft: bool
    hubbard_l: int | None = None

    @property
    def projector_functions(self) -> int:
        """pw.x's nh, the 2l+1 components summed over the beta
        functions, approximated as number_of_proj x (l_max + 1): exact
        for most files, high or low for the rest (module docstring)."""
        return self.projectors * (self.l_max + 1)


@dataclass(frozen=True, slots=True)
class ResourceEstimate:
    """The layout-independent inputs of one pw.x step's memory report,
    and its relative workload (module docstring)."""

    npwx: int
    ngm: int
    ngms: int
    dense_grid: tuple[int, int, int]
    smooth_grid: tuple[int, int, int]
    ecutrho_ry: float
    nbnd: int
    nspin: int
    npol: int
    nspin_mag: int
    kpoint_spin_pairs: int
    species: tuple[Species, ...]
    scf_loop: bool
    variable_cell: bool
    local_tf_mixing: bool
    workload: int


@dataclass(frozen=True, slots=True)
class MemoryEstimate:
    """pw.x's two figures for one layout, in MB (2**20 bytes):
    ``per_process_mb`` is the "max dynamical RAM per process" of the
    busiest process, ``total_mb`` the "total dynamical RAM" over all
    of them."""

    per_process_mb: float
    total_mb: float


def resource_estimate(
    lattice: Lattice,
    species: Sequence[Species],
    *,
    ecutwfc_ry: float,
    ecutrho_ry: float,
    nbnd: int,
    n_kpoint_spin: int,
    nspin: int,
    npol: int,
    nspin_mag: int,
    scf_loop: bool,
    variable_cell: bool,
    local_tf_mixing: bool,
) -> ResourceEstimate:
    """The estimate of one pw.x step on the written cell (``lattice``,
    ``species``). ``n_kpoint_spin`` is the k-point/spin pairs pw.x
    distributes; ``nspin``, ``npol`` and ``nspin_mag`` are its density,
    spinor and magnetization components (``parallelisation.
    qe_spin_layout``); ``scf_loop`` is true when the step runs its own
    SCF loop (``plan.SCF_LIKE_PURPOSES``) and ``variable_cell`` for
    vc-relax. Every value is already resolved."""
    volume_bohr3 = lattice.volume * _BOHR_PER_ANGSTROM**3
    lengths_bohr = tuple(length * _BOHR_PER_ANGSTROM for length in lattice.abc)
    smooth_cutoff = 4 * ecutwfc_ry
    double_grid = ecutrho_ry > smooth_cutoff
    npwx = _sphere_count(volume_bohr3, ecutwfc_ry)
    ngm = _sphere_count(volume_bohr3, ecutrho_ry)
    dense_grid = _fft_grid(lengths_bohr, ecutrho_ry)
    passes = _SCF_LOOP_PASSES if scf_loop else 1
    return ResourceEstimate(
        npwx=npwx,
        ngm=ngm,
        ngms=_sphere_count(volume_bohr3, smooth_cutoff) if double_grid else ngm,
        dense_grid=dense_grid,
        smooth_grid=(
            _fft_grid(lengths_bohr, smooth_cutoff) if double_grid else dense_grid
        ),
        ecutrho_ry=ecutrho_ry,
        nbnd=nbnd,
        nspin=nspin,
        npol=npol,
        nspin_mag=nspin_mag,
        kpoint_spin_pairs=n_kpoint_spin,
        species=tuple(species),
        scf_loop=scf_loop,
        variable_cell=variable_cell,
        local_tf_mixing=local_tf_mixing,
        workload=n_kpoint_spin * nbnd * npol * npwx * passes,
    )


def memory_estimate(
    estimate: ResourceEstimate, *, ntasks: int, npool: int, diag_side: int
) -> MemoryEstimate:
    """pw.x's estimate for ``estimate`` run on ``ntasks`` processes in
    ``npool`` pools with an s x s diagonalization grid, s =
    ``diag_side`` (memory_report.f90:459-467). A pool always has at
    least one process."""
    procs = max(1, ntasks // npool)
    local = _local_sizes(estimate, procs)
    resident = _resident_bytes(estimate, local, npool)
    mixing = (
        _COMPLEX * local.ngm * estimate.nspin * 2 * _MIXING_DIM
        if estimate.scf_loop
        else 0.0
    )
    scratch = _scratch_bytes(estimate, local, npool, diag_side)
    ggen_sort = (2 * _INTEGER + _REAL) * estimate.ngm
    per_process = max(resident + mixing + scratch, ggen_sort)
    total = (resident + scratch) * ntasks + mixing * ntasks / npool
    return MemoryEstimate(
        per_process_mb=per_process / _BYTES_PER_MB,
        total_mb=total / _BYTES_PER_MB,
    )


@dataclass(frozen=True, slots=True)
class _Local:
    """Sizes on pw.x's first process (module docstring)."""

    npwx: int
    ngm: float
    ngms: float
    nnr: int
    nnrs: int


def _local_sizes(estimate: ResourceEstimate, procs: int) -> _Local:
    return _Local(
        npwx=estimate.npwx // procs,
        ngm=estimate.ngm / procs,
        ngms=estimate.ngms / procs,
        nnr=_local_grid_points(estimate.dense_grid, procs),
        nnrs=_local_grid_points(estimate.smooth_grid, procs),
    )


def _local_grid_points(grid: tuple[int, int, int], procs: int) -> int:
    nr1, nr2, nr3 = grid
    return nr1 * nr2 * math.ceil(nr3 / procs)


def _resident_bytes(estimate: ResourceEstimate, local: _Local, npool: int) -> float:
    """``ram``: what stays allocated through the run (memory_report.f90:
    105-219), without the mixing history."""
    species = estimate.species
    ntyp = len(species)
    nspin = estimate.nspin
    pool_kpoints = math.ceil(estimate.kpoint_spin_pairs / npool)
    buffers = pool_kpoints + 1 if estimate.scf_loop and pool_kpoints > 1 else 1
    wavefunctions = estimate.nbnd + _hubbard_wavefunctions(estimate)
    density = (_COMPLEX * local.ngm + _REAL * local.nnr) * nspin
    density_copies = 4 if estimate.scf_loop else 3
    shells = local.ngm if estimate.variable_cell else 0.0
    return (
        _COMPLEX * wavefunctions * estimate.npol * local.npwx * buffers
        + _COMPLEX * local.ngm * ntyp
        + _REAL * shells * ntyp
        + _COMPLEX * _projector_count(species) * local.npwx
        + _qrad_bytes(estimate)
        + density_copies * density
        + _COMPLEX * (local.nnr + local.ngm * (1 + ntyp))
        + _REAL * local.nnr * (2 + nspin)
        + _REAL * local.ngm * 4
        + _INTEGER * local.ngm * 7
        + _INTEGER * local.ngms * 2
    )


def _scratch_bytes(
    estimate: ResourceEstimate, local: _Local, npool: int, diag_side: int
) -> float:
    """``ram_``: the largest block allocated and freed again
    (memory_report.f90:301-457)."""
    nbnd = estimate.nbnd
    npol = estimate.npol
    nbndx = _DAVIDSON_DIM * nbnd
    ultrasoft = any(item.ultrasoft for item in estimate.species)
    workspaces = 3 if ultrasoft else 2
    blocks = [
        _COMPLEX * 3 * (nbndx // diag_side) ** 2
        + _COMPLEX * _projector_count(estimate.species) * npol * nbnd
        + _COMPLEX * workspaces * nbndx * npol * local.npwx,
        _COMPLEX * local.npwx * nbnd * (npol + 1) + _REAL * nbnd * (3 * nbnd + 1),
    ]
    if estimate.scf_loop and estimate.local_tf_mixing:
        blocks.append(_COMPLEX * local.ngm * _SCREENING_ARRAYS + _REAL * local.nnrs)
    if ultrasoft:
        blocks.extend(_ultrasoft_scratch(estimate, local, npool))
    return max(blocks)


def _ultrasoft_scratch(
    estimate: ResourceEstimate, local: _Local, npool: int
) -> list[float]:
    """addusdens, and with an SCF loop addusforce and addusstress
    (memory_report.f90:393-448)."""
    ultrasoft = [item for item in estimate.species if item.ultrasoft]
    pairs = max(
        item.projector_functions * (item.projector_functions + 1) // 2
        for item in ultrasoft
    )
    atoms = max(item.atoms for item in ultrasoft)
    lmaxq = 2 * _lmax_kb(estimate.species) + 1
    harmonics = lmaxq * lmaxq
    ngm_pool = math.floor(local.ngm) // npool
    magnetic = local.ngm * estimate.nspin_mag
    blocks = [
        _REAL * ngm_pool * (harmonics + 1)
        + _COMPLEX * (magnetic + ngm_pool * (atoms + pairs + 1))
    ]
    if estimate.scf_loop:
        blocks.append(
            _REAL * (magnetic + ngm_pool * (harmonics + 1))
            + _COMPLEX * ngm_pool * (pairs + 3 * atoms)
            + _REAL * pairs * atoms * 3 * estimate.nspin_mag
        )
        blocks.append(
            _REAL * (magnetic + ngm_pool * (2 * harmonics + 1))
            + _COMPLEX * ngm_pool * (pairs + 3 + estimate.nspin)
        )
    return blocks


def _qrad_bytes(estimate: ResourceEstimate) -> float:
    lmaxq = 2 * _lmax_kb(estimate.species) + 1
    if lmaxq <= 0:
        return 0.0
    cell_factor = 2.0 if estimate.variable_cell else 1.0
    points = int((math.sqrt(estimate.ecutrho_ry) / _QRAD_STEP + 4) * cell_factor)
    nbeta = max(item.projectors for item in estimate.species)
    return _REAL * points * nbeta * (nbeta + 1) / 2 * lmaxq * len(estimate.species)


def _projector_count(species: Sequence[Species]) -> int:
    """pw.x's nkb: projector functions summed over every atom."""
    return sum(item.atoms * item.projector_functions for item in species)


def _lmax_kb(species: Sequence[Species]) -> int:
    """The highest beta angular momentum of any species; -1 with none."""
    return max((item.l_max for item in species if item.projectors), default=-1)


def _hubbard_wavefunctions(estimate: ResourceEstimate) -> int:
    """pw.x's nwfcU: per +U atom, 2l+1 orbitals, or with spin-orbit's
    fully relativistic pseudopotentials 8l+6, because
    ``offset_atom_wfc.f90:136-150`` counts each of the two j functions
    twice (4 for l=0, which has one)."""
    total = 0
    for item in estimate.species:
        if item.hubbard_l is None:
            continue
        angular = item.hubbard_l
        if estimate.npol == 1:
            orbitals = 2 * angular + 1
        else:
            orbitals = 4 if angular == 0 else 8 * angular + 6
        total += item.atoms * orbitals
    return total


def _sphere_count(volume_bohr3: float, ecut_ry: float) -> int:
    """Reciprocal-lattice points inside the cutoff sphere |G|^2 <= ecut,
    ``NINT(4pi/3 * sqrt(ecut)**3 / ((2pi)**3/omega))``."""
    return math.floor(volume_bohr3 * ecut_ry**1.5 / (6 * math.pi**2) + 0.5)


def _fft_grid(lengths_bohr: tuple[float, ...], ecut_ry: float) -> tuple[int, int, int]:
    nr1, nr2, nr3 = (
        good_fft_order(2 * math.floor(math.sqrt(ecut_ry) * length / (2 * math.pi)) + 1)
        for length in lengths_bohr
    )
    return nr1, nr2, nr3
