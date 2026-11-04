"""The phonon tasks (#215), step by step on a synthetic SSSP-shaped table.

The first step's k-mesh: under the phonon tasks' k rule, ``advise_steps``
raises the mesh the tiers decide against the ph step's q-mesh, on the
simulated cell, and the k-points pw.x runs and the job's pools follow the
raised mesh. No model is installed, so the heuristic tier decides.

The job: under a job timer no step gets a max_seconds share, and the first
step's input carries none, while the dos and band tasks still split the
walltime between their pw.x steps.

The phonon steps: ``phonon_steps_advice`` advises the ph, q2r, phonon_dos
and dispersion steps, a relaxation first step's relax record and the first
step's FFT grid on the advice of a first step under ``phonon_step_protocol``.
The overrides are routed for the scf, relax or vc-relax task, so the phonon
steps keep their defaults. The first step's input carries the grid ph.x
accepts and two-body D3, and the ph.x, q2r.x and matdyn.x inputs follow it
on its context.

The tasks: phonon, relax-phonon and vc-relax-phonon through their rows of
``service.TASK_PHASES``, from the request to the bundle, against the scf,
relax and vc-relax tasks for the same request, and the dispersion against
the band task's path. A phonon task refuses a first step on smearing whose
composition is not all-metallic unless the user confirms a metal, so the
requests here put such structures on fixed occupations, except in the tests
of that refusal: on the synthetic table and, where they are installed, on
the installed tables and models, whose classifier decides is_metal.
"""

from __future__ import annotations

import re
from typing import Literal

import pytest
from pymatgen.core import Lattice, Structure
from support import (
    alpha_uranium,
    antiferromagnetic_nickel_oxide,
    carbon_chain,
    carbon_pair_in_a_box,
    fcc_lead,
    in_memory_source,
    mc3d_42058_silicon,
    molybdenum_disulfide_monolayer,
    rock_salt,
    sodium_chloride,
    sssp_fixture_table_spec,
    strict_json,
    wurtzite_zinc_oxide,
)

from goldilocks_core.advisors.job_resources import JobTimerProtocol
from goldilocks_core.advisors.k_path import KPathDecision
from goldilocks_core.advisors.k_sampling import PhononKProtocol
from goldilocks_core.advisors.phonon import (
    AIIDA_PROTOCOLS_CITATION,
    NO_DISPERSION,
    PHONON_CITATIONS,
)
from goldilocks_core.advisors.q_sampling import QSamplingHumanInput, q_sampling
from goldilocks_core.assets.pseudopotentials.importers import sssp_preparer
from goldilocks_core.assets.store import AssetStore
from goldilocks_core.bundle import bundle_files
from goldilocks_core.checks import CheckReport
from goldilocks_core.generation.quantum_espresso.bands import path_rows
from goldilocks_core.generation.quantum_espresso.phonon import write_qe_phonon
from goldilocks_core.inputs.hpc import load_hpc_profile
from goldilocks_core.resolution import Unavailable, Warning
from goldilocks_core.service import (
    TASK_PHASES,
    Advice,
    RunOverrides,
    advise_band,
    advise_dos,
    check,
    generate,
)
from goldilocks_core.service._phonon_steps import (
    PhononStepsAdvice,
    phonon_step_settings,
    phonon_steps_advice,
)
from goldilocks_core.service._pipeline import advise_steps
from goldilocks_core.service._step_protocol import (
    PHONON_JOB_TIMER,
    RELAX_PHONON_PROTOCOL,
    StepProtocol,
    phonon_step_protocol,
)
from goldilocks_core.set_overrides import build_overrides
from goldilocks_core.steps import SharedContext, Step, default_shared_context

_Z_VALENCES = {
    "C": 4.0,
    "Cl": 7.0,
    "Fe": 16.0,
    "Mo": 14.0,
    "N": 5.0,
    "Na": 9.0,
    "Ni": 18.0,
    "O": 6.0,
    "Pb": 14.0,
    "S": 6.0,
    "Si": 4.0,
    "Ti": 12.0,
    "U": 14.0,
    "Zn": 20.0,
}
_FULLY_RELATIVISTIC_Z_VALENCES = {"Ni": 18.0, "O": 6.0}

_FIRST_STEP_TASKS = {
    "scf": "scf_single_point",
    "relax": "relax",
    "vc-relax": "vc-relax",
}
"""The task whose routing gives each first step its overrides: the request
keys of the system and the first step route, and the phonon steps keep their
defaults."""


@pytest.fixture
def store(tmp_path, monkeypatch) -> AssetStore:
    """The scalar table, covering every element here, and a fully
    relativistic one for NiO with spin-orbit coupling."""
    tables = (
        sssp_fixture_table_spec(tmp_path / "scalar", _Z_VALENCES),
        sssp_fixture_table_spec(
            tmp_path / "full", _FULLY_RELATIVISTIC_Z_VALENCES, relativistic="full"
        ),
    )
    monkeypatch.setattr(
        "goldilocks_core.service._pseudo.load_tables",
        lambda *a, **kw: {table.id: table for _, table in tables},
    )
    installed = AssetStore(tmp_path / "store")
    for spec, table in tables:
        installed.install(spec, sssp_preparer(table))
    return installed


def _scf(
    structure: Structure,
    store: AssetStore,
    protocol: StepProtocol,
    overrides: RunOverrides | None = None,
) -> Advice:
    """The advice for one first step of ``structure``, under ``protocol``."""
    overrides = overrides or RunOverrides()
    return advise_steps(
        structure,
        code="quantum_espresso",
        hpc=load_hpc_profile("scarf"),
        overrides=overrides,
        steps=overrides.for_steps(("scf",)),
        store=store,
        fetch_missing=False,
        protocols={"scf": protocol},
    )["scf"]


def test_the_raised_k_mesh_is_the_one_pw_x_runs_and_the_job_splits(store) -> None:
    """fcc Pb is a metal: the heuristic 0.15 1/A gives 9x9x9, which the
    smearing run raises to 10x10x10, the next multiple of the 5x5x5 q-mesh.
    pw.x runs 56 irreducible k-points instead of 35, and the job's 64 tasks
    split into 32 pools instead of 8."""
    plain = _scf(fcc_lead(), store, StepProtocol()).step
    raised = _scf(fcc_lead(), store, StepProtocol(phonon_k=PhononKProtocol())).step

    k_sampling = raised.kpoints.k_sampling
    assert plain.kpoints.k_sampling.value.mesh == (9, 9, 9)
    assert k_sampling.value.mesh == (10, 10, 10)
    assert raised.kpoints.occupations.value.occupations == "smearing"
    assert k_sampling.provenance.source_note.startswith(
        "Raised for DFPT from 9x9x9 to 10x10x10: each k-axis to the next "
        "multiple of its q-axis (q-mesh 5x5x5)"
    )
    assert [warning.code for warning in k_sampling.value.warnings] == [
        "phonon.k_mesh_raised"
    ]
    pairs = [
        (step.kpoints.n_irr_k.value, step.resources.parallelisation.value)
        for step in (plain, raised)
    ]
    assert [(n_irr_k, layout.kpoint_spin_pairs) for n_irr_k, layout in pairs] == [
        (35, 35),
        (56, 56),
    ]
    assert [layout.npool for _, layout in pairs] == [8, 32]


