"""The magnetic decision is advised, checked and written as one input.

``magnetic_ordering=afm`` can replace the uploaded cell with a different
one: rock-salt NiO's 2-atom primitive cell and its 8-atom conventional cell
both become the 4-atom AFM-II cell. Every count the input carries -- the
electron count, ``nbnd``, ``conv_thr``, the k-points (a band task's path
included, #118) and the job's memory estimate -- must then describe that
written cell (#128). They used to be counted on
the uploaded cell while the writer rendered the AFM one, and the writer
turned the electron difference into ``tot_charge = 24.0`` (2-atom input)
or ``-48.0`` (8-atom input).

The control is the written cell passed in directly, with its spins removed
(spin-decorated species never reach the analysis tier) and the AFM run's
own seeds as ``starting_magnetization``, so the magnetic step splits it
into the same species (#170). Runs on a synthetic SSSP-shaped Ni/O table
(z_valence 18 and 6) with the real enumlib.

Spin-orbit coupling makes a run noncollinear, where pw.x has no
``tot_magnetization`` and fixed occupations need none (#146). The CrI3
monolayer (MC2D mc2d-da9644c9) runs on a synthetic fully relativistic Cr/I
table (z_valence 14 and 7) and needs no enumlib. B2 FeCo (MC3D mc3d-60258)
runs on a synthetic fully relativistic Fe/Co table (z_valence 16 and 17):
its moment direction is a setting, and its k-points are counted with the
moments as pw.x counts them (#172).

Olivine LiFePO4 (MC3D mc3d-52501) has 28 sites but only 4 Fe for enumlib to
order, so ``magnetic_ordering=afm`` orders them (#171); it runs on a
synthetic Li/Fe/P/O table (z_valence 3, 16, 5 and 6) with the real enumlib.

A spin-polarized non-metal used to get fixed occupations without the
integer ``tot_magnetization`` pw.x needs for them on nspin=2, so the gate
refused the default for LiFePO4 and for NiO classified non-metal (#138).
Such a run now gets smearing, unless the applied ordering is compensated
by symmetry: then fixed occupations pin ``tot_magnetization = 0``.

On a slab, plain afm applied a cell repeated across the vacuum: the GdI2
monolayer doubled along c, its gates refused 'slab' and fix_bottom_layers
for two sheets, and the dipole notice of a polar Janus VSSe sheet kept the
uploaded cell's edir and emaxpos for a cell whose vacuum had moved to b.
Orderings now keep the vacuum vector, and the notice reads the written
cell (#144). Hematite Fe2O3 is written by its listed label, and the record
names the label, the criterion and the other candidates of its size. GdI2
runs on a synthetic Gd/I table (z_valence 18 and 7), Fe2O3 on Fe/O (16
and 6).

A collinear smearing magnet's bands leave its majority channel room for
the moment its starting magnetization seeds (#131); hcp Gd runs on the
Gd/I table.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import numpy as np
import pytest
from pymatgen.core import Lattice, Species, Structure
from support import hcp_gadolinium, sssp_fixture_table_spec

from goldilocks_core.advisors.magnetic_config import OrderingRecord
from goldilocks_core.advisors.magnetic_enumeration import enumlib_installed
from goldilocks_core.analysis.geometry import slab_geometry, slab_layers, vacuum_axes
from goldilocks_core.analysis.symmetry import symmetry
from goldilocks_core.assets.pseudopotentials.importers import sssp_preparer
from goldilocks_core.assets.store import AssetStore
from goldilocks_core.inputs.hpc import Hardware, HpcProfile, Partition
from goldilocks_core.service import (
    Advice,
    AdviceIncomplete,
    PathStepAdvice,
    advise,
    advise_band,
    advise_dos,
    advise_relax,
    check,
    check_band,
    check_dos,
    check_relax,
    generate,
    generate_band,
    generate_dos,
    generate_relax,
)
from goldilocks_core.service._magnetic_orderings import list_magnetic_orderings
from goldilocks_core.set_overrides import build_overrides

_needs_enumlib = pytest.mark.skipif(
    not enumlib_installed(),
    reason="needs the enumlib executables (enum.x, makeStr.py) on PATH",
)

_NEUTRAL_AFM_CELL_NELEC = 2 * 18.0 + 2 * 6.0


def _conventional_nio() -> Structure:
    return Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(4.17), ["Ni", "O"], [[0, 0, 0], [0.5, 0.5, 0.5]]
    )


def _primitive_nio() -> Structure:
    return _conventional_nio().get_primitive_structure()


def _hpc() -> HpcProfile:
    hardware = Hardware(
        cores_per_node=64, mem_per_node_gb=250, max_nodes=100, max_walltime_h=168
    )
    return HpcProfile(
        name="test-cluster",
        scheduler="slurm",
        launcher="srun",
        modules={"quantum_espresso": ("qe/7.2",)},
        partitions={"scarf": Partition(name="scarf", hardware=hardware, default=True)},
    )


@pytest.fixture
def store(tmp_path, monkeypatch) -> AssetStore:
    spec, registry_table = sssp_fixture_table_spec(
        tmp_path / "sources", {"Ni": 18.0, "O": 6.0}
    )
    monkeypatch.setattr(
        "goldilocks_core.service._pseudo.load_tables",
        lambda *a, **kw: {registry_table.id: registry_table},
    )
    installed = AssetStore(tmp_path / "store")
    installed.install(spec, sssp_preparer(registry_table))
    return installed


def _run(
    task: str, structure: Structure, settings: dict[str, object], store: AssetStore
) -> tuple[tuple[Advice, ...], tuple[str, ...]]:
    """Every pw.x step's ``Advice`` and every pw.x input for ``task``,
    after asserting the gate passes."""
    overrides = build_overrides(
        settings, task="scf_single_point" if task == "scf" else task
    )
    if task == "scf":
        advice = advise(structure, hpc=_hpc(), overrides=overrides, store=store)
        report, steps = check(advice), (advice,)
        rendered = generate(advice, report) if report.ok else ()
    elif task == "dos":
        dos = advise_dos(structure, hpc=_hpc(), overrides=overrides, store=store)
        report, steps = check_dos(dos), (dos.scf, dos.nscf)
        rendered = generate_dos(dos, report) if report.ok else ()
    elif task == "band":
        band = advise_band(structure, hpc=_hpc(), overrides=overrides, store=store)
        report, steps = check_band(band), (band.scf, band.bands)
        rendered = generate_band(band, report) if report.ok else ()
    else:
        relax = advise_relax(
            structure, calculation=task, hpc=_hpc(), overrides=overrides, store=store
        )
        report, steps = check_relax(relax), (relax.advice,)
        rendered = generate_relax(relax, report) if report.ok else ()
    assert report.ok, report.blocking
    inputs = tuple(
        content
        for step in rendered
        if step.executable == "pw.x"
        for content in step.files.values()
    )
    return steps, inputs


def _keyword(content: str, name: str) -> str | None:
    match = re.search(rf"^\s*{re.escape(name)}\s*=\s*(\S+)\s*$", content, re.M)
    return None if match is None else match.group(1)


def _counts(advice: Advice) -> dict[str, object]:
    """The counts of one pw.x step: its k-points are a mesh, or a bands
    step's path, by its vertices' labels and the steps between them."""
    kpoints = advice.step.kpoints
    job = advice.step.resources.job.value
    if isinstance(kpoints, PathStepAdvice):
        sampling = tuple(
            (tuple(vertex.label for vertex in branch.vertices), branch.steps)
            for branch in kpoints.k_path.value.branches
        )
    else:
        sampling = kpoints.k_sampling.value.mesh
    return {
        "nelec": advice.system.electron_count.value.nelec,
        "nbnd": kpoints.nbnd.value.nbnd,
        "conv_thr": kpoints.convergence.value.conv_thr,
        "k_points": sampling,
        "n_irr_k": kpoints.n_irr_k.value,
        "npool": advice.step.resources.parallelisation.value.npool,
        "job": (
            job.nodes,
            job.ntasks,
            job.memory_per_process_mb,
            job.memory_total_mb,
        ),
    }


_INPUT_CELLS: dict[str, Callable[[], Structure]] = {
    "2-atom primitive": _primitive_nio,
    "8-atom conventional": _conventional_nio,
}


@_needs_enumlib
@pytest.mark.parametrize("task", ["scf", "relax", "dos", "band"])
@pytest.mark.parametrize("input_cell", list(_INPUT_CELLS))
def test_every_count_describes_the_written_afm_cell(
    input_cell: str, task: str, store: AssetStore
) -> None:
    afm_steps, afm_inputs = _run(
        task, _INPUT_CELLS[input_cell](), {"magnetic_ordering": "afm"}, store
    )

    assert afm_inputs
    for content in afm_inputs:
        assert _keyword(content, "nat") == "4"
        assert _keyword(content, "tot_charge") is None
    electron_count = afm_steps[0].system.electron_count.value
    assert electron_count.nelec == _NEUTRAL_AFM_CELL_NELEC
    assert electron_count.tot_charge == 0.0

    magnetic = afm_steps[0].system.magnetic.value
    control = magnetic.cell.copy()
    control.remove_spin()
    control_steps, _ = _run(
        task,
        control,
        {
            "spin_polarized": True,
            "starting_magnetization": magnetic.starting_magnetization,
        },
        store,
    )
    assert [_counts(step) for step in afm_steps] == [
        _counts(step) for step in control_steps
    ]


@_needs_enumlib
def test_nelec_for_the_uploaded_cell_is_refused_once_the_ordering_resizes_it(
    store: AssetStore,
) -> None:
    """A ``nelec`` counts the electrons of the cell the user uploaded; an
    ordering that writes a cell of a different size makes it describe a
    cell the user did not get, so the electron count blocks instead of
    being rendered as a charge."""
    advice = advise(
        _primitive_nio(),
        hpc=_hpc(),
        overrides=build_overrides(
            {"magnetic_ordering": "afm", "nelec": 24.0}, task="scf_single_point"
        ),
        store=store,
    )

    report = check(advice)

    assert not report.ok
    assert not advice.system.electron_count.ok
    reason = advice.system.electron_count.root_cause()
    assert "nelec" in reason
    assert "2-atom" in reason
    assert "4-atom" in reason
    assert reason in [finding.message for finding in report.blocking]


def _starting_magnetization_lines(content: str) -> list[str]:
    return [
        line.strip()
        for line in content.splitlines()
        if line.strip().startswith("starting_magnetization(")
    ]


@_needs_enumlib
def test_a_listed_candidate_and_plain_afm_write_the_same_seeds_and_symmetry(
    store: AssetStore,
) -> None:
    """#170: a /magnetic-orderings candidate fed to a run seeded Ni at the
    flat 0.1 with O at +0.1, its symmetry counted on a spin-less CIF
    (Fm-3m), while magnetic_ordering=afm seeded the same AFM-II cell at
    5/18 (R-3m). Both are now one magnetic step: the candidate is its
    label, the deck seeds the Ni sublattice from z_valence and leaves O at
    0, and symmetry_eff is the split cell's. The two paths also wrote the
    cell in different orientations, where pw.x found 2 and 4 operations;
    both now write one cell, in the frame where pw.x keeps all 12 of R-3m's
    and n_irr_k counts them (#140)."""
    nio = _primitive_nio()
    afm_steps, (afm_deck,) = _run("scf", nio, {"magnetic_ordering": "afm"}, store)
    applied = afm_steps[0].system.magnetic.value.ordering.applied
    [candidate] = [
        candidate
        for candidate in list_magnetic_orderings(nio).candidates
        if candidate.label == applied
    ]
    listed_steps, (listed_deck,) = _run("scf", nio, dict(candidate.overrides), store)

    assert applied == "afm-1"
    assert candidate.overrides == {"magnetic_ordering": "afm-1"}
    assert _starting_magnetization_lines(afm_deck) == _starting_magnetization_lines(
        listed_deck
    )
    for steps in (afm_steps, listed_steps):
        magnetic = steps[0].system.magnetic.value
        assert magnetic.starting_magnetization == pytest.approx(
            {"Ni1": 5.0 / 18.0, "Ni2": -5.0 / 18.0, "O": 0.0}
        )
        assert steps[0].system.symmetry_eff.value.space_group_symbol == "R-3m"
    species = afm_deck.split("ATOMIC_SPECIES\n")[1].split("\n\n")[0]
    assert [line.split()[0] for line in species.splitlines()] == ["Ni1", "Ni2", "O"]
    assert float(_keyword(afm_deck, "starting_magnetization(3)")) == 0.0
    for card in ("CELL_PARAMETERS", "ATOMIC_POSITIONS"):
        assert _card(afm_deck, card) == _card(listed_deck, card)
    frames = [
        steps[0].system.magnetic.value.frame for steps in (afm_steps, listed_steps)
    ]
    assert [frame.operations for frame in frames] == [12, 12]
    assert (
        afm_steps[0].step.kpoints.n_irr_k.value
        == listed_steps[0].step.kpoints.n_irr_k.value
    )


def _card(content: str, header: str) -> list[str]:
    """The rows of the card ``header`` opens, up to the blank line after it."""
    lines = content.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(header)) + 1
    end = next(i for i in range(start, len(lines)) if not lines[i].strip())
    return lines[start:end]


