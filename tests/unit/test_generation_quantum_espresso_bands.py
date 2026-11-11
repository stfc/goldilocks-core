"""The band task's inputs (#118): the K_POINTS crystal_b card pw.x reads the
band path from, bands.in against scf.in for the same system, and one bands.x
run per spin channel."""

from __future__ import annotations

import dataclasses

import pytest
from pymatgen.core import Structure
from support import antiferromagnetic_nickel_oxide, mc3d_42058_silicon

from goldilocks_core.advisors.boundary import BoundaryFacts
from goldilocks_core.advisors.convergence import ConvergenceDecision
from goldilocks_core.advisors.cutoffs import CutoffsDecision
from goldilocks_core.advisors.electron_count import ElectronCountDecision
from goldilocks_core.advisors.hubbard_u import HubbardU, HubbardUDecision
from goldilocks_core.advisors.k_path import KPathDecision, PathBranch, PathVertex
from goldilocks_core.advisors.k_sampling import KSamplingDecision
from goldilocks_core.advisors.magnetic_config import (
    MagneticConfigFacts,
    OrderingRecord,
)
from goldilocks_core.advisors.nbnd import NbndDecision
from goldilocks_core.advisors.occupations import OccupationsDecision
from goldilocks_core.advisors.parallelisation import ParallelisationDecision
from goldilocks_core.advisors.vdw_method import VdwFacts
from goldilocks_core.generation.errors import GenerationError
from goldilocks_core.generation.quantum_espresso.bands import (
    k_points_crystal_b,
    path_rows,
    write_qe_bands,
    write_qe_bands_x,
)
from goldilocks_core.generation.quantum_espresso.scf import write_qe_scf
from goldilocks_core.step_settings import PwSettings
from goldilocks_core.steps import (
    ExitStatusCheck,
    SharedContext,
    StdoutMarkerCheck,
    Step,
)
from goldilocks_core.system_settings import SystemSettings

_CTX = SharedContext(prefix="band", outdir="./scratch", pseudo_dir="./pseudo")


def _path(cell: Structure, *branches: PathBranch) -> KPathDecision:
    return KPathDecision(
        branches=branches,
        k_path_distance=0.025,
        n_kpoints=sum(sum(branch.steps) + 1 for branch in branches),
        convention="setyawan_curtarolo",
        lattice_type="FCC",
        space_group="Fd-3m (227)",
        primitive_cells=1,
        cell=cell,
    )


def _fcc_path(cell: Structure) -> KPathDecision:
    """Gamma-X-W | U-X of the fcc table: two branches, 90 points."""
    x = PathVertex("X", (0.5, 0.0, 0.5))
    return _path(
        cell,
        PathBranch(
            (
                PathVertex("Gamma", (0.0, 0.0, 0.0)),
                x,
                PathVertex("W", (0.5, 0.25, 0.75)),
            ),
            (47, 24),
        ),
        PathBranch((PathVertex("U", (0.625, 0.25, 0.625)), x), (17,)),
    )


def _system(
    structure: Structure,
    pseudo_metadata_factory,
    nelec: float,
    *,
    seeds: dict[str, float] | None = None,
    hubbard: tuple[HubbardU, ...] = (),
) -> SystemSettings:
    """``structure`` as the written cell; spin-polarized with ``seeds`` as
    its starting magnetization when given."""
    elements = sorted({site.specie.symbol for site in structure})
    return SystemSettings(
        functional="PBEsol",
        cutoffs=CutoffsDecision(ecutwfc_ry=45.0, ecutrho_ry=360.0),
        electron_count=ElectronCountDecision(nelec=nelec, tot_charge=0.0),
        pseudopotentials=tuple(pseudo_metadata_factory(symbol) for symbol in elements),
        magnetic=MagneticConfigFacts(
            cell=structure,
            ordering=OrderingRecord(
                requested=None if seeds is None else "afm",
                applied=None if seeds is None else "afm-1",
            ),
            spin_polarized=seeds is not None,
            magnetic_elements=(),
            starting_magnetization=seeds,
            compensated=seeds is not None,
            tot_magnetization=None,
            spin_orbit_enabled=False,
            angle1=None,
            angle2=None,
        ),
        vdw=VdwFacts(use_vdw=False, method=None),
        hubbard=HubbardUDecision(
            u_values=hubbard, projectors="ortho-atomic" if hubbard else None
        ),
        boundary=BoundaryFacts(isolation="periodic"),
    )