def test_a_request_q_mesh_sets_the_mesh_the_k_mesh_meets(store) -> None:
    """Rock-salt NaCl as a confirmed non-metal runs on fixed occupations at
    the heuristic 0.30 1/A, 4x4x4. A request q_distance of 0.2 1/A gives the
    q record 6x6x6 on the same cell, and the k-mesh is raised to it."""
    overrides = build_overrides({"is_metal": "non_metal"}, task="scf_single_point")
    q = QSamplingHumanInput(q_distance=0.2)

    plain = _scf(sodium_chloride(), store, StepProtocol(), overrides)
    advice = _scf(
        sodium_chloride(), store, StepProtocol(phonon_k=PhononKProtocol(q)), overrides
    )

    kpoints = advice.step.kpoints
    assert kpoints.occupations.value.occupations == "fixed"
    assert plain.step.kpoints.k_sampling.value.mesh == (4, 4, 4)
    assert q_sampling(advice.system.cell, q).value.mesh == (6, 6, 6)
    assert kpoints.k_sampling.value.mesh == (6, 6, 6)
    assert kpoints.k_sampling.value.k_distance is None
    assert (plain.step.kpoints.n_irr_k.value, kpoints.n_irr_k.value) == (10, 20)


def test_a_job_timer_leaves_the_first_step_without_a_max_seconds_share(
    store,
) -> None:
    """Diamond Si under a job timer: the job holds no share and fires its
    timer at 95% of SCARF's 168 h, its record carries the protocol's note,
    and scf.in leaves max_seconds to pw.x's default."""
    timer = JobTimerProtocol(note="Test protocol: one timer for the whole job.")

    advice = _scf(mc3d_42058_silicon(), store, StepProtocol(job_timer=timer))

    resources = advice.step.resources
    assert resources.max_seconds is None
    assert resources.job.value.max_seconds_by_step == {}
    assert resources.job.value.timer_seconds == 574560
    assert resources.job.provenance.source_note == timer.note
    (scf,) = generate(advice, check(advice))
    assert "max_seconds" not in scf.files["scf.in"]


def test_the_dos_and_band_tasks_still_split_the_walltime(store) -> None:
    """Neither task's protocols declare a job timer, so each of its pw.x
    steps keeps its own max_seconds share of the one job."""
    hpc = load_hpc_profile("scarf")
    dos = advise_dos(mc3d_42058_silicon(), hpc=hpc, store=store)
    band = advise_band(mc3d_42058_silicon(), hpc=hpc, store=store)

    for steps in (
        {"scf": dos.scf, "nscf": dos.nscf},
        {"scf": band.scf, "bands": band.bands},
    ):
        job = steps["scf"].step.resources.job
        assert job.value.timer_seconds is None
        assert job.provenance.source_note is None
        shares = {
            purpose: advice.step.resources.max_seconds
            for purpose, advice in steps.items()
        }
        assert job.value.max_seconds_by_step == shares
        assert min(shares.values()) > 0


def _phonon(
    structure: Structure,
    store: AssetStore,
    first_step: Literal["scf", "relax", "vc-relax"],
    assignments: dict[str, object] | None = None,
) -> tuple[Advice, PhononStepsAdvice]:
    """The first step's advice under the phonon tasks' protocol for it, and
    the phonon steps advised on it, for a request of ``assignments``."""
    hpc = load_hpc_profile("scarf")
    overrides = build_overrides(assignments or {}, task=_FIRST_STEP_TASKS[first_step])
    steps = overrides.for_steps((first_step, "ph", "q2r", "phonon_dos", "dispersion"))
    protocol = phonon_step_protocol(first_step, steps["ph"].ph.q_sampling)
    first = advise_steps(
        structure,
        code="quantum_espresso",
        hpc=hpc,
        overrides=overrides,
        steps={first_step: steps[first_step]},
        store=store,
        fetch_missing=False,
        protocols={first_step: protocol},
    )[first_step]
    return first, phonon_steps_advice(first_step, first, steps, protocol.relax)


def _codes(warnings: tuple[Warning, ...]) -> list[str]:
    return [warning.code for warning in warnings]


def _keywords(text: str) -> dict[str, str]:
    """The ``key = value`` lines of a rendered input, values as written."""
    pairs = (line.split("=", 1) for line in text.splitlines() if "=" in line)
    return {key.strip(): value.strip() for key, value in pairs}


def test_the_phonon_steps_of_silicon(store) -> None:
    """Diamond Si: ph.x runs the 7x7x7 q-mesh of 0.3 1/A, 20 irreducible
    q-points and a work of 2401 scf-equivalents, with the balanced ph
    protocol; q2r.x and matdyn.x apply asr 'simple', and the DOS mesh is
    21x21x21. The phonon record carries the phonon task's relax-first notice.
    pw.x's own FFT grid passes ph.x's test, so the first step writes none,
    and the job runs the phonon tasks' timer in place of any max_seconds
    share. The dispersion step holds the path matdyn.x follows."""
    first, steps = _phonon(mc3d_42058_silicon(), store, "scf")

    q = steps.q_sampling.value
    assert (q.mesh, q.q_distance, q.n_irr_q, q.work, q.refusal) == (
        (7, 7, 7),
        0.3,
        20,
        2401,
        None,
    )
    phonon = steps.phonon
    assert (phonon.value.tr2_ph, phonon.value.alpha_mix, phonon.value.nmix_ph) == (
        1e-18,
        0.4,
        8,
    )
    assert phonon.source == "heuristic"
    assert first.step.kpoints.occupations.value.occupations == "smearing"
    assert _codes(phonon.value.warnings) == ["phonon.relax_first"]
    assert (steps.q2r.value.asr, steps.q2r.value.loto_2d) == ("simple", False)
    assert steps.phonon_dos.value.mesh == (21, 21, 21)
    fft_grid = steps.fft_grid.value
    assert (fft_grid.compatible, fft_grid.written, fft_grid.fragile) == (
        True,
        None,
        False,
    )
    assert steps.relax is None
    resources = first.step.resources
    assert resources.max_seconds is None
    assert resources.job.value.max_seconds_by_step == {}
    assert resources.job.value.timer_seconds == 574560
    assert resources.job.provenance.source_note == PHONON_JOB_TIMER.note
    assert steps.first_step_records() == {"fft_grid": steps.fft_grid}
    assert steps.step_records() == {
        "ph": {"q_sampling": steps.q_sampling, "phonon": steps.phonon},
        "q2r": {"q2r": steps.q2r},
        "phonon_dos": {"phonon_dos": steps.phonon_dos},
        "dispersion": {"k_path": steps.dispersion},
    }