def _cri3_monolayer() -> Structure:
    """MC2D's CrI3 monolayer (mc2d-da9644c9), layer group p-31m: a Cr
    honeycomb between two iodine planes, 18.1 A between layers."""
    return Structure.from_spacegroup(
        "P-31m",
        Lattice.hexagonal(6.971, 18.10),
        ["Cr", "I"],
        [[1 / 3, 2 / 3, 0.5], [0.3706, 0.0, 0.5842]],
    )


@pytest.fixture
def spin_orbit_store(tmp_path, monkeypatch) -> AssetStore:
    """A fully relativistic Cr/I table, the one a spin-orbit run selects."""
    spec, registry_table = sssp_fixture_table_spec(
        tmp_path / "sources", {"Cr": 14.0, "I": 7.0}, relativistic="full"
    )
    monkeypatch.setattr(
        "goldilocks_core.service._pseudo.load_tables",
        lambda *a, **kw: {registry_table.id: registry_table},
    )
    installed = AssetStore(tmp_path / "store")
    installed.install(spec, sssp_preparer(registry_table))
    return installed


_SPIN_ORBIT_FIXED = {"spin_orbit_coupling": True, "occupations": "fixed"}


def test_spin_orbit_with_fixed_occupations_writes_a_noncollinear_deck(
    spin_orbit_store: AssetStore,
) -> None:
    """#146: the gate used to demand an integer tot_magnetization, which
    the writer then refused. A noncollinear run needs none: pw.x stops on
    fixed occupations without one only with nspin=2 (QE 7.3
    PW/src/input.f90:764-781), and QE 7.5 on SCARF ran CrI3 with
    noncolin, lspinorb, fixed occupations and starting moments alone."""
    steps, (content,) = _run(
        "scf", _cri3_monolayer(), _SPIN_ORBIT_FIXED, spin_orbit_store
    )

    assert steps[0].system.magnetic.value.spin_mode == "noncollinear"
    assert _keyword(content, "noncolin") == ".true."
    assert _keyword(content, "lspinorb") == ".true."
    assert _keyword(content, "occupations") == "'fixed'"
    # Cr's 5 Bohr magneton seed over its z_valence: a magnetic deck
    assert float(_keyword(content, "starting_magnetization(1)")) == pytest.approx(
        5.0 / 14.0
    )
    assert _keyword(content, "nspin") is None
    assert _keyword(content, "tot_magnetization") is None


