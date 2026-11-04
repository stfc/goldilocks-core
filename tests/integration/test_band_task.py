"""The band task (#118), end to end on a synthetic SSSP-shaped table.

Its pw.x steps first: ``advise_steps`` advises the scf and the pw.x bands
step of diamond Si (MC3D mc3d-42058) together, under the band task's
protocols: the bands step runs every point of the written cell's band path,
three times the occupied bands, the scf step's occupations, and its own share
of the one job both steps run in. Its input repeats scf.in apart from the
step's own values and the K_POINTS card.

Then the task through ``advise_band``/``check_band``/``generate_band``: scf,
bands and one bands.x run per spin channel in one script; a collinear
smearing magnet (hcp Gd) with no moment in either pw.x input, and the same
magnet with spin-orbit coupling, whose one bands.x run takes no spin
component; a compensated antiferromagnet (AFM-II NiO, with the real enumlib)
on smearing rather than the pinned zero moment bands.x would stop on;
tetrahedra written as smearing in bands.in; a requested moment refused with
a remedy that runs; in-plane paths on slabs, Gamma to Z on a wire, a box
refused once, and folded bands noticed on a conventional cell. The scalar
and the fully relativistic table cover every element here.
"""

from __future__ import annotations

import re

import pytest
from pymatgen.core import Lattice, Structure
from support import (
    carbon_chain,
    carbon_pair_in_a_box,
    fcc_lead,
    generated_slab,
    graphene_monolayer,
    hcp_gadolinium,
    in_memory_source,
    mc3d_42058_silicon,
    rutile_titanium_dioxide,
    sssp_fixture_table_spec,
    strict_json,
)

from goldilocks_core.advisors.convergence import ConvergenceHumanInput
from goldilocks_core.advisors.k_path import KPathHumanInput
from goldilocks_core.advisors.magnetic_enumeration import enumlib_installed
from goldilocks_core.advisors.nbnd import NbndHumanInput
from goldilocks_core.assets.pseudopotentials.importers import sssp_preparer
from goldilocks_core.assets.store import AssetStore
from goldilocks_core.bundle import DirectoryOutput, publish
from goldilocks_core.checks import CheckReport
from goldilocks_core.generation.quantum_espresso.bands import k_points_crystal_b
from goldilocks_core.inputs.hpc import load_hpc_profile
from goldilocks_core.resolution import Blocked
from goldilocks_core.service import (
    Advice,
    BandAdvice,
    KPathOverrides,
    KpointsOverrides,
    PathStepAdvice,
    RunOverrides,
    StepOverrides,
    SystemOverrides,
    advise,
    advise_band,
    check,
    check_band,
    generate,
    generate_band,
    render_submission_band,
    to_bundle_input_band,
)
from goldilocks_core.service._pipeline import advise_steps
from goldilocks_core.service._step_protocol import BAND_SCF_PROTOCOL, BANDS_PROTOCOL
from goldilocks_core.set_overrides import build_overrides
from goldilocks_core.steps import ExitStatusCheck, Step, default_shared_context

_Z_VALENCES = {
    "C": 4.0,
    "Gd": 18.0,
    "Ni": 18.0,
    "O": 6.0,
    "Pb": 14.0,
    "Si": 4.0,
    "Ti": 12.0,
}


@pytest.fixture
def store(tmp_path, monkeypatch) -> AssetStore:
    """The scalar table and the fully relativistic one spin-orbit coupling
    selects."""
    specs = (
        sssp_fixture_table_spec(tmp_path / "scalar", _Z_VALENCES),
        sssp_fixture_table_spec(tmp_path / "full", _Z_VALENCES, relativistic="full"),
    )
    monkeypatch.setattr(
        "goldilocks_core.service._pseudo.load_tables",
        lambda *a, **kw: {table.id: table for _, table in specs},
    )
    installed = AssetStore(tmp_path / "store")
    for spec, table in specs:
        installed.install(spec, sssp_preparer(table))
    return installed