@pytest.mark.parametrize("first_step", ["scf", "relax"])
def test_the_first_step_writes_the_fft_grid_ph_x_accepts(store, first_step) -> None:
    """alpha-U given a Hubbard U on atomic projectors, the ones ph.x
    accepts: at the table's 120 Ry, pw.x's own dense grid, 20x24x32, is one
    ph.x refuses, so the scf of the phonon task and the fixed-cell
    relaxation of relax-phonon both write 24x24x32 as nr1-nr3, beside the
    HUBBARD card."""
    first, steps = _phonon(
        alpha_uranium(),
        store,
        first_step,
        {"hubbard_needs_correlation": True, "hubbard_projectors": "atomic"},
    )

    fft_grid = steps.fft_grid.value
    assert (fft_grid.pw_grid, fft_grid.compatible, fft_grid.written) == (
        (20, 24, 32),
        False,
        (24, 24, 32),
    )
    assert "phonon.hubbard_experimental" in _codes(steps.phonon.value.warnings)
    relax = None if steps.relax is None else steps.relax.value
    (step,) = generate(
        first,
        check(first, purpose=first_step, relax=steps.relax),
        purpose=first_step,
        relax=relax,
        fft_grid=fft_grid.written,
    )
    content = step.files[f"{first_step}.in"]
    keywords = _keywords(content)
    assert (keywords["nr1"], keywords["nr2"], keywords["nr3"]) == ("24", "24", "32")
    assert "HUBBARD (atomic)" in content


@pytest.mark.parametrize("first_step", ["relax", "vc-relax"])
def test_a_relaxation_first_step_relaxes_to_the_phonon_threshold(
    store, first_step
) -> None:
    """The relaxation that replaces the phonon scf runs to forc_conv_thr
    1e-4 Ry/Bohr, the phonon protocol's value, recorded as heuristic with the
    protocol's note and citation."""
    _, steps = _phonon(alpha_uranium(), store, first_step)

    relax = steps.relax
    assert relax.value.forc_conv_thr == 1e-4
    assert relax.provenance.field_sources["forc_conv_thr"] == "heuristic"
    assert relax.provenance.source_note == RELAX_PHONON_PROTOCOL.note
    assert relax.provenance.citations == (AIIDA_PROTOCOLS_CITATION,)
    assert relax.value.warnings == ()
    assert steps.first_step_records() == {
        "relax": steps.relax,
        "fft_grid": steps.fft_grid,
    }


def test_a_vc_relax_first_step_writes_no_fft_grid(store) -> None:
    """A vc-relax's final scf rebuilds pw.x's own grid for the relaxed cell,
    so on alpha-U, whose own grid ph.x refuses and whose b and a axes make it
    fragile, vc-relax.in carries no nr1-nr3."""
    first, steps = _phonon(alpha_uranium(), store, "vc-relax")

    fft_grid = steps.fft_grid.value
    assert (fft_grid.compatible, fft_grid.written, fft_grid.fragile_axes) == (
        False,
        None,
        (("b", "a"),),
    )
    (vc_relax,) = generate(
        first,
        check(first, purpose="vc-relax", relax=steps.relax),
        purpose="vc-relax",
        relax=steps.relax.value,
        fft_grid=fft_grid.written,
    )
    assert "nr1" not in vc_relax.files["vc-relax.in"]


def test_dft_d3_turns_the_first_step_s_three_body_terms_off(store) -> None:
    """With use_vdw=true the phonon record carries the two-body notice, since
    d3hess.x builds the D3 Hessian from two-body terms only, and the first
    step writes dftd3_threebody = .false. beside its DFT-D3 keywords."""
    first, steps = _phonon(mc3d_42058_silicon(), store, "scf", {"use_vdw": True})

    assert first.system.vdw.value.use_vdw
    assert _codes(steps.phonon.value.warnings) == [
        "phonon.relax_first",
        "phonon.d3_two_body",
    ]
    (scf,) = generate(first, check(first), dftd3_threebody=False)
    keywords = _keywords(scf.files["scf.in"])
    assert (keywords["vdw_corr"], keywords["dftd3_threebody"]) == (
        "'grimme-d3'",
        ".false.",
    )


def test_the_phonon_inputs_follow_the_first_step_on_its_context(store) -> None:
    """ph.x, q2r.x and matdyn.x run after the scf on one context: ph.x reads
    its save under the same prefix and outdir with its pools, and q2r.x and
    both matdyn.x runs read the files named for that prefix, the dispersion
    along the path its record holds."""
    first, steps = _phonon(mc3d_42058_silicon(), store, "scf")
    ctx = SharedContext(prefix="si", outdir="./si-out", pseudo_dir="./pseudo")

    (scf,) = generate(first, check(first), ctx=ctx)
    ph, q2r, dos, dispersion = write_qe_phonon(
        *phonon_step_settings(steps, first), ctx, d3hess=False
    )

    assert [step.name for step in (scf, ph, q2r, dos, dispersion)] == [
        "scf",
        "ph",
        "q2r",
        "phonon_dos",
        "dispersion",
    ]
    scf_keywords = _keywords(scf.files["scf.in"])
    ph_keywords = _keywords(ph.files["ph.in"])
    assert (scf_keywords["prefix"], scf_keywords["outdir"]) == ("'si'", "'./si-out'")
    assert (ph_keywords["prefix"], ph_keywords["outdir"]) == ("'si'", "'./si-out'")
    assert (ph_keywords["nq1"], ph_keywords["nq2"], ph_keywords["nq3"]) == (
        "7",
        "7",
        "7",
    )
    assert (ph_keywords["tr2_ph"], ph_keywords["fildyn"]) == ("1e-18", "'si.dyn'")
    npool = first.step.resources.parallelisation.value.npool
    assert ph.args[:2] == ("-npool", str(npool))
    assert _keywords(q2r.files["q2r.in"]) == {
        "fildyn": "'si.dyn'",
        "flfrc": "'si.fc'",
        "zasr": "'simple'",
    }
    dos_keywords = _keywords(dos.files["phonon_dos.in"])
    assert (dos_keywords["flfrc"], dos_keywords["asr"], dos_keywords["fldos"]) == (
        "'si.fc'",
        "'simple'",
        "'si.phdos'",
    )
    assert (dos_keywords["nk1"], dos_keywords["nk2"], dos_keywords["nk3"]) == (
        "21",
        "21",
        "21",
    )
    namelist, rows = dispersion.files["dispersion.in"].split("/\n")
    assert (_keywords(namelist)["flfrc"], _keywords(namelist)["flfrq"]) == (
        "'si.fc'",
        "'si.freq'",
    )
    assert rows.splitlines() == path_rows(steps.dispersion.value)


_PHONON_TASKS = (
    ("phonon", "scf"),
    ("relax-phonon", "relax"),
    ("vc-relax-phonon", "vc-relax"),
)
"""Each phonon task and its first pw.x step."""

_PLAIN_TASKS = {"scf": "scf_single_point", "relax": "relax", "vc-relax": "vc-relax"}
"""The task that runs each first step on its own."""

_NON_METAL = {"is_metal": "non_metal"}
"""The answer to is_metal for an insulator here: no model is installed, and
the heuristic cannot decide a structure with a non-metal element, so without
it the first step of such a structure runs on smearing, which the phonon
tasks refuse."""


def _task(
    task: str,
    structure: Structure,
    store: AssetStore,
    assignments: dict[str, object] | None = None,
):
    """``task``'s advice for ``structure`` and a request of ``assignments``,
    through its row of ``TASK_PHASES``, and the gate's report on it."""
    phases = TASK_PHASES[task]
    advice = phases.advise(
        structure,
        hpc=load_hpc_profile("scarf"),
        overrides=build_overrides(assignments or {}, task=task),
        store=store,
    )
    return advice, phases.check(advice)