def _steps(
    path: KPathDecision,
    occupations: OccupationsDecision,
    parallel: ParallelisationDecision,
) -> tuple[PwSettings, PwSettings]:
    """An scf step and a bands step that share occupations, convergence and
    parallelisation, as the band task's two pw.x steps can."""
    shared = PwSettings(
        occupations=occupations,
        convergence=ConvergenceDecision(
            conv_thr=1e-9,
            etot_conv_thr=1e-5,
            mixing_beta=0.4,
            electron_maxstep=80,
            mixing_mode="plain",
            mixing_fixed_ns=None,
        ),
        parallel=parallel,
    )
    scf = dataclasses.replace(
        shared,
        k_sampling=KSamplingDecision(mesh=(8, 8, 8), shift=(0, 0, 0), k_distance=0.15),
        n_irr_k=29,
        nbnd=NbndDecision(nbnd=8),
        max_seconds=2000,
    )
    bands = dataclasses.replace(
        shared, k_path=path, nbnd=NbndDecision(nbnd=12), max_seconds=5000
    )
    return scf, bands


def _silicon(pseudo_metadata_factory):
    """Diamond Si (MC3D mc3d-42058): no spin, fixed occupations, 4 pools."""
    structure = mc3d_42058_silicon()
    return _system(structure, pseudo_metadata_factory, 8.0), *_steps(
        _fcc_path(structure),
        OccupationsDecision(occupations="fixed", smearing_type=None, degauss=None),
        ParallelisationDecision(npool=4, ndiag=None, kpoint_spin_pairs=90),
    )


def _nickel_oxide(pseudo_metadata_factory):
    """AFM-II NiO, Ni1 up and Ni2 down, with U on Ni 3d: cold smearing, 4 pools
    and a 2 x 2 diagonalization grid."""
    structure = antiferromagnetic_nickel_oxide()
    system = _system(
        structure,
        pseudo_metadata_factory,
        48.0,
        seeds={"Ni1": 0.5, "Ni2": -0.5, "O": 0.0},
        hubbard=(HubbardU("Ni", "3d", 6.2, "table"),),
    )
    return system, *_steps(
        _fcc_path(structure),
        OccupationsDecision(occupations="smearing", smearing_type="cold", degauss=0.01),
        ParallelisationDecision(npool=4, ndiag=4, kpoint_spin_pairs=180),
    )


_PER_STEP_KEYWORDS = ("calculation", "max_seconds", "nbnd", "tprnfor", "tstress")


def _shared(content: str) -> list[str]:
    """``content`` without its K_POINTS card and the keywords ``_steps``
    sets per step."""
    cards = [card for card in content.split("\n\n") if not card.startswith("K_POINTS")]
    return [
        line
        for card in cards
        for line in card.splitlines()
        if line.split("=")[0].strip() not in _PER_STEP_KEYWORDS
    ]


def test_the_card_gives_each_vertex_its_steps_to_the_next_and_its_label() -> None:
    """K_POINTS crystal_b (QE 7.3 ``Modules/read_cards.f90:719-838``): the
    vertex count, then one row per vertex whose fourth number is the steps
    to the next vertex -- 0 at the end of a branch another follows, where
    pw.x jumps to the next vertex, and 1, read but unused, at the last. The
    label is a trailing comment: a row whose first character is a letter, not
    a digit, sign or point, is read as a symbolic point, which needs ibrav
    other than 0. QE counts the path's points from the card
    (``read_cards.f90:824-827``)."""
    path = _fcc_path(mc3d_42058_silicon())

    card = k_points_crystal_b(path)

    assert card == (
        "K_POINTS crystal_b\n"
        "  5\n"
        "  0  0  0  47  ! Gamma\n"
        "  0.5  0  0.5  24  ! X\n"
        "  0.5  0.25  0.75  0  ! W\n"
        "  0.625  0.25  0.625  17  ! U\n"
        "  0.5  0  0.5  1  ! X\n"
    )
    rows = card.splitlines()[2:]
    assert all(row.lstrip()[0] in "0123456789+-." for row in rows)
    weights = [int(row.split()[3]) for row in rows]
    assert sum(weights[:-1]) + 1 + weights[:-1].count(0) == path.n_kpoints == 90


def test_card_numbers_follow_the_card_rule() -> None:
    """#178: 10 significant digits, and 0, never -0, below 1e-10."""
    path = _path(
        mc3d_42058_silicon(),
        PathBranch(
            (
                PathVertex("Gamma", (-0.0, 1e-17, -3e-11)),
                PathVertex("K", (0.375, 0.1 + 0.2, 2 / 3)),
            ),
            (13,),
        ),
    )

    assert path_rows(path) == [
        "  2",
        "  0  0  0  13  ! Gamma",
        "  0.375  0.3  0.6666666667  1  ! K",
    ]