def test_spin_orbit_refuses_tot_magnetization_before_generation(
    spin_orbit_store: AssetStore,
) -> None:
    """#146: pw.x accepts tot_magnetization only with nspin=2
    (input.f90:761-762). The gate refuses it -- so /explain shows it --
    and generate() never reaches a writer."""
    advice = advise(
        _cri3_monolayer(),
        hpc=_hpc(),
        overrides=build_overrides(
            {**_SPIN_ORBIT_FIXED, "tot_magnetization": 6.0}, task="scf_single_point"
        ),
        store=spin_orbit_store,
    )

    report = check(advice)

    messages = [finding.message for finding in report.blocking]
    assert any("tot_magnetization" in message for message in messages), messages
    with pytest.raises(AdviceIncomplete):
        generate(advice, report)


def test_an_ignored_tot_magnetization_never_reaches_a_spin_orbit_deck(
    spin_orbit_store: AssetStore,
) -> None:
    """#146: an explicit spin_polarized=false ignores tot_magnetization
    with a warning, and the deck then carries none."""
    steps, (content,) = _run(
        "scf",
        _cri3_monolayer(),
        {**_SPIN_ORBIT_FIXED, "spin_polarized": False, "tot_magnetization": 6.0},
        spin_orbit_store,
    )

    codes = {warning["code"] for warning in steps[0].warnings()}
    assert "magnetic.magnetization_ignored_spin_polarized_false" in codes
    assert _keyword(content, "noncolin") == ".true."
    assert "starting_magnetization" not in content
    assert _keyword(content, "tot_magnetization") is None