def _advice(
    store: AssetStore,
    bands: StepOverrides | None = None,
    overrides: RunOverrides | None = None,
) -> dict[str, Advice]:
    """Diamond Si's scf and bands steps, ``bands`` the bands step's own
    overrides and ``overrides`` the task's."""
    return advise_steps(
        mc3d_42058_silicon(),
        code="quantum_espresso",
        hpc=load_hpc_profile("scarf"),
        overrides=overrides or RunOverrides(),
        steps={"scf": StepOverrides(), "bands": bands or StepOverrides()},
        store=store,
        fetch_missing=False,
        protocols={"scf": BAND_SCF_PROTOCOL, "bands": BANDS_PROTOCOL},
    )


def _cards(content: str) -> dict[str, str]:
    """Each card of a pw.x input by its header line, namelists left out."""
    blocks = (block.strip("\n") for block in content.split("\n\n"))
    return {
        block.splitlines()[0]: block
        for block in blocks
        if block and not block.startswith("&")
    }


def test_the_bands_step_runs_every_point_of_the_written_cell_s_path(store) -> None:
    """pw.x runs a bands list as given, unreduced by symmetry (QE 7.3
    ``PW/src/setup.f90:579-585``), so the step's k-points are the path's
    points. Its occupations are the scf step's, its convergence the scf's
    rule on the same cell, and its bands three times the 4 occupied ones
    (aiida-quantumespresso's bands.yaml), against the scf's 8."""
    advice = _advice(store)
    scf, bands = advice["scf"].step.kpoints, advice["bands"].step.kpoints

    assert isinstance(bands, PathStepAdvice)
    path = bands.k_path.value
    assert path.lattice_type == "FCC"
    assert path.cell is advice["bands"].system.cell.value.structure
    assert bands.n_irr_k.value == path.n_kpoints
    assert bands.occupations.value == scf.occupations.value
    assert bands.occupations.provenance.derived_from == ("occupations",)
    assert (scf.nbnd.value.nbnd, bands.nbnd.value.nbnd) == (8, 12)
    assert bands.convergence.value == scf.convergence.value
    assert set(advice["bands"].step.records()) == {
        "occupations",
        "k_path",
        "nbnd",
        "convergence",
        "job",
        "parallelisation",
    }


def test_the_bands_step_reads_its_own_overrides(store) -> None:
    """A bands step's k_path_distance spaces its path, and its nbnd and
    conv_thr are its own: the scf step keeps its defaults."""
    default = _advice(store)["bands"].step.kpoints.k_path.value
    advice = _advice(
        store,
        StepOverrides(
            kpoints=KpointsOverrides(
                nbnd=NbndHumanInput(nbnd=20),
                convergence=ConvergenceHumanInput(conv_thr=1e-11),
            ),
            k_path=KPathOverrides(k_path=KPathHumanInput(k_path_distance=0.05)),
        ),
    )
    scf, bands = advice["scf"].step.kpoints, advice["bands"].step.kpoints

    path = bands.k_path
    assert path.value.k_path_distance == 0.05
    assert path.provenance.field_sources == {"k_path_distance": "human"}
    assert path.value.n_kpoints < default.n_kpoints
    assert [branch.vertices for branch in path.value.branches] == [
        branch.vertices for branch in default.branches
    ]
    assert (bands.nbnd.value.nbnd, bands.nbnd.source) == (20, "human")
    assert (scf.nbnd.value.nbnd, scf.nbnd.source) == (8, "heuristic")
    assert (bands.convergence.value.conv_thr, scf.convergence.value.conv_thr) == (
        1e-11,
        4e-10,
    )