@pytest.mark.parametrize(
    ("material", "args", "shared_lines"),
    [
        (_silicon, ("-npool", "4", "-in", "bands.in"), ()),
        (
            _nickel_oxide,
            ("-npool", "4", "-ndiag", "4", "-in", "bands.in"),
            (
                "   nspin            = 2",
                "   starting_magnetization(2) = -0.5",
                "HUBBARD (ortho-atomic)",
                "  U  Ni2-3d  6.2",
            ),
        ),
    ],
    ids=["silicon", "nickel_oxide"],
)
def test_bands_in_repeats_scf_in_but_for_the_path_and_the_bands_step_s_values(
    material, args, shared_lines, pseudo_metadata_factory
) -> None:
    """A bands run reads the positions and the cell from the scf's save, but
    its species and every keyword that defines the Hamiltonian from its own
    input, so bands.in, given the scf step's occupations and convergence,
    repeats scf.in apart from calculation, nbnd, max_seconds and the K_POINTS
    card. It computes no forces or stress, so it asks for neither (#289)."""
    system, scf_step, bands_step = material(pseudo_metadata_factory)

    (scf,) = write_qe_scf(system, scf_step, _CTX)
    (bands,) = write_qe_bands(system, bands_step, _CTX)

    scf_in, bands_in = scf.files["scf.in"], bands.files["bands.in"]
    assert _shared(bands_in) == _shared(scf_in)
    assert {
        "&CONTROL",
        "&SYSTEM",
        "&ELECTRONS",
        "ATOMIC_SPECIES",
        "CELL_PARAMETERS angstrom",
        "ATOMIC_POSITIONS crystal",
        *shared_lines,
    } <= set(_shared(bands_in))
    assert [
        line
        for line in bands_in.splitlines()
        if line.split("=")[0].strip() in _PER_STEP_KEYWORDS
    ] == [
        "   calculation      = 'bands'",
        "   max_seconds      = 5000",
        "   nbnd             = 12",
    ]
    assert k_points_crystal_b(bands_step.k_path) in bands_in
    assert bands_in.count("K_POINTS") == 1
    assert dataclasses.replace(bands, files={}) == Step(
        name="bands",
        executable="pw.x",
        args=args,
        stdout="bands.out",
        completion=ExitStatusCheck("./scratch/band.save/data-file-schema.xml"),
    )


@pytest.mark.parametrize(
    "setting",
    ["occupations", "k_path", "nbnd", "convergence", "parallel", "max_seconds"],
)
def test_a_bands_step_without_a_setting_it_renders_is_refused(
    setting, pseudo_metadata_factory
) -> None:
    system, _, bands_step = _silicon(pseudo_metadata_factory)

    with pytest.raises(GenerationError, match=f"PwSettings.{setting} is required"):
        write_qe_bands(system, dataclasses.replace(bands_step, **{setting: None}), _CTX)


@pytest.mark.parametrize("spin_mode", ["none", "noncollinear"])
def test_bands_x_reads_a_single_spin_channel_once_on_one_task(spin_mode) -> None:
    """A noncollinear run has one channel: bands.x accepts only spin_component
    1 for it (QE 7.3 ``PP/src/bands.f90:119-120``). lsym is off: its group
    theory can stop bands.x after filband is written, and runs for every
    point on one task. bands.x writes no status file, so ``JOB DONE`` in its
    stdout passes the step."""
    assert write_qe_bands_x(spin_mode, _CTX) == [
        Step(
            name="bands_x",
            executable="bands.x",
            args=("-in", "bands_x.in"),
            files={
                "bands_x.in": "&BANDS\n"
                "   prefix           = 'band'\n"
                "   outdir           = './scratch'\n"
                "   filband          = 'bands.dat'\n"
                "   lsym             = .false.\n"
                "/\n"
            },
            stdout="bands_x.out",
            completion=StdoutMarkerCheck("JOB DONE"),
            ntasks=1,
        )
    ]


def test_a_collinear_run_reads_each_spin_channel_in_its_own_bands_x_run() -> None:
    """One run per channel (spin_component), each with its own filband: both
    rewrite prefix.wfc*, so they run one after the other. Neither writes the
    default filband, bands.out, which would overwrite the pw.x bands step's
    stdout (``PP/src/bands.f90:54``, 193-195)."""
    steps = write_qe_bands_x("collinear", _CTX)

    assert steps == [
        Step(
            name=f"bands_x_{channel}",
            executable="bands.x",
            args=("-in", f"bands_x_{channel}.in"),
            files={
                f"bands_x_{channel}.in": "&BANDS\n"
                "   prefix           = 'band'\n"
                "   outdir           = './scratch'\n"
                f"   filband          = 'bands_{channel}.dat'\n"
                f"   spin_component   = {component}\n"
                "   lsym             = .false.\n"
                "/\n"
            },
            stdout=f"bands_x_{channel}.out",
            completion=StdoutMarkerCheck("JOB DONE"),
            ntasks=1,
        )
        for channel, component in (("up", 1), ("down", 2))
    ]
    assert not any(
        "bands.out" in text
        for step in steps
        for text in (*step.files.values(), step.stdout)
    )