def _b2_feco() -> Structure:
    """B2 FeCo (Pm-3m, MC3D mc3d-60258)."""
    return Structure(
        Lattice.cubic(2.80), ["Fe", "Co"], [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]]
    )


@pytest.fixture
def feco_spin_orbit_store(tmp_path, monkeypatch) -> AssetStore:
    """A fully relativistic Fe/Co table, the one a spin-orbit run selects."""
    spec, registry_table = sssp_fixture_table_spec(
        tmp_path / "sources", {"Fe": 16.0, "Co": 17.0}, relativistic="full"
    )
    monkeypatch.setattr(
        "goldilocks_core.service._pseudo.load_tables",
        lambda *a, **kw: {registry_table.id: registry_table},
    )
    installed = AssetStore(tmp_path / "store")
    installed.install(spec, sssp_preparer(registry_table))
    return installed


_FECO_SPIN_ORBIT = {"spin_orbit_coupling": True, "k_grid": [10, 10, 10]}


def test_spin_orbit_moments_start_along_c_and_count_k_points_as_pw_x_does(
    feco_spin_orbit_store: AssetStore,
) -> None:
    """#172: a magnetic spin-orbit run's moment direction is a physical
    choice. Unset, the moments start along [001] of the uploaded cell,
    which records.magnetic reports with its source and an info notice
    names. n_irr_k counts the operations that keep those moments: pw.x 7.5
    ran this 10x10x10 FeCo deck with 16 operations and 126 k-points; the
    structural count of 56 sized npool and memory for too few."""
    steps, (content,) = _run("scf", _b2_feco(), _FECO_SPIN_ORBIT, feco_spin_orbit_store)

    advice = steps[0]
    assert advice.step.kpoints.n_irr_k.value == 126
    direction = advice.records()["magnetic"].value.moment_direction
    assert (direction.uvw, direction.source) == ((0.0, 0.0, 1.0), "heuristic")
    codes = {warning["code"] for warning in advice.warnings()}
    assert "magnetic.soc_moment_direction_defaulted" in codes
    for species in (1, 2):
        assert float(_keyword(content, f"angle1({species})")) == 0.0
        assert float(_keyword(content, f"angle2({species})")) == 0.0


def test_a_moment_direction_setting_is_written_as_qe_s_angles(
    feco_spin_orbit_store: AssetStore,
) -> None:
    """#172: moment_direction is a setting: [110] of the cubic cell is
    written as angle1 = 90 and angle2 = 45 for every species, and the
    k-points are counted for that direction (8 operations keep it)."""
    steps, (content,) = _run(
        "scf",
        _b2_feco(),
        {**_FECO_SPIN_ORBIT, "moment_direction": [1, 1, 0]},
        feco_spin_orbit_store,
    )

    advice = steps[0]
    direction = advice.records()["magnetic"].value.moment_direction
    assert (direction.uvw, direction.source) == ((1.0, 1.0, 0.0), "human")
    codes = {warning["code"] for warning in advice.warnings()}
    assert "magnetic.soc_moment_direction_defaulted" not in codes
    for species in (1, 2):
        assert float(_keyword(content, f"angle1({species})")) == 90.0
        assert float(_keyword(content, f"angle2({species})")) == 45.0
    assert advice.step.kpoints.n_irr_k.value == 186


def _olivine_lifepo4() -> Structure:
    """Olivine LiFePO4 (Pnma, MC3D mc3d-52501): 28 sites, 4 of them Fe2+."""
    return Structure.from_spacegroup(
        "Pnma",
        Lattice.orthorhombic(10.242, 5.968, 4.687),
        ["Li", "Fe", "P", "O", "O", "O"],
        [
            [0.5, 0.5, 0.5],
            [0.7803, 0.75, 0.4789],
            [0.5948, 0.75, 0.9226],
            [0.5952, 0.75, 0.2504],
            [0.955, 0.75, 0.7068],
            [0.6672, 0.5435, 0.7876],
        ],
    )


@pytest.fixture
def olivine_store(tmp_path, monkeypatch) -> AssetStore:
    spec, registry_table = sssp_fixture_table_spec(
        tmp_path / "sources", {"Li": 3.0, "Fe": 16.0, "P": 5.0, "O": 6.0}
    )
    monkeypatch.setattr(
        "goldilocks_core.service._pseudo.load_tables",
        lambda *a, **kw: {registry_table.id: registry_table},
    )
    installed = AssetStore(tmp_path / "store")
    installed.install(spec, sssp_preparer(registry_table))
    return installed