def _steps(
    task: str,
    structure: Structure,
    store: AssetStore,
    assignments: dict[str, object] | None = None,
) -> tuple[Step, ...]:
    """The steps ``task`` renders for ``structure``, after asserting that the
    gate passes."""
    advice, report = _task(task, structure, store, assignments)
    assert report.ok, [finding.message for finding in report.blocking]
    return TASK_PHASES[task].generate(advice, report)


def _codes_of(report: CheckReport) -> list[str]:
    return [finding.code for finding in report.blocking]


@pytest.mark.parametrize(("task", "first_step"), _PHONON_TASKS)
def test_each_phonon_task_publishes_its_first_step_and_the_phonon_inputs(
    store, task, first_step
) -> None:
    """Diamond Si, set to a non-metal: the bundle holds the first step's
    input, the scf one only for the phonon task, then ph.in, q2r.in,
    phonon_dos.in and dispersion.in, and no d3hess.in without DFT-D3.
    goldilocks.json names the task, and CITATIONS.md the aiida-quantumespresso
    protocols and Baroni et al. for the ph step's defaults and Setyawan and
    Curtarolo for the path."""
    hpc = load_hpc_profile("scarf")
    phases = TASK_PHASES[task]
    structure = mc3d_42058_silicon()
    advice, report = _task(task, structure, store, _NON_METAL)
    ctx = default_shared_context()
    steps = phases.generate(advice, report, ctx=ctx)
    script = phases.render_submission(advice, hpc, "quantum_espresso", steps)
    bundle_input = phases.to_bundle_input(
        advice,
        steps,
        script,
        ctx,
        code="quantum_espresso",
        hpc=hpc,
        assignments=_NON_METAL,
        source=in_memory_source(structure),
    )
    files = {file["path"]: file["content"] for file in bundle_files(bundle_input)}

    assert sorted(path for path in files if path.endswith(".in")) == sorted(
        [f"{first_step}.in", "ph.in", "q2r.in", "phonon_dos.in", "dispersion.in"]
    )
    assert "submit.sh" in files
    assert strict_json(files["goldilocks.json"])["request"]["task"] == task
    citations = files["CITATIONS.md"].decode("utf-8")
    for citation in (
        *PHONON_CITATIONS,
        "Setyawan and Curtarolo, Comput. Mater. Sci. 49, 299 (2010)",
    ):
        assert f"- {citation}\n" in citations, citation


@pytest.mark.parametrize(("task", "first_step"), _PHONON_TASKS)
@pytest.mark.parametrize(
    ("structure", "assignments", "q_mesh", "k_mesh"),
    [
        (
            mc3d_42058_silicon,
            {"is_metal": "metal", "q_distance": 0.2},
            (11, 11, 11),
            (22, 22, 22),
        ),
        (
            sodium_chloride,
            {"is_metal": "non_metal", "q_distance": 0.2},
            (6, 6, 6),
            (6, 6, 6),
        ),
    ],
    ids=["silicon-smearing", "sodium-chloride-fixed"],
)
def test_each_phonon_task_raises_its_first_step_against_the_request_q_mesh(
    store, task, first_step, structure, assignments, q_mesh, k_mesh
) -> None:
    """A request q_distance of 0.2 1/A sets the ph step's q-mesh and the mesh
    each phonon task's first step meets. Diamond Si taken as a metal runs on
    smearing, so its heuristic 14x14x14, which the default 7x7x7 q-mesh leaves
    alone, goes to 22x22x22, the next multiple of the 11x11x11 q-mesh;
    rock-salt NaCl as a confirmed non-metal runs on fixed occupations, so its
    4x4x4 goes to the 6x6x6 q-mesh. pw.x runs the raised mesh."""
    advice, report = _task(task, structure(), store, assignments)

    assert report.ok, [finding.message for finding in report.blocking]
    records = advice.records()
    k_sampling = records["k_sampling"]
    assert records["q_sampling"].value.mesh == q_mesh
    assert k_sampling.value.mesh == k_mesh
    assert "phonon.k_mesh_raised" in _codes(k_sampling.value.warnings)
    first, *_ = TASK_PHASES[task].generate(advice, report)
    counts = "  ".join(str(count) for count in (*k_mesh, 0, 0, 0))
    assert f"K_POINTS automatic\n  {counts}\n" in first.files[f"{first_step}.in"]


@pytest.mark.parametrize("task", [task for task, _ in _PHONON_TASKS])
def test_a_request_for_the_phonon_steps_reaches_their_records_and_inputs(
    store, task
) -> None:
    """Diamond Si, set to a non-metal, with a request for each phonon step:
    ph.x's tr2_ph, alpha_mix and nmix_ph, the acoustic sum rule of q2r.x and
    matdyn.x, the DOS spacing and the path spacing. The ph, q2r, phonon_dos
    and k_path records take each value from the request, and ph.in, q2r.in,
    phonon_dos.in and dispersion.in carry it: the 0.2 1/A spacing gives an
    11x11x11 DOS mesh in place of the default 21x21x21, and at 0.05 1/A
    Gamma-X takes 24 steps in place of 47."""
    assignments = {
        **_NON_METAL,
        "tr2_ph": 1e-16,
        "alpha_mix": 0.3,
        "nmix_ph": 12,
        "asr": "simple",
        "dos_q_distance": 0.2,
        "k_path_distance": 0.05,
    }

    advice, report = _task(task, mc3d_42058_silicon(), store, assignments)

    assert report.ok, [finding.message for finding in report.blocking]
    records = advice.records()
    phonon, q2r, dos, path = (
        records[name] for name in ("phonon", "q2r", "phonon_dos", "k_path")
    )
    assert (phonon.value.tr2_ph, phonon.value.alpha_mix, phonon.value.nmix_ph) == (
        1e-16,
        0.3,
        12,
    )
    assert (q2r.value.asr, dos.value.dos_q_distance, dos.value.mesh) == (
        "simple",
        0.2,
        (11, 11, 11),
    )
    assert (path.value.k_path_distance, path.value.branches[0].steps[0]) == (
        0.05,
        24,
    )
    assert [record.provenance.field_sources for record in (phonon, q2r, dos, path)] == [
        {"tr2_ph": "human", "alpha_mix": "human", "nmix_ph": "human"},
        {"asr": "human"},
        {"dos_q_distance": "human"},
        {"k_path_distance": "human"},
    ]
    _, ph, q2r_step, dos_step, dispersion_step = TASK_PHASES[task].generate(
        advice, report
    )
    ph_keywords = _keywords(ph.files["ph.in"])
    assert (
        ph_keywords["tr2_ph"],
        ph_keywords["alpha_mix(1)"],
        ph_keywords["nmix_ph"],
    ) == ("1e-16", "0.3", "12")
    assert _keywords(q2r_step.files["q2r.in"])["zasr"] == "'simple'"
    dos_keywords = _keywords(dos_step.files["phonon_dos.in"])
    assert (
        dos_keywords["asr"],
        dos_keywords["nk1"],
        dos_keywords["nk2"],
        dos_keywords["nk3"],
    ) == ("'simple'", "11", "11", "11")
    namelist, rows = dispersion_step.files["dispersion.in"].split("/\n")
    assert _keywords(namelist)["asr"] == "'simple'"
    assert rows.splitlines() == path_rows(path.value)


