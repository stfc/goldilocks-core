"""The phonon tasks' ph.x, d3hess.x, q2r.x and matdyn.x inputs (#215)."""

from __future__ import annotations

import dataclasses

import pytest
from pymatgen.core import Structure
from support import graphene_monolayer, mc3d_42058_silicon

from goldilocks_core.advisors.k_path import KPathDecision, PathBranch, PathVertex
from goldilocks_core.advisors.parallelisation import ParallelisationDecision
from goldilocks_core.advisors.phonon import (
    PhononDecision,
    PhononDosDecision,
    Q2rDecision,
)
from goldilocks_core.advisors.q_sampling import QSamplingDecision
from goldilocks_core.generation.errors import GenerationError
from goldilocks_core.generation.quantum_espresso.bands import path_rows
from goldilocks_core.generation.quantum_espresso.namelists import render_namelist
from goldilocks_core.generation.quantum_espresso.phonon import write_qe_phonon
from goldilocks_core.step_settings import (
    DispersionSettings,
    MatdynSettings,
    PhSettings,
    Q2rSettings,
)
from goldilocks_core.steps import (
    DynamicalMatricesCheck,
    SharedContext,
    StdoutMarkerCheck,
    Step,
)

_CTX = SharedContext(prefix="pwscf", outdir="./out", pseudo_dir="./pseudo")

_PhononSettings = tuple[PhSettings, Q2rSettings, MatdynSettings, DispersionSettings]

_GAMMA = PathVertex("Gamma", (0.0, 0.0, 0.0))


def _path(
    cell: Structure,
    *branches: PathBranch,
    convention: str,
    lattice_type: str,
    space_group: str,
) -> KPathDecision:
    return KPathDecision(
        branches=branches,
        k_path_distance=0.025,
        n_kpoints=sum(sum(branch.steps) + 1 for branch in branches),
        convention=convention,
        lattice_type=lattice_type,
        space_group=space_group,
        primitive_cells=1,
        cell=cell,
    )


def _split_fcc_path() -> KPathDecision:
    """The first two branches of diamond Si's path where matdyn.x adds the
    non-analytic term: Gamma-X-W-K-Gamma, then Gamma-L from the same Gamma."""
    return _path(
        mc3d_42058_silicon(),
        PathBranch(
            (
                _GAMMA,
                PathVertex("X", (-0.5, 0.0, -0.5)),
                PathVertex("W", (-0.75, -0.25, -0.5)),
                PathVertex("K", (-0.75, -0.375, -0.375)),
                _GAMMA,
            ),
            (47, 24, 17, 50),
        ),
        PathBranch((_GAMMA, PathVertex("L", (-0.5, -0.5, -0.5))), (41,)),
        convention="setyawan_curtarolo",
        lattice_type="FCC",
        space_group="Fd-3m (227)",
    )


def _hex2d_path() -> KPathDecision:
    """Graphene's Gamma-M-K-Gamma, Gamma only at its ends."""
    return _path(
        graphene_monolayer(),
        PathBranch(
            (
                _GAMMA,
                PathVertex("M", (0.5, 0.0, 0.0)),
                PathVertex("K", (1 / 3, 1 / 3, 0.0)),
                _GAMMA,
            ),
            (59, 35, 69),
        ),
        convention="bravais_2d",
        lattice_type="HEX2D",
        space_group="P6/mmm (191)",
    )