@_needs_enumlib
def test_afm_orders_the_four_fe_of_olivine_lifepo4(olivine_store: AssetStore) -> None:
    """#171: a ceiling on all 28 sites kept LiFePO4 ferromagnetic and listed
    only 'fm', though pymatgen enumerates its 4 Fe in about a second."""
    olivine = _olivine_lifepo4()

    listing = list_magnetic_orderings(olivine)
    advice = advise(
        olivine,
        hpc=_hpc(),
        overrides=build_overrides(
            {"magnetic_ordering": "afm"}, task="scf_single_point"
        ),
        store=olivine_store,
    )

    labels = [candidate.label for candidate in listing.candidates]
    assert labels[0] == "fm"
    assert len(labels) > 1
    assert listing.warnings == ()
    magnetic = advice.system.magnetic.value
    assert magnetic.ordering == OrderingRecord(
        requested="afm",
        applied="afm-1",
        criterion="smallest_cell",
        alternatives=("afm-2", "afm-3"),
    )
    assert magnetic.compensated is True
    assert len(magnetic.cell) == 28
    assert {site.label for site in magnetic.cell} == {"Li", "Fe1", "Fe2", "P", "O"}
    assert magnetic.starting_magnetization["Fe1"] == pytest.approx(5.0 / 16.0)
    assert magnetic.starting_magnetization["Fe2"] == pytest.approx(-5.0 / 16.0)


def _bcc_chromium() -> Structure:
    """bcc Cr (MC3D mc3d-49144), its 1-atom primitive cell."""
    return Structure.from_spacegroup(
        "Im-3m", Lattice.cubic(2.8145), ["Cr"], [[0, 0, 0]]
    ).get_primitive_structure()


@pytest.fixture
def chromium_store(tmp_path, monkeypatch) -> AssetStore:
    spec, registry_table = sssp_fixture_table_spec(tmp_path / "sources", {"Cr": 14.0})
    monkeypatch.setattr(
        "goldilocks_core.service._pseudo.load_tables",
        lambda *a, **kw: {registry_table.id: registry_table},
    )
    installed = AssetStore(tmp_path / "store")
    installed.install(spec, sssp_preparer(registry_table))
    return installed


@_needs_enumlib
def test_an_afm_request_writes_an_afm_deck_for_a_non_magnetic_classification(
    chromium_store: AssetStore,
) -> None:
    """#145: with the ML tier classifying bcc Cr non-magnetic,
    magnetic_ordering=afm was dropped and the deck was byte-identical to
    the default one, with no nspin. The request now turns spin polarization
    on and writes the ordered cell, neutral (#128)."""
    steps, (content,) = _run(
        "scf",
        _bcc_chromium(),
        {"is_magnetic": "non_magnetic", "magnetic_ordering": "afm"},
        chromium_store,
    )

    assert steps[0].analysis.is_magnetic.value == "non_magnetic"
    magnetic = steps[0].system.magnetic.value
    assert magnetic.ordering == OrderingRecord(
        requested="afm",
        applied="afm-1",
        criterion="smallest_cell",
        alternatives=("afm-2",),
    )
    assert magnetic.compensated is True
    assert _keyword(content, "nspin") == "2"
    assert _keyword(content, "nat") == "2"
    assert _keyword(content, "ntyp") == "2"
    assert _keyword(content, "tot_charge") is None
    assert float(_keyword(content, "starting_magnetization(1)")) == pytest.approx(
        5.0 / 14.0
    )
    assert float(_keyword(content, "starting_magnetization(2)")) == pytest.approx(
        -5.0 / 14.0
    )


@pytest.mark.parametrize(
    ("structure", "store_fixture"),
    [(_olivine_lifepo4, "olivine_store"), (_primitive_nio, "store")],
    ids=["LiFePO4", "NiO"],
)
def test_a_magnetic_insulator_s_default_passes_the_gate_on_smearing(
    structure: Callable[[], Structure],
    store_fixture: str,
    request: pytest.FixtureRequest,
) -> None:
    """#138: LiFePO4 and NiO classified non-metal got occupations='fixed'
    on nspin=2 with no tot_magnetization, which pw.x stops on (QE 7.3
    PW/src/input.f90:764-778), so check refused the default (a 422 on
    /run). Nothing knows their moment, so they get smearing."""
    steps, (content,) = _run(
        "scf",
        structure(),
        {"is_metal": "non_metal"},
        request.getfixturevalue(store_fixture),
    )

    advice = steps[0]
    assert advice.analysis.is_metal.value == "non_metal"
    assert advice.system.magnetic.value.spin_mode == "collinear"
    assert advice.step.kpoints.occupations.value.occupations == "smearing"
    assert _keyword(content, "occupations") == "'smearing'"
    assert _keyword(content, "nspin") == "2"
    assert _keyword(content, "tot_magnetization") is None


@_needs_enumlib
@pytest.mark.parametrize("task", ["scf", "relax"])
def test_a_compensated_afm_insulator_pins_a_zero_moment_on_fixed_occupations(
    task: str, store: AssetStore
) -> None:
    """#138: the engine-built AFM-II NiO cell has an operation reversing
    every spin, so its moment is 0 by symmetry: fixed occupations with
    tot_magnetization = 0, both spin channels holding 24 electrons, and a
    neutral cell (#128). The request itself carries no moment."""
    steps, (content,) = _run(
        task,
        _primitive_nio(),
        {"magnetic_ordering": "afm", "is_metal": "non_metal"},
        store,
    )

    magnetic = steps[0].system.magnetic.value
    occupations = steps[0].step.kpoints.occupations.value
    assert magnetic.ordering == OrderingRecord(
        requested="afm",
        applied="afm-1",
        criterion="smallest_cell",
        alternatives=("afm-2",),
    )
    assert magnetic.compensated is True
    assert magnetic.tot_magnetization is None
    assert occupations.occupations == "fixed"
    assert occupations.tot_magnetization == 0.0
    assert _keyword(content, "occupations") == "'fixed'"
    assert float(_keyword(content, "tot_magnetization")) == 0.0
    assert _keyword(content, "nbnd") == "24"
    assert _keyword(content, "tot_charge") is None