def test_one_job_holds_both_pw_x_steps(store) -> None:
    """The steps run one after the other in one allocation (#169): the job
    is sized over both and splits 95% of its walltime between them by
    workload -- k-point/spin pairs x nbnd x 3 SCF passes for the scf, x 1
    for the bands step, which runs no SCF loop (npw is the same for both
    and cancels). The bands step's pools share out its path's points."""
    advice = _advice(store)
    scf, bands = advice["scf"].step, advice["bands"].step

    job = scf.resources.job.value
    assert bands.resources.job.value is job
    shares = job.max_seconds_by_step
    assert shares.keys() == {"scf", "bands"}
    assert (scf.resources.max_seconds, bands.resources.max_seconds) == (
        shares["scf"],
        shares["bands"],
    )
    budget = int(job.walltime_h * 3600 * 0.95)
    workload = {
        name: (
            step.resources.parallelisation.value.kpoint_spin_pairs
            * step.kpoints.nbnd.value.nbnd
            * passes
        )
        for name, step, passes in (("scf", scf, 3), ("bands", bands, 1))
    }
    for name, share in shares.items():
        assert abs(share - budget * workload[name] / sum(workload.values())) < 1
    assert bands.resources.parallelisation.value.kpoint_spin_pairs == (
        bands.kpoints.k_path.value.n_kpoints
    )


def test_without_pseudopotentials_the_bands_step_degrades(store) -> None:
    """Advice degrades instead of raising: without the table there is no
    electron count, so the bands step's band count and the job are blocked
    by the missing table, while its path, which reads only the cell,
    resolves. The gate names the table once."""
    advice = _advice(
        store,
        overrides=RunOverrides(system=SystemOverrides(pseudo_table_id="nowhere")),
    )
    bands = advice["bands"].step

    assert bands.kpoints.k_path.ok
    assert isinstance(bands.kpoints.nbnd, Blocked)
    assert isinstance(bands.resources.job, Blocked)
    (finding,) = check(advice["bands"], purpose="bands").blocking
    assert finding.code == "advice.blocked"
    assert "nowhere" in finding.message


def test_bands_in_repeats_scf_in_but_for_the_k_points_card(store) -> None:
    """``generate(purpose='bands')`` writes bands.in from the same system as
    scf.in: every card but K_POINTS is the scf's, and its K_POINTS crystal_b
    card holds the vertices of the step's path record. Both steps report
    through the status file of the same save."""
    advice = _advice(store)
    ctx = default_shared_context()
    scf_report = check(advice["scf"])
    bands_report = check(advice["bands"], purpose="bands")
    assert scf_report.ok, scf_report.blocking
    assert bands_report.ok, bands_report.blocking

    (scf,) = generate(advice["scf"], scf_report, ctx=ctx)
    (bands,) = generate(advice["bands"], bands_report, ctx=ctx, purpose="bands")

    scf_cards = _cards(scf.files["scf.in"])
    bands_cards = _cards(bands.files["bands.in"])
    assert scf_cards.pop("K_POINTS automatic")
    assert bands_cards.pop("K_POINTS crystal_b") == k_points_crystal_b(
        advice["bands"].step.kpoints.k_path.value
    ).strip("\n")
    assert bands_cards == scf_cards
    assert list(bands_cards) == [
        "ATOMIC_SPECIES",
        "CELL_PARAMETERS angstrom",
        "ATOMIC_POSITIONS crystal",
    ]
    lines = bands.files["bands.in"].splitlines()
    assert "   calculation      = 'bands'" in lines
    assert "   nbnd             = 12" in lines
    assert (bands.name, bands.stdout) == ("bands", "bands.out")
    assert isinstance(bands.completion, ExitStatusCheck)
    assert bands.completion == scf.completion


def _band(
    structure: Structure, settings: dict[str, object], store: AssetStore
) -> tuple[BandAdvice, CheckReport]:
    """The band task's advice for ``structure`` with the request ``settings``,
    and the gate's verdict on it."""
    advice = advise_band(
        structure,
        hpc=load_hpc_profile("scarf"),
        overrides=build_overrides(settings, task="band"),
        store=store,
    )
    return advice, check_band(advice)