def _silicon(
    parallel: ParallelisationDecision | None = None,
) -> _PhononSettings:
    """Diamond Si's phonon steps, as the advisors decide them on its written
    cell: the 7x7x7 q-mesh (20 irreducible q-points, work 2401), the balanced
    ph protocol, asr 'simple' and the 21x21x21 DOS mesh at 0.10 1/Angstrom;
    the first step runs 4 pools. The dispersion follows ``_split_fcc_path``."""
    q2r = Q2rDecision(asr="simple", loto_2d=False)
    return (
        PhSettings(
            q_sampling=QSamplingDecision(
                mesh=(7, 7, 7), q_distance=0.3, n_irr_q=20, work=2401
            ),
            phonon=PhononDecision(tr2_ph=1e-18, alpha_mix=0.4, nmix_ph=8),
            parallel=parallel
            or ParallelisationDecision(npool=4, ndiag=None, kpoint_spin_pairs=72),
        ),
        Q2rSettings(q2r=q2r),
        MatdynSettings(
            q2r=q2r,
            phonon_dos=PhononDosDecision(
                mesh=(21, 21, 21), dos_q_distance=0.1, delta_e=1.0
            ),
        ),
        DispersionSettings(q2r=q2r, path=_split_fcc_path()),
    )


def _graphene() -> _PhononSettings:
    """Graphene with isolation=slab: the 10x10x1 q-mesh (14 irreducible
    q-points, work 700), loto_2d, the 30x30x1 DOS mesh and
    ``_hex2d_path``."""
    q2r = Q2rDecision(asr="simple", loto_2d=True)
    return (
        PhSettings(
            q_sampling=QSamplingDecision(
                mesh=(10, 10, 1), q_distance=0.3, n_irr_q=14, work=700
            ),
            phonon=PhononDecision(tr2_ph=1e-18, alpha_mix=0.4, nmix_ph=8),
            parallel=ParallelisationDecision(npool=2, ndiag=None, kpoint_spin_pairs=19),
        ),
        Q2rSettings(q2r=q2r),
        MatdynSettings(
            q2r=q2r,
            phonon_dos=PhononDosDecision(
                mesh=(30, 30, 1), dos_q_distance=0.1, delta_e=1.0
            ),
        ),
        DispersionSettings(q2r=q2r, path=_hex2d_path()),
    )


def _step(steps: list[Step], name: str) -> Step:
    (step,) = (step for step in steps if step.name == name)
    return step


def _keywords(namelist: str) -> dict[str, str]:
    """``namelist``'s ``key = value`` lines, values as written."""
    pairs = (line.split("=", 1) for line in namelist.splitlines() if "=" in line)
    return {key.strip(): value.strip() for key, value in pairs}


def test_ph_in_starts_with_a_title_line_ph_x_reads_as_one() -> None:
    """ph.x reads the first line as a title of at most 75 characters, and one
    containing '&inputph' as a missing title (QE 7.3
    ``PHonon/PH/phq_readin.f90:229-246``, ``Modules/run_info.f90:15``)."""
    ph = _step(write_qe_phonon(*_silicon(), _CTX, d3hess=False), "ph")

    title, namelist = ph.files["ph.in"].split("\n", 1)

    assert title == "phonons on a 7x7x7 q-mesh (goldilocks)"
    assert len(title) <= 75
    assert "&inputph" not in title.lower()
    assert namelist.startswith("&INPUTPH\n")


def test_ph_in_runs_the_q_mesh_with_the_ph_step_s_settings() -> None:
    """ldisp on the q-mesh, the linear-response settings, the dynamical
    matrices in <prefix>.dyn and recover, which resumes a stopped run and
    starts a fresh one. Nothing else: no max_seconds (the job timer stops
    ph.x), no epsil or zeu (ph.x decides them at Gamma, and epsil stops it on
    a smeared run, ``prepare_q.f90:137-180``, ``phq_readin.f90:944-945``), no
    asr (Gamma-Gamma tricks only), no amass (from the save) and no k-mesh
    (the scf's)."""
    ph = _step(write_qe_phonon(*_silicon(), _CTX, d3hess=False), "ph")

    namelist = ph.files["ph.in"].split("\n", 1)[1]

    assert _keywords(namelist) == {
        "outdir": "'./out'",
        "prefix": "'pwscf'",
        "tr2_ph": "1e-18",
        "alpha_mix(1)": "0.4",
        "nmix_ph": "8",
        "fildyn": "'pwscf.dyn'",
        "recover": ".true.",
        "ldisp": ".true.",
        "nq1": "7",
        "nq2": "7",
        "nq3": "7",
    }
    for absent in ("max_seconds", "epsil", "zeu", "asr", "amass", "nk1", "k1"):
        assert absent not in namelist