@_needs_enumlib
@pytest.mark.parametrize(
    "seeds", [{"Ni1": 5.0 / 18.0}, {"Ni2": -5.0 / 18.0}], ids=["Ni1", "Ni2"]
)
def test_restating_one_sublattice_s_seed_keeps_the_afm_insulator_compensated(
    seeds: dict[str, float], store: AssetStore
) -> None:
    """#185: a starting_magnetization that restates one sublattice's
    computed seed (Ni's 5/18 here) writes the seeds the ordering computes,
    so it writes the compensated deck: fixed occupations with
    tot_magnetization = 0, not smearing."""
    settings: dict[str, object] = {"magnetic_ordering": "afm", "is_metal": "non_metal"}
    _, (computed,) = _run("scf", _primitive_nio(), settings, store)

    steps, (content,) = _run(
        "scf", _primitive_nio(), {**settings, "starting_magnetization": seeds}, store
    )

    magnetic = steps[0].system.magnetic.value
    assert magnetic.human_seeded_labels == tuple(seeds)
    assert magnetic.compensated is True
    assert content == computed
    assert float(_keyword(content, "tot_magnetization")) == 0.0


def _tenorite_cuo() -> Structure:
    """Tenorite CuO (C2/c, Asbrink & Norrby 1970), its 4-atom primitive
    cell: Cu2+, 3d9."""
    return Structure.from_spacegroup(
        "C2/c",
        Lattice.monoclinic(4.6837, 3.4226, 5.1288, 99.54),
        ["Cu", "O"],
        [[0.25, 0.25, 0.0], [0.0, 0.4184, 0.25]],
    ).get_primitive_structure()


@pytest.fixture
def cuo_store(tmp_path, monkeypatch) -> AssetStore:
    spec, registry_table = sssp_fixture_table_spec(
        tmp_path / "sources", {"Cu": 19.0, "O": 6.0}
    )
    monkeypatch.setattr(
        "goldilocks_core.service._pseudo.load_tables",
        lambda *a, **kw: {registry_table.id: registry_table},
    )
    installed = AssetStore(tmp_path / "store")
    installed.install(spec, sssp_preparer(registry_table))
    return installed


@pytest.mark.parametrize(
    ("spin_polarized", "nspin", "occupations"),
    [(None, "2", "'smearing'"), (False, None, "'fixed'")],
    ids=["default", "spin_polarized=false"],
)
def test_a_u_on_an_odd_d_shell_writes_a_spin_polarized_deck(
    spin_polarized: bool | None,
    nspin: str | None,
    occupations: str,
    cuo_store: AssetStore,
) -> None:
    """#147: with the classifier calling tenorite CuO non-magnetic, its
    default deck carried U Cu-3d 4 and no nspin: the Hubbard decision was
    resolved apart from the spin decision. The U on Cu2+ d9 now turns spin
    polarization on, under a warning, and the non-metal then runs on
    smearing, since nothing knows its moment (#138). An explicit
    spin_polarized=false still writes the unpolarized deck."""
    settings: dict[str, object] = {
        "is_magnetic": "non_magnetic",
        "is_metal": "non_metal",
    }
    if spin_polarized is not None:
        settings["spin_polarized"] = spin_polarized

    steps, (content,) = _run("scf", _tenorite_cuo(), settings, cuo_store)

    advice = steps[0]
    assert advice.analysis.is_magnetic.value == "non_magnetic"
    assert content.endswith("HUBBARD (ortho-atomic)\n  U  Cu-3d  4\n")
    assert _keyword(content, "nspin") == nspin
    assert _keyword(content, "occupations") == occupations
    codes = {warning["code"] for warning in advice.warnings()}
    assert ("magnetic.spin_polarized_for_hubbard_open_shell" in codes) is (
        spin_polarized is None
    )


def _corundum_fe2o3() -> Structure:
    """Hematite Fe2O3 (R-3c, MC3D mc3d-44692) in its 10-site rhombohedral
    primitive cell, 4 of them Fe3+."""
    return Structure.from_spacegroup(
        "R-3c",
        Lattice.hexagonal(5.035, 13.747),
        ["Fe", "O"],
        [[0, 0, 0.3553], [0.3059, 0, 0.25]],
    ).get_primitive_structure()


@pytest.fixture
def hematite_store(tmp_path, monkeypatch) -> AssetStore:
    spec, registry_table = sssp_fixture_table_spec(
        tmp_path / "sources", {"Fe": 16.0, "O": 6.0}
    )
    monkeypatch.setattr(
        "goldilocks_core.service._pseudo.load_tables",
        lambda *a, **kw: {registry_table.id: registry_table},
    )
    installed = AssetStore(tmp_path / "store")
    installed.install(spec, sssp_preparer(registry_table))
    return installed


@_needs_enumlib
def test_a_requested_label_writes_that_ordering_and_records_its_alternatives(
    hematite_store: AssetStore,
) -> None:
    """#144: plain afm on Fe2O3 applied the Cr2O3-type order (R3c), the
    first of three 10-site candidates, and recorded only its label. The
    hematite order (R-3 with the up and down Fe as two species) is asked
    for by its listed label: the deck is written for it, and
    records.magnetic names it, the criterion and the other two."""
    hematite = _corundum_fe2o3()
    listing = list_magnetic_orderings(hematite)
    [label] = [
        candidate.label
        for candidate in listing.candidates
        if candidate.label != "fm"
        and symmetry(candidate.structure).value.space_group_symbol == "R-3"
    ]
    others = tuple(
        candidate.label
        for candidate in listing.candidates
        if candidate.label not in ("fm", label)
    )

    steps, (content,) = _run(
        "scf", hematite, {"magnetic_ordering": label}, hematite_store
    )

    advice = steps[0]
    assert advice.system.symmetry_eff.value.space_group_symbol == "R-3"
    assert _keyword(content, "nat") == "10"
    magnetic = advice.records()["magnetic"].value
    assert magnetic.ordering == OrderingRecord(
        requested=label,
        applied=label,
        criterion="requested",
        alternatives=tuple(others),
    )
    assert magnetic.compensated is True
    assert len(others) == 2