def _generated(
    structure: Structure, settings: dict[str, object], store: AssetStore
) -> tuple[BandAdvice, dict[str, Step]]:
    """The band task's advice and its rendered steps by name, after asserting
    the gate passes."""
    advice, report = _band(structure, settings, store)
    assert report.ok, [finding.message for finding in report.blocking]
    steps = generate_band(advice, report, ctx=default_shared_context())
    return advice, {step.name: step for step in steps}


def _keyword(content: str, name: str) -> str | None:
    match = re.search(rf"^\s*{re.escape(name)}\s*=\s*(\S+)\s*$", content, re.M)
    return None if match is None else match.group(1)


def _path_rows(content: str) -> list[tuple[tuple[float, float, float], str]]:
    """The vertices of a K_POINTS crystal_b card: crystal coordinates and
    label."""
    lines = content.splitlines()
    start = lines.index("K_POINTS crystal_b") + 1
    rows = []
    for line in lines[start + 1 : start + 1 + int(lines[start])]:
        numbers, label = line.split("!")
        k1, k2, k3, _steps = numbers.split()
        rows.append(((float(k1), float(k2), float(k3)), label.strip()))
    return rows


def test_a_band_task_writes_scf_bands_and_bands_x_in_one_script(store) -> None:
    """Diamond Si without spin: one bands.x run after the two pw.x steps,
    each pw.x step with its share of the one job's walltime, in run order.
    bands.in's path is its record's, and its cards are scf.in's."""
    advice, steps = _generated(mc3d_42058_silicon(), {}, store)

    assert list(steps) == ["scf", "bands", "bands_x"]
    assert [step.executable for step in steps.values()] == ["pw.x", "pw.x", "bands.x"]
    layout = advice.tiers().layout()["steps"]
    assert [step["name"] for step in layout] == ["scf", "bands"]
    assert layout[1]["records"] == [
        "bands_occupations",
        "k_path",
        "bands_nbnd",
        "bands_convergence",
        "bands_parallelisation",
    ]
    scf_in = steps["scf"].files["scf.in"]
    bands_in = steps["bands"].files["bands.in"]
    path = advice.records()["k_path"].value
    assert _keyword(bands_in, "calculation") == "'bands'"
    assert k_points_crystal_b(path) in bands_in
    assert [label for _k, label in _path_rows(bands_in)] == [
        vertex.label for branch in path.branches for vertex in branch.vertices
    ]
    assert (_keyword(scf_in, "nbnd"), _keyword(bands_in, "nbnd")) == ("8", "12")
    scf_cards, bands_cards = _cards(scf_in), _cards(bands_in)
    assert scf_cards.pop("K_POINTS automatic")
    assert bands_cards.pop("K_POINTS crystal_b")
    assert bands_cards == scf_cards
    job = advice.records()["job"].value
    assert job.max_seconds_by_step == {
        "scf": int(_keyword(scf_in, "max_seconds")),
        "bands": int(_keyword(bands_in, "max_seconds")),
    }
    assert "max_seconds" not in steps["bands_x"].files["bands_x.in"]
    script = render_submission_band(
        advice, load_hpc_profile("scarf"), "quantum_espresso", tuple(steps.values())
    )
    lines = script.splitlines()
    assert [line for line in lines if line.startswith("# ")] == [
        "# scf",
        "# bands",
        "# bands_x",
    ]
    assert "srun --nodes=1 --ntasks=1 bands.x -in bands_x.in > bands_x.out" in lines
    assert lines[-1] == (
        'goldilocks_check_stdout_marker "bands_x" "bands_x.out" "JOB DONE"'
    )