def _route(path: KPathDecision) -> str:
    """``path``'s vertex labels, branch by branch."""
    return " | ".join(
        "-".join(vertex.label for vertex in branch.vertices) for branch in path.branches
    )


@pytest.mark.parametrize("task", [task for task, _ in _PHONON_TASKS])
def test_the_dispersion_follows_the_band_task_s_path(store, task) -> None:
    """Diamond Si confirmed a metal runs its first step on smearing, on which
    ph.x computes no effective charges, and the dispersion's k_path is the
    band task's for the same request. As a non-metal, on fixed occupations,
    matdyn.x adds the non-analytic term, so the same path lists its interior
    Gamma twice, one point more, and dispersion.in carries those rows."""
    band, _ = _task("band", mc3d_42058_silicon(), store, {"is_metal": "metal"})
    metal, _ = _task(task, mc3d_42058_silicon(), store, {"is_metal": "metal"})
    insulator, report = _task(task, mc3d_42058_silicon(), store, _NON_METAL)

    band_path = band.records()["k_path"].value
    assert metal.records()["k_path"].value == band_path
    split = insulator.records()["k_path"]
    assert _route(band_path) == "Gamma-X-W-K-Gamma-L-U-W-L-K | U-X"
    assert _route(split.value) == "Gamma-X-W-K-Gamma | Gamma-L-U-W-L-K | U-X"
    assert split.value.n_kpoints == band_path.n_kpoints + 1 == 307
    assert split.provenance.derived_from == ("magnetic", "occupations", "q2r")
    assert "listed twice" in split.provenance.source_note
    *_, dispersion = TASK_PHASES[task].generate(insulator, report)
    rows = dispersion.files["dispersion.in"].split("/\n")[1].splitlines()
    assert rows == path_rows(split.value)
    gamma = rows.index("  0  0  0  0  ! Gamma")
    assert rows[gamma - 1 : gamma + 2] == [
        "  -0.75  -0.375  -0.375  50  ! K",
        "  0  0  0  0  ! Gamma",
        "  0  0  0  41  ! Gamma",
    ]


@pytest.mark.parametrize("task", [task for task, _ in _PHONON_TASKS])
def test_a_conventional_cell_s_phonon_branches_are_noticed_as_folded(
    store, task
) -> None:
    """Rock-salt NaCl in its 8-atom conventional cell, set to a non-metal:
    the dispersion follows the path of the primitive cell's zone with the
    band path's notices, so its k_path record says that the phonon branches
    of 4 primitive cells fold together, with Gamma listed twice on fixed
    occupations."""
    advice, report = _task(task, sodium_chloride(), store, _NON_METAL)

    assert report.ok, [finding.message for finding in report.blocking]
    (folded,) = (
        warning
        for warning in advice.warnings()
        if warning["code"] == "k_path.folded_bands"
    )
    assert folded["record"] == "k_path"
    for term in ("4 primitive cells", "phonon branches"):
        assert term in folded["message"], term
    assert "listed twice" in advice.records()["k_path"].provenance.source_note


@pytest.mark.parametrize(("task", "first_step"), _PHONON_TASKS)
def test_dft_d3_inserts_d3hess_and_two_body_d3_in_the_phonon_tasks_only(
    store, task, first_step
) -> None:
    """With use_vdw=true each phonon task runs d3hess.x between its first step
    and ph.x, and that step writes dftd3_threebody = .false., the two-body D3
    of d3hess.x's Hessian; the task that runs the first step on its own, for
    the same request, keeps QE's three-body terms."""
    assignments = {**_NON_METAL, "use_vdw": True}

    steps = _steps(task, mc3d_42058_silicon(), store, assignments)
    (plain,) = _steps(
        _PLAIN_TASKS[first_step], mc3d_42058_silicon(), store, assignments
    )

    assert [step.name for step in steps] == [
        first_step,
        "d3hess",
        "ph",
        "q2r",
        "phonon_dos",
        "dispersion",
    ]
    keywords = _keywords(steps[0].files[f"{first_step}.in"])
    assert (keywords["vdw_corr"], keywords["dftd3_threebody"]) == (
        "'grimme-d3'",
        ".false.",
    )
    assert _keywords(steps[1].files["d3hess.in"]) == {
        "prefix": "'pwscf'",
        "outdir": "'./out'",
    }
    plain_keywords = _keywords(plain.files[f"{first_step}.in"])
    assert plain_keywords["vdw_corr"] == "'grimme-d3'"
    assert "dftd3_threebody" not in plain_keywords


@pytest.mark.parametrize(("task", "first_step"), _PHONON_TASKS[1:])
def test_the_phonon_relaxations_converge_forces_ten_times_tighter(
    store, task, first_step
) -> None:
    """relax.in and vc-relax.in of the phonon tasks carry forc_conv_thr 1e-4
    Ry/Bohr, the phonon protocol's, where the relax and vc-relax tasks keep
    Quantum ESPRESSO's 1e-3; a request of 1e-3 is used as given, with the
    protocol's warning on the relax record."""
    (phonon_first, *_) = _steps(task, mc3d_42058_silicon(), store, _NON_METAL)
    (plain,) = _steps(_PLAIN_TASKS[first_step], mc3d_42058_silicon(), store, _NON_METAL)
    loose, _ = _task(
        task, mc3d_42058_silicon(), store, {**_NON_METAL, "forc_conv_thr": 1e-3}
    )

    name = f"{first_step}.in"
    assert float(_keywords(phonon_first.files[name])["forc_conv_thr"]) == 1e-4
    assert float(_keywords(plain.files[name])["forc_conv_thr"]) == 1e-3
    relax = loose.records()["relax"]
    assert (relax.value.forc_conv_thr, relax.source) == (1e-3, "human")
    assert ("relax", "phonon.loose_force_threshold") in {
        (warning["record"], warning["code"]) for warning in loose.warnings()
    }


@pytest.mark.parametrize(("task", "first_step"), _PHONON_TASKS)
def test_each_phonon_task_carries_its_own_notices(store, task, first_step) -> None:
    """The relax-first notice only where no relaxation runs, the input-cell
    notice only after a vc-relax, both on the ph step's phonon record; the
    first step's records keep its own name and the ph, q2r, phonon_dos and
    dispersion steps follow it."""
    advice, report = _task(task, mc3d_42058_silicon(), store, _NON_METAL)

    assert report.ok, [finding.message for finding in report.blocking]
    notices = {
        (warning["record"], warning["code"])
        for warning in advice.warnings()
        if warning["code"] in ("phonon.relax_first", "phonon.vc_relax_input_cell")
    }
    assert (
        notices
        == {
            "phonon": {("phonon", "phonon.relax_first")},
            "relax-phonon": set(),
            "vc-relax-phonon": {("phonon", "phonon.vc_relax_input_cell")},
        }[task]
    )
    layout = advice.tiers().layout()["steps"]
    assert [step["name"] for step in layout] == [
        first_step,
        "ph",
        "q2r",
        "phonon_dos",
        "dispersion",
    ]
    assert layout[1:] == [
        {"name": "ph", "records": ["q_sampling", "phonon"]},
        {"name": "q2r", "records": ["q2r"]},
        {"name": "phonon_dos", "records": ["phonon_dos"]},
        {"name": "dispersion", "records": ["k_path"]},
    ]
    assert ("relax" in layout[0]["records"]) is (first_step != "scf")
    assert layout[0]["records"][-1] == "fft_grid"