def _gdi2_monolayer() -> Structure:
    """A 2H GdI2 sheet like MC2D's monolayer (aedf368b): Gd between two I
    planes 1.98 A away, in the xy plane of a cell 19.94 A high along z,
    15.98 A of it vacuum."""
    return Structure(
        Lattice.hexagonal(4.357, 19.94),
        ["Gd", "I", "I"],
        [[1 / 3, 2 / 3, 0.0], [2 / 3, 1 / 3, 0.0993], [2 / 3, 1 / 3, -0.0993]],
    )


@pytest.fixture
def gdi2_store(tmp_path, monkeypatch) -> AssetStore:
    spec, registry_table = sssp_fixture_table_spec(
        tmp_path / "sources", {"Gd": 18.0, "I": 7.0}
    )
    monkeypatch.setattr(
        "goldilocks_core.service._pseudo.load_tables",
        lambda *a, **kw: {registry_table.id: registry_table},
    )
    installed = AssetStore(tmp_path / "store")
    installed.install(spec, sssp_preparer(registry_table))
    return installed


@_needs_enumlib
def test_afm_on_a_monolayer_keeps_one_sheet_for_the_slab_gates(
    gdi2_store: AssetStore,
) -> None:
    """#144: plain afm doubled the GdI2 monolayer across its vacuum (here
    with the doubled c moved to b), so the written cell held two sheets:
    fix_bottom_layers was refused for 'more than one slab' and
    isolation='slab' for vacuum along b. The applied ordering is now in the
    sheet, and the written cell keeps the input's c and vacuum: both gates
    pass, fix_bottom_layers freezes the bottom I layer, and the vacuum the
    step read from the uploaded structure (local-TF mixing) is the written
    cell's."""
    gdi2 = _gdi2_monolayer()

    steps, (content,) = _run(
        "relax",
        gdi2,
        {"magnetic_ordering": "afm", "fix_bottom_layers": 1, "isolation": "slab"},
        gdi2_store,
    )

    advice = steps[0]
    cell = advice.system.magnetic.value.cell
    assert advice.system.magnetic.value.ordering.applied == "afm-1"
    assert len(cell) == 6
    # The written cell is turned about its normal to put a along x (#140),
    # which leaves c where it was.
    assert np.allclose(cell.lattice.matrix[2], gdi2.lattice.matrix[2], atol=1e-12)
    assert vacuum_axes(cell) == advice.analysis.geometry.value.vacuum_axes == ("c",)
    assert len(slab_layers(cell)) == 3
    assert advice.step.kpoints.convergence.value.mixing_mode == "local-TF"
    assert _keyword(content, "assume_isolated") == "'2D'"
    lines = content.splitlines()
    start = lines.index("ATOMIC_POSITIONS crystal") + 1
    rows = [line.split() for line in lines[start : start + len(cell)]]
    fixed = [row for row in rows if row[-3:] == ["0", "0", "0"]]
    assert [row[0] for row in fixed] == ["I", "I"]
    assert {round(float(row[3]) % 1.0, 4) for row in fixed} == {0.9007}


def test_a_smearing_magnet_s_bands_hold_its_seeded_moment(
    gdi2_store: AssetStore,
) -> None:
    """#131: pw.x's own 22 bands held hcp Gd's moment at 2*22 - 36 = 8
    Bohr magnetons on SCARF instead of 15.5. The deck now sizes the
    majority channel for the moment the written seeds carry, 2 x 5/18 x 18
    = 10 from the selected pseudopotential's z_valence: nelup = (36 + 10)/2
    = 23, padded to NINT(1.2 x 23) = 28 bands."""
    gadolinium = Structure.from_spacegroup(
        "P6_3/mmc", Lattice.hexagonal(3.642, 5.902), ["Gd"], [[1 / 3, 2 / 3, 0.25]]
    )

    steps, (content,) = _run("scf", gadolinium, {}, gdi2_store)

    magnetic = steps[0].system.magnetic.value
    assert steps[0].step.kpoints.occupations.value.occupations == "smearing"
    assert magnetic.spin_mode == "collinear"
    assert magnetic.seeded_moment == pytest.approx(10.0)
    assert _keyword(content, "nspin") == "2"
    assert _keyword(content, "tot_magnetization") is None
    assert float(_keyword(content, "starting_magnetization(1)")) == pytest.approx(
        5.0 / 18.0
    )
    assert _keyword(content, "nbnd") == "28"
    assert steps[0].records()["magnetic"].value.seeded_moment == pytest.approx(10.0)


def test_a_dos_nscf_step_below_the_seeded_majority_count_misses_bands(
    gdi2_store: AssetStore,
) -> None:
    """#118: the dos task's nscf step runs at the scf's density, so 22 bands,
    below the (36 + 10)/2 = 23 electrons hcp Gd's seeded majority channel
    fills, leave occupied majority bands out if the scf reaches that moment,
    instead of capping it: the nscf step's warning says that, and the scf
    keeps its 28 bands."""
    (scf, nscf), _ = _run("dos", hcp_gadolinium(), {"steps.nscf.nbnd": 22}, gdi2_store)

    scf_bands = scf.step.kpoints.nbnd.value
    nscf_bands = nscf.step.kpoints.nbnd.value
    assert scf_bands.nbnd == 28
    assert "nbnd.moment_capped" not in [w.code for w in scf_bands.warnings]
    assert nscf_bands.nbnd == 22
    (capped,) = nscf_bands.warnings
    assert capped.code == "nbnd.moment_capped"
    assert capped.message.startswith(
        "nbnd=22 holds fewer than the (nelec + |M|)/2 = 23 electrons the "
        "majority spin channel fills"
    )
    assert "this nscf step" in capped.message
    assert "Use nbnd >= 23" in capped.message