def test_a_band_bundle_records_the_task_and_cites_the_path(store, tmp_path) -> None:
    """The bundle holds every step's input and one script; goldilocks.json
    names the band task, and CITATIONS.md the path's convention."""
    structure = mc3d_42058_silicon()
    advice, steps = _generated(structure, {"k_path_distance": 0.05}, store)
    hpc = load_hpc_profile("scarf")
    ctx = default_shared_context()
    rendered = tuple(steps.values())
    bundle = to_bundle_input_band(
        advice,
        rendered,
        render_submission_band(advice, hpc, "quantum_espresso", rendered),
        ctx,
        code="quantum_espresso",
        hpc=hpc,
        assignments={"k_path_distance": 0.05},
        source=in_memory_source(structure),
    )
    publish(bundle, DirectoryOutput(tmp_path / "bundle"))

    files = {path.name for path in (tmp_path / "bundle").iterdir()}
    assert {"scf.in", "bands.in", "bands_x.in", "submit.sh"} <= files
    manifest = strict_json((tmp_path / "bundle" / "goldilocks.json").read_text())
    assert manifest["request"]["task"] == "band"
    assert manifest["request"]["overrides"] == {"k_path_distance": 0.05}
    k_path = manifest["records"]["k_path"]
    assert k_path["value"]["k_path_distance"] == 0.05
    assert k_path["field_sources"] == {"k_path_distance": "human"}
    citations = (tmp_path / "bundle" / "CITATIONS.md").read_text()
    assert "- Setyawan and Curtarolo, Comput. Mater. Sci. 49, 299 (2010)\n" in (
        citations
    )


def test_a_collinear_magnet_runs_bands_x_once_per_spin_channel(store) -> None:
    """hcp Gd, a collinear smearing magnet: neither pw.x input pins a
    moment, the scf's 28 bands leave its majority channel room for the 10
    Bohr magnetons its starting magnetization seeds (#131), and the bands
    step computes three times the 18 occupied bands. bands.x writes each
    channel to its own file, one run after the other."""
    advice, steps = _generated(hcp_gadolinium(), {}, store)

    assert list(steps) == ["scf", "bands", "bands_x_up", "bands_x_down"]
    for name, input_file in (("scf", "scf.in"), ("bands", "bands.in")):
        content = steps[name].files[input_file]
        assert _keyword(content, "nspin") == "2"
        assert _keyword(content, "tot_magnetization") is None
    assert _keyword(steps["scf"].files["scf.in"], "nbnd") == "28"
    assert _keyword(steps["bands"].files["bands.in"], "nbnd") == "54"
    assert advice.records()["magnetic"].value.seeded_moment == pytest.approx(10.0)
    for name, filband, channel in (
        ("bands_x_up", "'bands_up.dat'", "1"),
        ("bands_x_down", "'bands_down.dat'", "2"),
    ):
        content = steps[name].files[f"{name}.in"]
        assert (_keyword(content, "filband"), _keyword(content, "spin_component")) == (
            filband,
            channel,
        )


def test_a_spin_orbit_magnet_runs_bands_x_once(store) -> None:
    """hcp Gd with spin-orbit coupling, a noncollinear magnet: both pw.x
    inputs are noncollinear, the bands step computes three times the 36
    occupied spinor bands, and bands.x, which takes only the first spin
    component of a noncollinear run (QE 7.3 ``PP/src/bands.f90:119-120``),
    runs once with none set. The path assumes E(k) = E(-k), which the
    moments can break, and the advice says so."""
    advice, steps = _generated(hcp_gadolinium(), {"spin_orbit_coupling": True}, store)

    assert list(steps) == ["scf", "bands", "bands_x"]
    for name, input_file in (("scf", "scf.in"), ("bands", "bands.in")):
        content = steps[name].files[input_file]
        assert _keyword(content, "noncolin") == ".true."
        assert _keyword(content, "lspinorb") == ".true."
    assert _keyword(steps["bands"].files["bands.in"], "nbnd") == "108"
    assert "spin_component" not in steps["bands_x"].files["bands_x.in"]
    codes = {warning["code"] for warning in advice.warnings()}
    assert "k_path.magnetic_noncollinear_symmetry" in codes