def test_alpha_uranium_needs_the_written_grid_vc_relax_phonon_cannot_keep(
    store,
) -> None:
    """alpha-U is fragile: a vc-relax rebuilds pw.x's own grid for the
    relaxed cell, which ph.x can refuse, so vc-relax-phonon is refused with no
    remedy, while the phonon task's scf.in and relax-phonon's relax.in carry
    the 24x24x32 grid ph.x accepts."""
    _, refused = _task("vc-relax-phonon", alpha_uranium(), store)
    scf, *_ = _steps("phonon", alpha_uranium(), store)
    relax, *_ = _steps("relax-phonon", alpha_uranium(), store)

    (finding,) = refused.blocking
    assert (finding.code, finding.remedies) == (
        "phonon.vc_relax_fft_grid_unsupported",
        (),
    )
    assert "relax-phonon" in finding.message
    for step in (scf, relax):
        keywords = _keywords(step.files[f"{step.name}.in"])
        grid = tuple(keywords.get(f"nr{axis}") for axis in (1, 2, 3))
        assert grid == ("24", "24", "32"), step.name


def test_a_molecule_in_a_box_gets_one_finding_in_vc_relax_phonon(store) -> None:
    """mc3d-6516's isolated carbon pair, set to a non-magnetic non-metal, on
    fixed occupations: Martyna-Tuckerman, which ph.x does not implement, is the
    one cause given; the vc-relax task's own refusal of an isolated system,
    whose advice is the relax task, is left out."""
    _, report = _task(
        "vc-relax-phonon",
        carbon_pair_in_a_box(),
        store,
        {**_NON_METAL, "is_magnetic": "non_magnetic"},
    )

    assert _codes_of(report) == ["phonon.isolated_boundary_unsupported"]


@pytest.mark.parametrize("task", [task for task, _ in _PHONON_TASKS])
def test_a_periodic_molecule_in_a_box_gets_one_finding_in_each_phonon_task(
    store, task
) -> None:
    """The same carbon pair with isolation=periodic: ph.x would compute a
    periodic array of copies of the pair, and a molecule has no phonon
    dispersion, so each phonon task refuses it with one finding and no
    remedy, and its dispersion record is unavailable, adding none."""
    assignments = {**_NON_METAL, "is_magnetic": "non_magnetic", "isolation": "periodic"}

    advice, report = _task(task, carbon_pair_in_a_box(), store, assignments)

    assert _codes_of(report) == ["phonon.isolated_boundary_unsupported"]
    assert report.blocking[0].remedies == ()
    assert "with isolation=periodic" in report.blocking[0].message
    assert advice.records()["k_path"] == Unavailable(reason=NO_DISPERSION)


@pytest.mark.parametrize(
    ("task", "assignments"),
    [
        ("phonon", _NON_METAL),
        ("relax-phonon", _NON_METAL),
        ("vc-relax-phonon", {**_NON_METAL, "cell_dofree": "epitaxial_ab"}),
    ],
    ids=["phonon", "relax-phonon", "vc-relax-phonon"],
)
def test_a_wire_s_dispersion_runs_gamma_to_z(store, task, assignments) -> None:
    """The carbon chain, set to a non-metal, has vacuum along a and b but not
    c: unlike a box, a wire is periodic along its axis, so each phonon task
    runs it, vc-relax-phonon with the cell_dofree that relaxes only the
    period, and its dispersion runs from Gamma to Z along the wire. Gamma
    starts the path, so it is not listed twice."""
    advice, report = _task(task, carbon_chain(), store, assignments)

    assert report.ok, [finding.message for finding in report.blocking]
    path = advice.records()["k_path"].value
    assert (path.lattice_type, _route(path)) == ("LINE", "Gamma-Z")
    *_, dispersion = TASK_PHASES[task].generate(advice, report)
    assert dispersion.files["dispersion.in"].split("/\n")[1].splitlines() == [
        "  2",
        "  0  0  0  99  ! Gamma",
        "  0  0  1  1  ! Z",
    ]


def test_magnetic_afm_nickel_oxide_with_spin_orbit_and_a_hubbard_u_is_refused(
    store,
) -> None:
    """AFM-II NiO, set to a non-metal, with spin-orbit coupling and the U on
    atomic projectors: ph.x's DFPT+U is collinear only, so the noncollinear
    magnetic run is refused, where the scf task generates it."""
    assignments = {
        **_NON_METAL,
        "spin_orbit_coupling": True,
        "hubbard_projectors": "atomic",
        "starting_magnetization": {"Ni1": 0.5, "Ni2": -0.5},
    }

    advice, report = _task(
        "phonon", antiferromagnetic_nickel_oxide(), store, assignments
    )
    _, scf_report = _task(
        "scf_single_point", antiferromagnetic_nickel_oxide(), store, assignments
    )

    magnetic = advice.first.system.magnetic.value
    assert (magnetic.spin_mode, magnetic.spin_orbit_enabled) == ("noncollinear", True)
    assert _codes_of(report) == ["phonon.noncollinear_hubbard_unsupported"]
    assert scf_report.ok, [finding.message for finding in scf_report.blocking]


def _rock_salt_nickel_oxide() -> Structure:
    """NiO in its 2-atom rock-salt primitive cell (a = 4.17 A)."""
    return Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(4.17), ["Ni", "O"], [[0, 0, 0], [0.5, 0.5, 0.5]]
    ).get_primitive_structure()


_MAGNETIC_NICKEL_OXIDE = {
    **_NON_METAL,
    "hubbard_projectors": "atomic",
    "tot_magnetization": 2,
}
"""Ferromagnetic NiO as a magnetic insulator: its 2 Bohr magnetons per cell,
of its 24 electrons' parity, put its first step on fixed occupations, and its
U is on the atomic projectors ph.x takes."""


@pytest.mark.parametrize("task", [task for task, _ in _PHONON_TASKS])
def test_no_phonon_input_writes_what_ph_x_refuses(store, task) -> None:
    """Ferromagnetic rock-salt NiO, set to a non-metal with its moment, with its
    U on atomic projectors: no input of a phonon task constrains the
    magnetization, sets tqr or occupations from_input, or runs K_POINTS gamma,
    which ph.x stops on."""
    steps = _steps(task, _rock_salt_nickel_oxide(), store, _MAGNETIC_NICKEL_OXIDE)

    contents = [content.lower() for step in steps for content in step.files.values()]
    assert any("hubbard (atomic)" in content for content in contents)
    for content in contents:
        for refused in ("constrained_magnetization", "tqr", "from_input"):
            assert refused not in content, refused
        assert re.search(r"k_points\s*[({]?\s*gamma", content) is None


def _bcc_iron() -> Structure:
    """bcc Fe in its conventional 2-atom cell (a = 2.867 A): every element a
    metal."""
    return Structure(Lattice.cubic(2.867), ["Fe", "Fe"], [[0, 0, 0], [0.5, 0.5, 0.5]])