def _janus_vsse(c: float = 20.0) -> Structure:
    """A Janus VSSe sheet (a = 3.30 A) in the xy plane of a cell ``c`` A high
    along z: the S plane 1.50 A above V4+ (d1) and the Se plane 1.62 A
    below. No operation reverses c (P3m1), so it is polar."""
    return Structure(
        Lattice.hexagonal(3.30, c),
        ["V", "S", "Se"],
        [
            [1 / 3, 2 / 3, 0.5],
            [2 / 3, 1 / 3, 0.5 + 1.50 / c],
            [2 / 3, 1 / 3, 0.5 - 1.62 / c],
        ],
    )


def _dipole_notice(advice: Advice) -> str:
    (message,) = [
        warning["message"]
        for warning in advice.warnings()
        if warning["code"] == "boundary.dipole_correction_suggested"
    ]
    return message


def _sawtooth(message: str) -> tuple[int, float, float]:
    """``edir``, ``emaxpos`` and ``eopreg`` of a dipole notice."""
    values = dict(re.findall(r"(edir|emaxpos|eopreg) = ([0-9.]+)", message))
    return int(values["edir"]), float(values["emaxpos"]), float(values["eopreg"])


def _drop_in_vacuum(cell: Structure, edir: int, emaxpos: float, eopreg: float) -> bool:
    """Whether the sawtooth's drop, from ``emaxpos`` to ``emaxpos +
    eopreg`` along lattice vector ``edir``, is centred on the widest
    vacuum of ``cell`` along it and holds no atom."""
    slab = slab_geometry(cell)
    centre = (emaxpos + eopreg / 2) % 1.0
    heights = np.mod(cell.frac_coords[:, edir - 1] - emaxpos, 1.0)
    return (
        slab is not None
        and slab.vacuum_axis == "abc"[edir - 1]
        and abs((centre - slab.vacuum_center + 0.5) % 1.0 - 0.5) < 1e-3
        and bool(np.all(heights > eopreg))
    )


@_needs_enumlib
def test_the_dipole_notice_of_a_polar_afm_slab_describes_the_written_cell() -> None:
    """#144: plain afm on the polar VSSe sheet doubled it across its vacuum
    and moved c to b, while the dipole notice, read from the uploaded
    cell, still put edir = 3. The ordering is now in the sheet, the
    written cell keeps c with its vacuum, and the notice's edir, emaxpos
    and eopreg place the sawtooth's drop in that vacuum."""
    janus = _janus_vsse()

    advice = advise(
        janus,
        hpc=_hpc(),
        overrides=build_overrides(
            {"magnetic_ordering": "afm"}, task="scf_single_point"
        ),
    )

    cell = advice.system.magnetic.value.cell
    edir, emaxpos, eopreg = _sawtooth(_dipole_notice(advice))
    assert advice.system.magnetic.value.ordering.applied == "afm-1"
    assert len(cell) == 6
    assert np.allclose(cell.lattice.matrix[2], janus.lattice.matrix[2], atol=1e-12)
    assert edir == 3
    assert _drop_in_vacuum(cell, edir, emaxpos, eopreg)
    assert "isolation='slab'" in _dipole_notice(advice)


def test_the_dipole_notice_reads_the_vacuum_of_the_cell_written(monkeypatch) -> None:
    """#144: the notice's numbers belong to the cell the input is written
    for. An ordering whose cell sits 0.45 c higher than the upload (its
    vacuum centred at 0.45 instead of 0) moves the sawtooth with it; read
    from the upload, the drop would fall inside the sheet."""
    janus = _janus_vsse()
    a, b, c = janus.lattice.matrix
    species, coords = [], []
    for shift, spin in ((0.45 * c, 5.0), (0.45 * c + b, -5.0)):
        for site in janus:
            species.append(
                Species("V", spin=spin) if site.specie.symbol == "V" else site.specie
            )
            coords.append(site.coords + shift)
    candidate = Structure(
        Lattice([a, 2 * b, c]), species, coords, coords_are_cartesian=True
    )
    monkeypatch.setattr(
        "goldilocks_core.advisors.magnetic_config.enumlib_installed", lambda: True
    )
    monkeypatch.setattr(
        "goldilocks_core.advisors.magnetic_config.enumerate_orderings",
        lambda *_args, **_kwargs: ((candidate, "afm"),),
    )

    advice = advise(
        janus,
        hpc=_hpc(),
        overrides=build_overrides(
            {"magnetic_ordering": "afm"}, task="scf_single_point"
        ),
    )

    cell = advice.system.magnetic.value.cell
    edir, emaxpos, eopreg = _sawtooth(_dipole_notice(advice))
    assert edir == 3
    assert _drop_in_vacuum(cell, edir, emaxpos, eopreg)
    assert not _drop_in_vacuum(janus, edir, emaxpos, eopreg)
    # #210: the published geometry_eff is the written cell's, the one the
    # notice reads; geometry stays the upload's.
    records = advice.records()
    centre = (emaxpos + eopreg / 2) % 1
    assert records["geometry_eff"].value.slab.vacuum_center == pytest.approx(
        centre, abs=1e-4
    )
    assert records["geometry"].value.slab.vacuum_center != pytest.approx(
        centre, abs=1e-2
    )