def test_a_bands_step_below_the_seeded_majority_count_misses_bands(store) -> None:
    """hcp Gd's seeded majority channel fills (36 + 10)/2 = 23 electrons:
    22 bands pass the gate's floor of 18, but leave occupied majority bands
    out of the band structure if the scf reaches that moment, which the
    bands step's warning says. The scf keeps its default."""
    advice, _steps = _generated(hcp_gadolinium(), {"steps.bands.nbnd": 22}, store)

    records = advice.records()
    assert records["nbnd"].value.nbnd == 28
    bands = records["bands_nbnd"].value
    assert bands.nbnd == 22
    (capped,) = (w for w in bands.warnings if w.code == "nbnd.moment_capped")
    assert capped.message.startswith(
        "nbnd=22 holds fewer than the (nelec + |M|)/2 = 23 electrons the "
        "majority spin channel fills"
    )
    assert "this bands step" in capped.message
    assert "Use nbnd >= 23" in capped.message


def _primitive_nickel_oxide() -> Structure:
    return Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(4.17), ["Ni", "O"], [[0, 0, 0], [0.5, 0.5, 0.5]]
    ).get_primitive_structure()


@pytest.mark.skipif(
    not enumlib_installed(),
    reason="needs the enumlib executables (enum.x, makeStr.py) on PATH",
)
def test_a_compensated_antiferromagnet_runs_its_band_task_on_smearing(store) -> None:
    """AFM-II NiO classified non-metal pins tot_magnetization = 0 on fixed
    occupations (#138), which bands.x would stop on: the band task's scf
    derives no moment, takes smearing, and says why in its occupations
    record. Other tasks keep the pinned moment."""
    settings = {"magnetic_ordering": "afm", "is_metal": "non_metal"}

    advice, steps = _generated(_primitive_nickel_oxide(), settings, store)
    scf_task = advise(
        _primitive_nickel_oxide(),
        hpc=load_hpc_profile("scarf"),
        overrides=build_overrides(settings, task="scf_single_point"),
        store=store,
    )

    occupations = advice.records()["occupations"]
    assert advice.records()["magnetic"].value.compensated is True
    assert occupations.value.occupations == "smearing"
    assert occupations.value.tot_magnetization is None
    assert occupations.provenance.source_note == (
        BAND_SCF_PROTOCOL.unpinned_moment.note
    )
    assert list(steps) == ["scf", "bands", "bands_x_up", "bands_x_down"]
    for name, input_file in (("scf", "scf.in"), ("bands", "bands.in")):
        assert _keyword(steps[name].files[input_file], "tot_magnetization") is None
    pinned = scf_task.step.kpoints.occupations.value
    assert (pinned.occupations, pinned.tot_magnetization) == ("fixed", 0.0)


def test_tetrahedra_on_the_scf_are_written_as_smearing_in_bands_in(store) -> None:
    """pw.x stops on tetrahedra without an automatic k-point grid (QE 7.3
    PW/src/setup.f90:598), and a bands run only weights its bands, at the
    scf's Fermi energy: the bands step takes cold smearing at 0.01 Ry, and
    its occupations record says so."""
    advice, steps = _generated(
        mc3d_42058_silicon(), {"occupations": "tetrahedra_opt"}, store
    )

    scf_in = steps["scf"].files["scf.in"]
    bands_in = steps["bands"].files["bands.in"]
    assert _keyword(scf_in, "occupations") == "'tetrahedra_opt'"
    assert (
        _keyword(bands_in, "occupations"),
        _keyword(bands_in, "smearing"),
        _keyword(bands_in, "degauss"),
    ) == ("'smearing'", "'cold'", "0.01")
    note = advice.records()["bands_occupations"].provenance.source_note
    assert note.startswith("The scf step's tetrahedra_opt is written as cold smearing")