@pytest.mark.parametrize(
    ("ndiag", "args"),
    [
        (None, ("-npool", "4", "-in", "ph.in")),
        (16, ("-npool", "4", "-ndiag", "16", "-in", "ph.in")),
    ],
)
def test_ph_x_runs_on_the_allocation_with_the_first_step_s_pools(
    ndiag: int | None, args: tuple[str, ...]
) -> None:
    """ph.x runs on every task of the job, with the first pw.x step's pools
    and diagonalization group, and no images."""
    parallel = ParallelisationDecision(npool=4, ndiag=ndiag, kpoint_spin_pairs=72)

    ph = _step(write_qe_phonon(*_silicon(parallel), _CTX, d3hess=False), "ph")

    assert ph.args == args
    assert ph.ntasks is None


def test_the_ph_step_declares_its_check_its_stop_file_and_its_restart_data() -> None:
    """The submission script checks every dynamical matrix <prefix>.dyn0 lists,
    stops ph.x through <prefix>.EXIT, which ph.x looks for in the working
    directory, and keeps or deletes ph.x's recover data under <outdir>/_ph0
    and its matrices."""
    ph = _step(write_qe_phonon(*_silicon(), _CTX, d3hess=False), "ph")

    assert dataclasses.replace(ph, files={}) == Step(
        name="ph",
        executable="ph.x",
        args=("-npool", "4", "-in", "ph.in"),
        stdout="ph.out",
        completion=DynamicalMatricesCheck("pwscf.dyn"),
        stop_file="pwscf.EXIT",
        restart_data=("./out/_ph0", "pwscf.dyn*"),
    )


def test_d3hess_x_runs_only_for_dft_d3_before_ph_x_on_one_task() -> None:
    """d3hess.x writes the D3 Hessian ph.x reads, <outdir>/<prefix>.hess,
    from its defaults: q_gamma off, since a Gamma-only Hessian is refused at
    q /= 0 (``PHonon/PH/d2ionq_disp.f90:87-88``). It writes no status file
    and prints JOB DONE at its end (``PP/src/d3hess.f90:83``)."""
    without = write_qe_phonon(*_silicon(), _CTX, d3hess=False)
    with_d3 = write_qe_phonon(*_silicon(), _CTX, d3hess=True)

    assert "d3hess" not in [step.name for step in without]
    assert with_d3[1:] == without
    assert with_d3[0] == Step(
        name="d3hess",
        executable="d3hess.x",
        args=("-in", "d3hess.in"),
        files={
            "d3hess.in": "&INPUT\n"
            "   prefix           = 'pwscf'\n"
            "   outdir           = './out'\n"
            "/\n"
        },
        stdout="d3hess.out",
        completion=StdoutMarkerCheck("JOB DONE"),
        ntasks=1,
    )