_ANSWERED_OCCUPATIONS = {"non_metal": "fixed", "metal": "smearing"}
"""The occupations of the first step under each answer to is_metal."""


@pytest.mark.parametrize(("task", "first_step"), _PHONON_TASKS)
def test_an_insulator_on_smearing_needs_is_metal_in_each_phonon_task(
    store, task, first_step
) -> None:
    """Wurtzite ZnO without is_metal: the heuristic, all there is without a
    model, cannot decide it, and the classifier calls it a metal, so either way
    its first step runs on smearing, on which a relax-phonon run of it went
    through its relaxation and then diverged in ph.x at Gamma. Each phonon
    task is refused, naming is_metal with both answers, and each answer
    generates: non_metal on fixed occupations, metal on smearing. The task that
    runs the first step on its own is not refused."""
    advice, report = _task(task, wurtzite_zinc_oxide(), store)
    _, plain = _task(_PLAIN_TASKS[first_step], wurtzite_zinc_oxide(), store)

    (finding,) = report.blocking
    assert (finding.code, finding.fields, finding.remedies) == (
        "phonon.metallicity_unconfirmed",
        ("is_metal",),
        ({"is_metal": "non_metal"}, {"is_metal": "metal"}),
    )
    assert advice.first.analysis.is_metal.status == "unavailable"
    assert advice.first.step.kpoints.occupations.value.occupations == "smearing"
    assert plain.ok, [finding.message for finding in plain.blocking]
    for remedy in finding.remedies:
        answered, answered_report = _task(task, wurtzite_zinc_oxide(), store, remedy)
        assert answered_report.ok, [f.message for f in answered_report.blocking]
        first, *_ = TASK_PHASES[task].generate(answered, answered_report)
        occupations = _ANSWERED_OCCUPATIONS[remedy["is_metal"]]
        keywords = _keywords(first.files[f"{first_step}.in"])
        assert keywords["occupations"] == f"'{occupations}'", remedy


@pytest.mark.parametrize("task", [task for task, _ in _PHONON_TASKS])
@pytest.mark.parametrize(
    ("structure", "assignments", "occupations"),
    [
        (wurtzite_zinc_oxide, {"occupations": "fixed"}, "fixed"),
        (_bcc_iron, {}, "smearing"),
    ],
    ids=["fixed-occupations", "all-metallic"],
)
def test_fixed_occupations_or_an_all_metallic_composition_need_no_is_metal(
    store, task, structure, assignments, occupations
) -> None:
    """ZnO on the fixed occupations the request sets, with which ph.x computes
    its dielectric response, and bcc Fe, every element of which is a metal, on
    smearing: neither needs is_metal."""
    advice, report = _task(task, structure(), store, assignments)

    assert report.ok, [finding.message for finding in report.blocking]
    assert advice.first.step.kpoints.occupations.value.occupations == occupations


def _titanium_nitride() -> Structure:
    """TiN in its 2-atom rock-salt primitive cell (a = 4.24 A): 17 valence
    electrons with the table here, as with SSSP's."""
    return rock_salt("Ti", "N", 4.24)


_ON_SMEARING = {
    "nickel-oxide-set-non-metal": (
        _rock_salt_nickel_oxide,
        {**_NON_METAL, "hubbard_projectors": "atomic"},
        (
            "With is_metal=non_metal it stays on occupations=smearing: fixed "
            "occupations on a collinear spin-polarized run need an integer "
            "tot_magnetization of the electron count's parity"
        ),
        (
            {"is_metal": "non_metal", "is_magnetic": "non_magnetic"},
            {"is_metal": "metal"},
        ),
    ),
    "spin-polarized-monolayer": (
        molybdenum_disulfide_monolayer,
        {},
        (
            "Setting is_metal=non_metal alone would keep occupations=smearing: fixed "
            "occupations on a collinear spin-polarized run need an integer "
            "tot_magnetization of the electron count's parity"
        ),
        (
            {"is_metal": "non_metal", "is_magnetic": "non_magnetic"},
            {"is_metal": "metal"},
        ),
    ),
    "odd-electron-count": (
        _titanium_nitride,
        {},
        (
            "Setting is_metal=non_metal alone would keep occupations=smearing: "
            "without spin polarization fixed occupations cannot fill its odd "
            "electron count"
        ),
        ({"is_metal": "metal"},),
    ),
    "requested-smearing": (
        wurtzite_zinc_oxide,
        {**_NON_METAL, "occupations": "smearing"},
        "The request sets occupations=smearing, which is_metal does not change.",
        ({"occupations": "fixed"}, {"is_metal": "metal"}),
    ),
}
"""Requests whose first step is_metal=non_metal leaves on smearing: the
structure, the request, the reason the refusal gives and its remedies."""


@pytest.mark.parametrize("case", list(_ON_SMEARING))
def test_a_first_step_is_metal_non_metal_leaves_on_smearing_needs_a_metal(
    store, case
) -> None:
    """Ferromagnetic NiO set to a non-metal, its U on atomic projectors, and a
    MoS2 monolayer the heuristic spin-polarizes, collinear runs without a
    moment, which is_magnetic=non_magnetic runs without spin polarization,
    since NiO's U acts on an even d count; TiN, whose 17 electrons fixed
    occupations cannot fill without spin polarization; and ZnO on the smearing
    its request sets: is_metal=non_metal leaves each on smearing, on which
    ZnO's ph.x diverged at Gamma. Each relax-phonon request is refused with
    that reason, and each remedy generates, on fixed occupations unless it
    confirms a metal."""
    structure, assignments, reason, remedies = _ON_SMEARING[case]
    advice, report = _task("relax-phonon", structure(), store, assignments)

    (finding,) = report.blocking
    assert (finding.code, finding.remedies) == (
        "phonon.metallicity_unconfirmed",
        remedies,
    )
    assert reason in finding.message
    assert advice.first.step.kpoints.occupations.value.occupations == "smearing"
    for remedy in remedies:
        first, *_ = _steps("relax-phonon", structure(), store, assignments | remedy)
        metal = remedy.get("is_metal") == "metal"
        expected = "'smearing'" if metal else "'fixed'"
        assert _keywords(first.files["relax.in"])["occupations"] == expected, remedy


def test_the_moment_the_refusal_names_runs_a_magnetic_insulator_fixed(
    store,
) -> None:
    """Ferromagnetic NiO with its 2 Bohr magnetons per cell, the
    tot_magnetization the refusal names and no remedy guesses: with
    is_metal=non_metal its first step runs on fixed occupations, pinning it."""
    advice, report = _task(
        "relax-phonon", _rock_salt_nickel_oxide(), store, _MAGNETIC_NICKEL_OXIDE
    )

    occupations = advice.first.step.kpoints.occupations.value
    assert report.ok, [finding.message for finding in report.blocking]
    assert (occupations.occupations, occupations.tot_magnetization) == ("fixed", 2.0)