def test_a_requested_moment_is_refused_with_a_remedy_that_runs(store) -> None:
    """Fixed occupations pinning a moment on a collinear run pass the scf's
    rules, but bands.x would stop on its two Fermi energies. The remedy also
    sets smearing: clearing the moment alone would leave fixed occupations
    with no moment to pin."""
    settings = {"spin_polarized": True, "occupations": "fixed", "tot_magnetization": 0}

    _advice, report = _band(mc3d_42058_silicon(), settings, store)
    (finding,) = report.blocking
    (remedy,) = finding.remedies
    patched = {**settings, **remedy}
    remedied = {key: value for key, value in patched.items() if value is not None}
    advice, steps = _generated(mc3d_42058_silicon(), remedied, store)
    _advice, moment_cleared = _band(
        mc3d_42058_silicon(), {"spin_polarized": True, "occupations": "fixed"}, store
    )

    assert finding.code == "occupations.bands_x_refuses_tot_magnetization"
    assert remedy == {"occupations": "smearing", "tot_magnetization": None}
    assert list(steps) == ["scf", "bands", "bands_x_up", "bands_x_down"]
    assert advice.records()["occupations"].value.tot_magnetization is None
    assert [each.code for each in moment_cleared.blocking] == [
        "occupations.fixed_needs_tot_magnetization"
    ]


def test_a_slab_s_path_lies_in_its_plane(store) -> None:
    """Graphene under QE's 2D truncation: the hexagonal 2D path, every
    vertex at 0 along the vacuum axis, and bands.in repeats scf.in's
    assume_isolated, which the bands run's potential is rebuilt with."""
    advice, steps = _generated(graphene_monolayer(), {"isolation": "slab"}, store)

    path = advice.records()["k_path"].value
    bands_in = steps["bands"].files["bands.in"]
    assert (path.convention, path.lattice_type) == ("bravais_2d", "HEX2D")
    assert [label for _k, label in _path_rows(bands_in)] == ["Gamma", "M", "K", "Gamma"]
    assert all(k[2] == 0 for k, _label in _path_rows(bands_in))
    assert _keyword(bands_in, "assume_isolated") == "'2D'"
    assert _keyword(steps["scf"].files["scf.in"], "assume_isolated") == "'2D'"


def test_a_generated_slab_with_a_tilted_c_gets_a_rectangular_path(store) -> None:
    """pymatgen's TiO2(101) slab, a Pc layer under a tilted c: its path
    holds Gamma and stays in the plane of the layer."""
    slab = Structure.from_sites(generated_slab(rutile_titanium_dioxide(), (1, 0, 1)))

    advice, steps = _generated(slab, {}, store)

    rows = _path_rows(steps["bands"].files["bands.in"])
    assert advice.records()["k_path"].value.lattice_type == "RECT"
    assert ((0.0, 0.0, 0.0), "Gamma") in rows
    assert all(k[2] == 0 for k, _label in rows)


def test_a_wire_runs_gamma_to_z(store) -> None:
    """The carbon chain's cell holds two periods along its axis, so Z, half
    a reciprocal vector of one period, is a whole one of the cell's."""
    advice, steps = _generated(carbon_chain(), {}, store)

    assert advice.records()["k_path"].value.lattice_type == "LINE"
    assert _path_rows(steps["bands"].files["bands.in"]) == [
        ((0.0, 0.0, 0.0), "Gamma"),
        ((0.0, 0.0, 1.0), "Z"),
    ]


def test_a_molecule_in_a_box_is_refused_once(store) -> None:
    """A box has no band path, so its bands step has no k-points and its job
    blocks on the same root cause: the gate names it once, with the tasks
    that apply and no remedy."""
    advice, report = _band(carbon_pair_in_a_box(), {}, store)

    (finding,) = report.blocking
    assert finding.code == "advice.blocked"
    assert finding.message == (
        "a molecule or cluster in a box has no band structure; use the "
        "scf_single_point or relax task"
    )
    assert finding.remedies == ()
    assert isinstance(advice.records()["k_path"], Blocked)


def test_a_conventional_cell_s_bands_are_noticed_as_folded(store) -> None:
    advice, _report = _band(fcc_lead(), {}, store)

    (folded,) = (
        warning
        for warning in advice.warnings()
        if warning["code"] == "k_path.folded_bands"
    )
    assert folded["record"] == "k_path"
    assert "4 primitive cells" in folded["message"]