def test_q2r_x_and_matdyn_x_turn_the_matrices_into_a_phonon_dos() -> None:
    """q2r.x reads <prefix>.dyn0 and the matrices it lists into the force
    constants <prefix>.fc; matdyn.x interpolates them on the DOS mesh with
    tetrahedra (degauss 0, its default) into <prefix>.phdos. Blank flfrq and
    flvec stop it writing the frequencies and modes of every mesh point
    (``PHonon/PH/matdyn.f90:564-583``, ``:760-778``). Both run on one task
    and print JOB DONE."""
    steps = write_qe_phonon(*_silicon(), _CTX, d3hess=False)
    q2r, phonon_dos = _step(steps, "q2r"), _step(steps, "phonon_dos")

    assert dataclasses.replace(q2r, files={}) == Step(
        name="q2r",
        executable="q2r.x",
        args=("-in", "q2r.in"),
        stdout="q2r.out",
        completion=StdoutMarkerCheck("JOB DONE"),
        ntasks=1,
    )
    assert q2r.files["q2r.in"] == (
        "&INPUT\n"
        "   fildyn           = 'pwscf.dyn'\n"
        "   flfrc            = 'pwscf.fc'\n"
        "   zasr             = 'simple'\n"
        "/\n"
    )
    assert dataclasses.replace(phonon_dos, files={}) == Step(
        name="phonon_dos",
        executable="matdyn.x",
        args=("-in", "phonon_dos.in"),
        stdout="phonon_dos.out",
        completion=StdoutMarkerCheck("JOB DONE"),
        ntasks=1,
    )
    assert phonon_dos.files["phonon_dos.in"] == (
        "&INPUT\n"
        "   flfrc            = 'pwscf.fc'\n"
        "   asr              = 'simple'\n"
        "   dos              = .true.\n"
        "   nk1              = 21\n"
        "   nk2              = 21\n"
        "   nk3              = 21\n"
        "   deltae           = 1.0\n"
        "   fldos            = 'pwscf.phdos'\n"
        "   flfrq            = ' '\n"
        "   flvec            = ' '\n"
        "/\n"
    )


def test_dispersion_in_lists_the_path_after_matdyn_x_s_namelist() -> None:
    """matdyn.x interpolates q2r.x's force constants, with the same acoustic
    sum rule, at the points of the rows after its namelist, which it reads as
    pw.x reads a K_POINTS crystal_b card (``q_in_band_form``,
    ``q_in_cryst_coord``; QE 7.3 ``PHonon/PH/matdyn.f90:485-501``): the
    number of rows, then x y z n, with a count of 0 where Gamma ends one
    branch and its second copy starts the next. It writes the frequencies to
    <prefix>.freq and <prefix>.freq.gp (``:760-776``); a blank flvec leaves
    out the modes of every point (``:564-569``)."""
    steps = write_qe_phonon(*_silicon(), _CTX, d3hess=False)

    assert _step(steps, "dispersion").files["dispersion.in"] == (
        "&INPUT\n"
        "   flfrc            = 'pwscf.fc'\n"
        "   asr              = 'simple'\n"
        "   flfrq            = 'pwscf.freq'\n"
        "   flvec            = ' '\n"
        "   q_in_band_form   = .true.\n"
        "   q_in_cryst_coord = .true.\n"
        "/\n"
        "  7\n"
        "  0  0  0  47  ! Gamma\n"
        "  -0.5  0  -0.5  24  ! X\n"
        "  -0.75  -0.25  -0.5  17  ! W\n"
        "  -0.75  -0.375  -0.375  50  ! K\n"
        "  0  0  0  0  ! Gamma\n"
        "  0  0  0  41  ! Gamma\n"
        "  -0.5  -0.5  -0.5  1  ! L\n"
    )


def test_the_dispersion_runs_on_one_task_with_q2r_s_sum_rule() -> None:
    """Like the phonon DOS, matdyn.x runs on one task and passes on JOB DONE,
    with no stop file and nothing a rerun resumes from; it applies the sum
    rule of the q2r record, here a request's 'crystal'."""
    ph, q2r, matdyn, dispersion = _silicon()
    crystal = Q2rDecision(asr="crystal", loto_2d=False)
    dispersion = dataclasses.replace(dispersion, q2r=crystal)

    steps = write_qe_phonon(ph, q2r, matdyn, dispersion, _CTX, d3hess=False)

    step = _step(steps, "dispersion")
    assert dataclasses.replace(step, files={}) == Step(
        name="dispersion",
        executable="matdyn.x",
        args=("-in", "dispersion.in"),
        stdout="dispersion.out",
        completion=StdoutMarkerCheck("JOB DONE"),
        ntasks=1,
    )
    assert _keywords(step.files["dispersion.in"])["asr"] == "'crystal'"