_REFUSED_FIXED = {
    "spin-polarized-monolayer": (
        molybdenum_disulfide_monolayer,
        "occupations.fixed_needs_tot_magnetization",
        (
            {"occupations": "fixed", "is_magnetic": "non_magnetic"},
            {"occupations": "smearing", "is_metal": "metal"},
        ),
    ),
    "odd-electron-count": (
        _titanium_nitride,
        "occupations.fixed_needs_even_electron_count",
        ({"occupations": "smearing", "is_metal": "metal"},),
    ),
}
"""Structures whose run cannot take a requested occupations=fixed: the
refusal the relax task gives it and the remedies of relax-phonon's."""


@pytest.mark.parametrize("case", list(_REFUSED_FIXED))
def test_a_requested_fixed_the_run_cannot_take_offers_no_bare_smearing(
    store, case
) -> None:
    """A MoS2 monolayer the heuristic spin-polarizes, without a moment, and
    TiN, whose 17 electrons fixed occupations cannot fill without spin
    polarization, set to a non-metal on occupations=fixed: the relax task
    refuses that, offering smearing, which a phonon task runs on such a
    composition only as a confirmed metal. relax-phonon refuses it as
    unconfirmed metallicity instead, and each remedy generates, on fixed
    occupations unless it confirms a metal."""
    structure, refused, remedies = _REFUSED_FIXED[case]
    assignments = {**_NON_METAL, "occupations": "fixed"}
    _, plain = _task("relax", structure(), store, assignments)
    _, report = _task("relax-phonon", structure(), store, assignments)

    (plain_finding,) = plain.blocking
    assert plain_finding.code == refused
    assert {"occupations": "smearing"} in plain_finding.remedies
    (finding,) = report.blocking
    assert (finding.code, finding.remedies) == (
        "phonon.metallicity_unconfirmed",
        remedies,
    )
    for remedy in remedies:
        first, *_ = _steps("relax-phonon", structure(), store, assignments | remedy)
        metal = remedy.get("is_metal") == "metal"
        expected = "'smearing'" if metal else "'fixed'"
        assert _keywords(first.files["relax.in"])["occupations"] == expected, remedy


def _rock_salt_magnesium_oxide() -> Structure:
    """MgO in its 2-atom rock-salt primitive cell (a = 4.212 A)."""
    return Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(4.212), ["Mg", "O"], [[0, 0, 0], [0.5, 0.5, 0.5]]
    ).get_primitive_structure()


def _installed(
    task: str, structure: Structure, assignments: dict[str, object] | None = None
):
    """``task``'s advice and the gate's report on it, on the installed tables
    and models."""
    phases = TASK_PHASES[task]
    advice = phases.advise(
        structure,
        hpc=load_hpc_profile("scarf"),
        overrides=build_overrides(assignments or {}, task=task),
    )
    return advice, phases.check(advice)


@pytest.mark.parametrize("task", [task for task, _ in _PHONON_TASKS])
def test_the_classifier_s_metal_call_needs_an_answer_and_its_non_metal_call_none(
    real_assets, task
) -> None:
    """On the installed tables and models: the classifier calls wurtzite ZnO a
    metal, which puts its first step on smearing, so each phonon task refuses
    it until is_metal is set, and is_metal=non_metal runs it on fixed
    occupations. It calls rock-salt MgO a non-metal, whose first step runs on
    fixed occupations without a refusal."""
    refused, refused_report = _installed(task, wurtzite_zinc_oxide())
    answered, answered_report = _installed(
        task, wurtzite_zinc_oxide(), {"is_metal": "non_metal"}
    )
    magnesia, magnesia_report = _installed(task, _rock_salt_magnesium_oxide())

    called_metal = refused.first.analysis.is_metal
    assert (called_metal.value, called_metal.source) == ("metal", "ml")
    assert refused.first.step.kpoints.occupations.value.occupations == "smearing"
    assert _codes_of(refused_report) == ["phonon.metallicity_unconfirmed"]
    assert answered_report.ok, [f.message for f in answered_report.blocking]
    assert answered.first.step.kpoints.occupations.value.occupations == "fixed"
    called_non_metal = magnesia.first.analysis.is_metal
    assert (called_non_metal.value, called_non_metal.source) == ("non_metal", "ml")
    assert magnesia.first.step.kpoints.occupations.value.occupations == "fixed"
    assert magnesia_report.ok, [f.message for f in magnesia_report.blocking]


@pytest.mark.parametrize(
    ("structure", "assignments", "remedies"),
    [
        (
            _rock_salt_nickel_oxide,
            {**_NON_METAL, "hubbard_projectors": "atomic"},
            (
                {"is_metal": "non_metal", "is_magnetic": "non_magnetic"},
                {"is_metal": "metal"},
            ),
        ),
        (
            lambda: rock_salt("Mn", "O", 4.445, primitive=False),
            {**_NON_METAL, "hubbard_projectors": "atomic"},
            ({"is_metal": "metal"},),
        ),
        (
            molybdenum_disulfide_monolayer,
            {"is_magnetic": "magnetic"},
            (
                {"is_metal": "non_metal", "is_magnetic": "non_magnetic"},
                {"is_metal": "metal"},
            ),
        ),
        (_titanium_nitride, {}, ({"is_metal": "metal"},)),
    ],
    ids=[
        "nickel-oxide-set-non-metal",
        "manganese-oxide-set-non-metal",
        "spin-polarized-monolayer",
        "odd-electron-count",
    ],
)
def test_on_the_installed_models_no_remedy_leaves_a_non_metal_on_smearing(
    real_assets, structure, assignments, remedies
) -> None:
    """On the installed tables and models: ferromagnetic NiO and MnO set to a
    non-metal, a MoS2 monolayer set to magnetic, which the classifier calls a
    non-metal, and TiN, whose 17 electrons the
    classifier calls a metal, all stay on smearing, so relax-phonon refuses
    each, and every remedy passes the gate on fixed occupations unless it
    confirms a metal. is_magnetic=non_magnetic is not offered for MnO, whose U
    on Mn2+ d5, an odd count, keeps the run spin-polarized."""
    refused, report = _installed("relax-phonon", structure(), assignments)

    (finding,) = report.blocking
    assert (finding.code, finding.remedies) == (
        "phonon.metallicity_unconfirmed",
        remedies,
    )
    assert refused.first.step.kpoints.occupations.value.occupations == "smearing"
    for remedy in remedies:
        answered, answered_report = _installed(
            "relax-phonon", structure(), assignments | remedy
        )
        occupations = answered.first.step.kpoints.occupations.value.occupations
        assert answered_report.ok, [f.message for f in answered_report.blocking]
        metal = remedy.get("is_metal") == "metal"
        assert occupations == ("smearing" if metal else "fixed"), remedy


def test_on_the_installed_models_a_molybdenum_disulfide_monolayer_runs_unpolarized(
    real_assets,
) -> None:
    """#244: the default assets carry the mMACE backbone, so is_magnetic comes
    from the classifier, which calls the MoS2 monolayer non-magnetic (the
    heuristic tier spin-polarized it). relax-phonon then runs it on fixed
    occupations instead of refusing it."""
    advice, report = _installed("relax-phonon", molybdenum_disulfide_monolayer())

    is_magnetic = advice.first.analysis.is_magnetic
    assert (is_magnetic.value, is_magnetic.source) == ("non_magnetic", "ml")
    assert advice.first.step.kpoints.occupations.value.occupations == "fixed"
    assert report.ok, [f.message for f in report.blocking]