def test_a_slab_under_2d_truncation_takes_the_2d_non_analytic_term() -> None:
    """loto_2d in q2r.x and both matdyn.x runs for isolation=slab, after QE's
    PHonon example17; the q- and DOS meshes keep one division along the
    vacuum, and the dispersion lists the path's rows as they are."""
    steps = write_qe_phonon(*_graphene(), _CTX, d3hess=False)

    q2r = _keywords(_step(steps, "q2r").files["q2r.in"])
    matdyn = _keywords(_step(steps, "phonon_dos").files["phonon_dos.in"])
    ph = _keywords(_step(steps, "ph").files["ph.in"].split("\n", 1)[1])
    namelist, rows = _step(steps, "dispersion").files["dispersion.in"].split("/\n")
    dispersion = _keywords(namelist)
    assert q2r["loto_2d"] == matdyn["loto_2d"] == dispersion["loto_2d"] == ".true."
    assert (ph["nq1"], ph["nq2"], ph["nq3"]) == ("10", "10", "1")
    assert (matdyn["nk1"], matdyn["nk2"], matdyn["nk3"]) == ("30", "30", "1")
    assert rows.splitlines() == path_rows(_hex2d_path())
    assert rows.splitlines()[0] == "  4"


def test_the_steps_run_in_order_on_the_shared_prefix_and_outdir() -> None:
    """d3hess.x and ph.x read the first step's save, q2r.x ph.x's matrices
    and both matdyn.x runs q2r.x's force constants, so every name the inputs
    give follows the shared context."""
    ctx = SharedContext(prefix="si", outdir="/scratch/run", pseudo_dir="./pseudo")

    steps = write_qe_phonon(*_silicon(), ctx, d3hess=True)

    assert [step.name for step in steps] == [
        "d3hess",
        "ph",
        "q2r",
        "phonon_dos",
        "dispersion",
    ]
    assert [step.executable for step in steps] == [
        "d3hess.x",
        "ph.x",
        "q2r.x",
        "matdyn.x",
        "matdyn.x",
    ]
    d3hess, ph, q2r, phonon_dos, dispersion = (
        _keywords(step.files[f"{step.name}.in"].split("&", 1)[1]) for step in steps
    )
    assert d3hess == {"prefix": "'si'", "outdir": "'/scratch/run'"}
    assert (ph["prefix"], ph["outdir"], ph["fildyn"]) == (
        "'si'",
        "'/scratch/run'",
        "'si.dyn'",
    )
    assert (q2r["fildyn"], q2r["flfrc"]) == ("'si.dyn'", "'si.fc'")
    assert (phonon_dos["flfrc"], phonon_dos["fldos"]) == ("'si.fc'", "'si.phdos'")
    assert (dispersion["flfrc"], dispersion["flfrq"]) == ("'si.fc'", "'si.freq'")
    assert not {"dos", "fldos", "nk1", "nk2", "nk3", "deltae"} & dispersion.keys()
    assert steps[1].completion == DynamicalMatricesCheck("si.dyn")
    assert steps[1].stop_file == "si.EXIT"
    assert steps[1].restart_data == ("/scratch/run/_ph0", "si.dyn*")


@pytest.mark.parametrize(
    ("keywords", "binary"),
    [({"q_gamma": False}, "d3hess"), ({"prefix": "pwscf"}, "q2r")],
    ids=["d3hess_q_gamma", "q2r_prefix"],
)
def test_keywords_the_writer_leaves_out_are_refused(
    keywords: dict[str, object], binary: str
) -> None:
    """d3hess.x's q_gamma must stay off for a q-mesh, and q2r.x's prefix would
    be put in front of fildyn (``PHonon/PH/do_q2r.f90:85-89``); ASE's schemas
    leave both out, so a writer cannot set them by mistake."""
    with pytest.raises(GenerationError, match=next(iter(keywords))):
        render_namelist(keywords, binary=binary)
