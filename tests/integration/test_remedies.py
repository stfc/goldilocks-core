"""Every remedy a finding names produces a runnable input (#151).

The gate's findings name the override patches that resolve them. Before
this, its reasons were prose, and following one could still fail: "set
spin_polarized=true" for an odd electron count with fixed occupations is
refused by the integer-moment rule, and "cell_dofree='all'" for a Cartesian
mask on a rotated slab is refused by the 2D-truncation rule under
isolation=slab. For each finding the gate can return, this runs a request
that triggers it, then the same request with each remedy applied (a None
value removes that override), through ``advise``/``check``/``generate`` on
synthetic SSSP-shaped tables, so it runs in CI. A remedied vc-relax of a
slab must also hold its vacuum fixed: isolation=periodic passes with an
explicit cell_dofree=all, which would relax it, and no cell_dofree remedy may
lead to another refusal. A wire's refusals name the constraint that relaxes
only its period, in any orientation, and that constraint generates too. It
also checks the text a user reads: the findings
and the warnings of real runs with the scarf profile, whose job warnings name
a partition. Each task runs through its row of ``service.TASK_PHASES``.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable
from dataclasses import dataclass
from importlib import resources

import pytest
from pymatgen.core import Lattice, Structure
from pymatgen.core.surface import SlabGenerator
from support import (
    INTERNAL_TEXT,
    antiferromagnetic_nickel_oxide,
    hcp_gadolinium,
    mc3d_42058_silicon,
    molybdenum_disulfide_monolayer,
    rock_salt,
    rotated_about_x,
    silicon_dimer_in_a_box,
    sssp_fixture_table_spec,
    with_vacuum_along,
    wurtzite_zinc_oxide,
)

from goldilocks_core.analysis.geometry import vacuum_axes
from goldilocks_core.assets.pseudopotentials.importers import sssp_preparer
from goldilocks_core.assets.store import AssetStore
from goldilocks_core.checks import FINDING_CATALOGUE, CheckReport
from goldilocks_core.inputs.hpc import load_hpc_profile
from goldilocks_core.service import TASK_PHASES, advise
from goldilocks_core.set_overrides import build_overrides

pytestmark = pytest.mark.integration


def _diamond_silicon() -> Structure:
    """Diamond Si in its 2-atom fcc primitive cell: a and b out of the xy
    plane, and already in pw.x's frame, so it is written unrotated."""
    half = 5.431 / 2
    return Structure(
        Lattice([[0, half, half], [half, 0, half], [half, half, 0]]),
        ["Si", "Si"],
        [[0, 0, 0], [0.25, 0.25, 0.25]],
    )


def _silicon_slab(min_vacuum_size: float = 12) -> Structure:
    """The Si(001) slab of ``test_dimensionality_workflows.py``: 8 atomic
    layers, vacuum along c, 23.08 A of it for ``min_vacuum_size=18``, enough
    for the 2D Coulomb truncation."""
    bulk = Structure.from_spacegroup(
        "Fd-3m", Lattice.cubic(5.431), ["Si"], [[0.0, 0.0, 0.0]]
    )
    slab = SlabGenerator(
        bulk, (0, 0, 1), min_slab_size=8, min_vacuum_size=min_vacuum_size
    ).get_slab()
    return Structure.from_sites(slab)


def _turned_silicon_slab() -> Structure:
    """The Si(001) slab turned about x, which the writer turns back into
    pw.x's frame: the written cell is a rotated one."""
    return rotated_about_x(_silicon_slab(18), 30.0)


def _fcc_aluminium() -> Structure:
    """One-atom fcc Al, 3 valence electrons: the odd count fixed occupations
    without spin polarization cannot fill (the example structures all have
    even counts)."""
    return Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(4.05), ["Al"], [[0, 0, 0]]
    ).get_primitive_structure()


def _example(name: str) -> Callable[[], Structure]:
    path = resources.files("goldilocks_core") / "examples" / "structures" / name
    return lambda: Structure.from_file(str(path))


@dataclass(frozen=True)
class _Trigger:
    task: str
    structure: Callable[[], Structure]
    overrides: dict[str, object]


_TRIGGERS = {
    "occupations.fixed_needs_tot_magnetization": _Trigger(
        "scf", _example("Fe_bcc.cif"), {"occupations": "fixed"}
    ),
    "occupations.fixed_needs_integer_tot_magnetization": _Trigger(
        "scf",
        _example("Fe_bcc.cif"),
        {"occupations": "fixed", "tot_magnetization": 2.5},
    ),
    "occupations.fixed_tot_magnetization_parity": _Trigger(
        "scf",
        _example("Fe_bcc.cif"),
        {"occupations": "fixed", "tot_magnetization": 3},
    ),
    "occupations.fixed_needs_even_electron_count": _Trigger(
        "scf", _fcc_aluminium, {"occupations": "fixed", "spin_polarized": False}
    ),
    "nbnd.too_few_bands": _Trigger("scf", _diamond_silicon, {"nbnd": 2}),
    "relax.vc_relax_needs_bfgs": _Trigger(
        "vc-relax", _diamond_silicon, {"ion_dynamics": "damp"}
    ),
    "boundary.isolated_needs_vacuum": _Trigger(
        "scf", _diamond_silicon, {"isolation": "isolated"}
    ),
    "boundary.slab_unsuited_to_2d_truncation": _Trigger(
        "scf", _diamond_silicon, {"isolation": "slab"}
    ),
    "relax.slab_vc_relax_needs_2d_cell_dofree": _Trigger(
        "vc-relax",
        lambda: _silicon_slab(18),
        {"isolation": "slab", "cell_dofree": "all"},
    ),
    "relax.two_d_cell_dofree_needs_xy_frame": _Trigger(
        "vc-relax", _diamond_silicon, {"cell_dofree": "2Dxy"}
    ),
    "relax.cartesian_cell_dofree_on_rotated_cell": _Trigger(
        "vc-relax", mc3d_42058_silicon, {"cell_dofree": "z"}
    ),
    "vdw.use_vdw_without_d3bj_parameters": _Trigger(
        "scf", _diamond_silicon, {"functional": "LDA", "use_vdw": True}
    ),
    "relax.fix_bottom_layers_needs_slab": _Trigger(
        "relax", _diamond_silicon, {"fix_bottom_layers": 1}
    ),
    "relax.fix_bottom_layers_exceeds_layers": _Trigger(
        "relax", _silicon_slab, {"fix_bottom_layers": 9}
    ),
    "parallelisation.npool_does_not_divide_ntasks": _Trigger(
        "scf", _diamond_silicon, {"npool": 7}
    ),
    "parallelisation.ndiag_grid_too_large": _Trigger(
        "scf", _diamond_silicon, {"npool": 1, "ndiag": 64}
    ),
    "occupations.bands_x_refuses_tot_magnetization": _Trigger(
        "band", hcp_gadolinium, {"tot_magnetization": 7}
    ),
    "phonon.hubbard_projectors_unsupported": _Trigger(
        "phonon",
        antiferromagnetic_nickel_oxide,
        {"is_metal": "non_metal", "magnetic_ordering": "afm"},
    ),
    "phonon.noncollinear_hubbard_unsupported": _Trigger(
        "phonon",
        antiferromagnetic_nickel_oxide,
        {
            "is_metal": "non_metal",
            "is_magnetic": "non_magnetic",
            "spin_orbit_coupling": True,
            "hubbard_projectors": "atomic",
        },
    ),
    "phonon.pinned_moment_with_smearing": _Trigger(
        "phonon", _example("Fe_bcc.cif"), {"tot_magnetization": 2}
    ),
    "phonon.q_grid_breaks_symmetry": _Trigger(
        "phonon", _diamond_silicon, {"is_metal": "non_metal", "q_grid": [4, 4, 3]}
    ),
    "phonon.too_many_q_points": _Trigger(
        "phonon", _diamond_silicon, {"is_metal": "non_metal", "q_distance": 0.02}
    ),
    "phonon.fix_bottom_layers_unsupported": _Trigger(
        "relax-phonon",
        _silicon_slab,
        {"is_metal": "non_metal", "fix_bottom_layers": 1},
    ),
    "phonon.metallicity_unconfirmed": _Trigger("phonon", wurtzite_zinc_oxide, {}),
}
"""A request that blocks with exactly one finding, of that code, per
catalogued code with remedies. The phonon tasks' noncollinear one is
spin-orbit coupling without moments, which ph.x itself does not refuse. A
phonon task refuses smearing on a structure with a non-metal element unless
the user confirms a metal, so the other phonon triggers put the insulators on
fixed occupations, NiO on the 0 of its compensated antiferromagnetic
ordering; ZnO's without is_metal is the metallicity refusal."""

_METALLICITY_VARIANTS = {
    "collinear-set-non-metal": _Trigger(
        "relax-phonon",
        lambda: rock_salt("Ni", "O", 4.17),
        {"is_metal": "non_metal", "hubbard_projectors": "atomic"},
    ),
    "spin-polarized-monolayer": _Trigger(
        "relax-phonon", molybdenum_disulfide_monolayer, {}
    ),
    "odd-electron-count": _Trigger(
        "relax-phonon", lambda: rock_salt("Ti", "N", 4.24), {}
    ),
    "requested-smearing": _Trigger(
        "relax-phonon", wurtzite_zinc_oxide, {"occupations": "smearing"}
    ),
    "requested-fixed-collinear": _Trigger(
        "relax-phonon",
        molybdenum_disulfide_monolayer,
        {"is_metal": "non_metal", "occupations": "fixed"},
    ),
    "requested-fixed-odd-count": _Trigger(
        "relax-phonon",
        lambda: rock_salt("Ti", "N", 4.24),
        {"is_metal": "non_metal", "occupations": "fixed"},
    ),
    "requested-fixed-moment": _Trigger(
        "relax-phonon",
        wurtzite_zinc_oxide,
        {"occupations": "fixed", "tot_magnetization": 2.5},
    ),
}
"""Requests the metallicity refusal offers other remedies for than ZnO's
answers: ferromagnetic NiO set to a non-metal and a MoS2 monolayer the
heuristic spin-polarizes, collinear runs without a moment; TiN, whose odd
electron count fixed occupations cannot fill without spin polarization; ZnO
on the smearing its request sets; and requested fixed occupations these runs
cannot take, the monolayer's and TiN's, and ZnO's with a moment that is not
an integer, which the metallicity refusal replaces the occupations refusal
for, since its remedy, smearing, needs a confirmed metal there."""

_PHONON_MOMENT_TRIGGERS = {
    "occupations.fixed_needs_integer_tot_magnetization": _Trigger(
        "phonon",
        _example("Fe_bcc.cif"),
        {"occupations": "fixed", "tot_magnetization": 2.5},
    ),
    "occupations.fixed_tot_magnetization_parity": _Trigger(
        "phonon",
        _example("Fe_bcc.cif"),
        {"occupations": "fixed", "tot_magnetization": 3},
    ),
}
"""The occupations refusals of a moment fixed occupations cannot take in a
phonon task on bcc Fe, whose remedy, smearing, unsets the moment there,
which ph.x refuses on smearing."""

_UNREACHABLE = {"k_path.too_many_kpoints"}
"""Catalogued codes with remedies that no real request reaches: a band path
needs more than 40000 k-point/spin pairs, which within k_path_distance's
lower bound only a cell with lattice vectors shorter than about 1.4 Angstrom
gives. tests/unit/test_checks.py triggers it on the gate directly."""


@pytest.fixture
def store(tmp_path, monkeypatch) -> AssetStore:
    """The default PBEsol table for every element here, an LDA one for Si,
    the functional without D3(BJ) parameters, and a fully relativistic one
    for NiO with spin-orbit coupling."""
    scalar = sssp_fixture_table_spec(
        tmp_path / "scalar",
        {
            "Al": 3.0,
            "Fe": 16.0,
            "Gd": 18.0,
            "Mo": 14.0,
            "N": 5.0,
            "Ni": 18.0,
            "O": 6.0,
            "Pt": 10.0,
            "S": 6.0,
            "Si": 4.0,
            "Ti": 12.0,
            "Zn": 20.0,
        },
    )
    lda_spec, lda_table = sssp_fixture_table_spec(
        tmp_path / "lda", {"Si": 4.0}, functional="LDA"
    )
    full = sssp_fixture_table_spec(
        tmp_path / "full", {"Ni": 18.0, "O": 6.0}, relativistic="full"
    )
    tables = (scalar, (lda_spec, dataclasses.replace(lda_table, default=False)), full)
    monkeypatch.setattr(
        "goldilocks_core.service._pseudo.load_tables",
        lambda *_args, **_kwargs: {table.id: table for _, table in tables},
    )
    installed = AssetStore(tmp_path / "store")
    for spec, table in tables:
        installed.install(spec, sssp_preparer(table))
    return installed


def _run(trigger: _Trigger, overrides: dict[str, object], store: AssetStore):
    """The check of ``trigger``'s task on its structure with ``overrides``,
    and the steps the task renders when the check passes."""
    task = "scf_single_point" if trigger.task == "scf" else trigger.task
    phases = TASK_PHASES[task]
    advice = phases.advise(
        trigger.structure(),
        hpc=load_hpc_profile("scarf"),
        overrides=build_overrides(overrides, task=task),
        store=store,
    )
    report = phases.check(advice)
    steps = phases.generate(advice, report) if report.ok else ()
    return report, steps


def _applied(overrides: dict[str, object], remedy: dict[str, object]):
    """``overrides`` patched with ``remedy``: a None value removes the key."""
    patched = {**overrides, **remedy}
    return {key: value for key, value in patched.items() if value is not None}


def _messages(report: CheckReport) -> list[str]:
    return [finding.message for finding in report.blocking]


def _holds_the_vacuum(trigger: _Trigger, steps) -> bool:
    """Whether the vc-relax ``steps`` render for ``trigger`` holds its vacuum
    fixed. Every trigger with vacuum is a slab with its vacuum along c, which
    QE's 2D constraints hold together with the z components of a and b (QE
    7.3 Modules/cell_base.f90:742-749 and :803-808); 'all' would relax it."""
    if trigger.task != "vc-relax" or not vacuum_axes(trigger.structure()):
        return True
    (step,) = steps
    written = re.search(r"cell_dofree\s*=\s*'([^']+)'", step.files["vc-relax.in"])
    return written is not None and written[1] in {"2Dxy", "2Dshape"}


def test_every_finding_with_remedies_has_a_trigger() -> None:
    assert set(_TRIGGERS) | _UNREACHABLE == {
        finding.code for finding in FINDING_CATALOGUE if finding.remedies
    }


def _each_remedy_makes_it_runnable(
    code: str, trigger: _Trigger, store: AssetStore
) -> None:
    """``trigger`` blocks with exactly one finding, of ``code``, and each of
    its remedies makes the request generate."""
    report, _ = _run(trigger, trigger.overrides, store)

    (finding,) = report.blocking
    assert finding.code == code
    assert INTERNAL_TEXT.findall(finding.message) == []
    assert finding.remedies
    for remedy in finding.remedies:
        patched, steps = _run(trigger, _applied(trigger.overrides, remedy), store)
        assert patched.ok, (remedy, _messages(patched))
        assert any(step.executable == "pw.x" for step in steps), remedy
        assert _holds_the_vacuum(trigger, steps), remedy


@pytest.mark.parametrize("code", list(_TRIGGERS))
def test_each_remedy_makes_the_request_runnable(code: str, store: AssetStore) -> None:
    _each_remedy_makes_it_runnable(code, _TRIGGERS[code], store)


@pytest.mark.parametrize("variant", list(_METALLICITY_VARIANTS))
def test_each_metallicity_remedy_makes_the_request_runnable(
    variant: str, store: AssetStore
) -> None:
    """Each remedy of the metallicity refusal, whichever the request makes it
    offer, resolves it."""
    _each_remedy_makes_it_runnable(
        "phonon.metallicity_unconfirmed", _METALLICITY_VARIANTS[variant], store
    )


@pytest.mark.parametrize("code", list(_PHONON_MOMENT_TRIGGERS))
def test_in_a_phonon_task_each_remedy_of_a_moment_refusal_makes_it_runnable(
    code: str, store: AssetStore
) -> None:
    _each_remedy_makes_it_runnable(code, _PHONON_MOMENT_TRIGGERS[code], store)


def test_the_odd_count_remedies_hold_where_spin_polarization_alone_fails(
    store: AssetStore,
) -> None:
    """The old advice, spin_polarized=true on its own, keeps fixed
    occupations, which a collinear run without a moment cannot use."""
    trigger = _TRIGGERS["occupations.fixed_needs_even_electron_count"]

    report, _ = _run(trigger, {**trigger.overrides, "spin_polarized": True}, store)

    assert [finding.code for finding in report.blocking] == [
        "occupations.fixed_needs_tot_magnetization"
    ]


def test_clearing_a_cartesian_mask_on_a_turned_slab_also_clears_the_2d_rule(
    store: AssetStore,
) -> None:
    """Under isolation=slab, cell_dofree=all fails the 2D-truncation rule;
    the remedy clears cell_dofree, and the slab's default '2Dxy' passes
    both rules."""
    trigger = _Trigger(
        "vc-relax", _turned_silicon_slab, {"cell_dofree": "z", "isolation": "slab"}
    )

    report, _ = _run(trigger, trigger.overrides, store)
    codes = [finding.code for finding in report.blocking]
    (cartesian,) = (
        finding
        for finding in report.blocking
        if finding.code == "relax.cartesian_cell_dofree_on_rotated_cell"
    )
    with_all, _ = _run(trigger, {**trigger.overrides, "cell_dofree": "all"}, store)
    cleared, steps = _run(
        trigger, _applied(trigger.overrides, *cartesian.remedies), store
    )

    assert codes == [
        "relax.slab_vc_relax_needs_2d_cell_dofree",
        "relax.cartesian_cell_dofree_on_rotated_cell",
    ]
    assert [finding.code for finding in with_all.blocking] == [
        "relax.slab_vc_relax_needs_2d_cell_dofree"
    ]
    assert cleared.ok, _messages(cleared)
    assert "cell_dofree      = '2Dxy'" in steps[0].files["vc-relax.in"]


@pytest.mark.parametrize(
    ("structure", "overrides"),
    [
        (_diamond_silicon, {"cell_dofree": "all"}),
        (silicon_dimer_in_a_box, {}),
        (lambda: with_vacuum_along(_silicon_slab(18), "a"), {"cell_dofree": "all"}),
    ],
    ids=["bulk", "box", "slab-with-its-vacuum-along-a"],
)
def test_isolation_slab_outside_a_slab_in_the_xy_frame_names_only_the_boundary(
    structure: Callable[[], Structure],
    overrides: dict[str, object],
    store: AssetStore,
) -> None:
    """The 2D cell constraint's remedies used to be offered here too: '2Dxy'
    fails the 2D-frame rule on each of these cells, and isolation=periodic
    with cell_dofree unset blocks the slab and writes 'all' for the box,
    which relaxes its vacuum; on the bulk cell it repeated the boundary
    finding's remedy."""
    trigger = _Trigger("vc-relax", structure, {"isolation": "slab", **overrides})

    report, _ = _run(trigger, trigger.overrides, store)

    assert [finding.code for finding in report.blocking] == [
        "boundary.slab_unsuited_to_2d_truncation"
    ]


def test_the_2d_frame_remedy_under_isolation_slab_raises_no_new_finding(
    store: AssetStore,
) -> None:
    """On a bulk cell out of the xy frame, the 2D-frame rule's cell_dofree=all
    used to raise the 2D cell constraint's finding, whose cell_dofree=2Dxy
    raised the 2D-frame rule again."""
    trigger = _Trigger(
        "vc-relax", _diamond_silicon, {"isolation": "slab", "cell_dofree": "2Dxy"}
    )

    report, _ = _run(trigger, trigger.overrides, store)
    (frame,) = (
        finding
        for finding in report.blocking
        if finding.code == "relax.two_d_cell_dofree_needs_xy_frame"
    )
    remedied, _ = _run(trigger, _applied(trigger.overrides, *frame.remedies), store)

    assert [finding.code for finding in report.blocking] == [
        "boundary.slab_unsuited_to_2d_truncation",
        "relax.two_d_cell_dofree_needs_xy_frame",
    ]
    assert [finding.code for finding in remedied.blocking] == [
        "boundary.slab_unsuited_to_2d_truncation"
    ]


def test_a_slab_without_room_for_the_truncation_keeps_the_2d_constraint_remedies(
    store: AssetStore,
) -> None:
    """The Si(001) slab in its 27.16 A cell is in the xy frame but too thin in
    vacuum for the 2D truncation: its default is '2Dxy', so isolation=periodic
    with cell_dofree unset resolves both findings and holds the vacuum."""
    trigger = _Trigger(
        "vc-relax", _silicon_slab, {"isolation": "slab", "cell_dofree": "all"}
    )

    report, _ = _run(trigger, trigger.overrides, store)
    constraint = report.blocking[-1]
    remedied, steps = _run(
        trigger, _applied(trigger.overrides, constraint.remedies[1]), store
    )

    assert [finding.code for finding in report.blocking] == [
        "boundary.slab_unsuited_to_2d_truncation",
        "relax.slab_vc_relax_needs_2d_cell_dofree",
    ]
    assert constraint.remedies[1] == {"isolation": "periodic", "cell_dofree": None}
    assert remedied.ok, _messages(remedied)
    assert "cell_dofree      = '2Dxy'" in steps[0].files["vc-relax.in"]


def _silicon_chain() -> Structure:
    """A linear silicon chain along c (Si-Si 2.3 A), 12 A from its images
    along a and b: a wire whose period, c, lies along z."""
    return Structure(
        Lattice.tetragonal(12.0, 4.6), ["Si", "Si"], [[0.5, 0.5, 0], [0.5, 0.5, 0.5]]
    )


@pytest.mark.parametrize("period", ["a", "b", "c"])
def test_the_constraint_named_for_a_wire_holds_its_vacuum_in_any_orientation(
    period: str, store: AssetStore
) -> None:
    """The chain's period permuted onto a, b or c still lies along z, where
    'x' or 'y', which the relax advisor named for a period a or b, would move
    a component of it that is zero. A vc-relax without cell_dofree and one
    with '2Dxy' are refused naming the same constraint: QE's 'epitaxial_' with
    the two vacuum vectors, which it holds fixed while it moves every component
    of the third (QE 7.3 Modules/cell_base.f90:825-842). That constraint
    generates."""
    trigger = _Trigger(
        "vc-relax", lambda: with_vacuum_along(_silicon_chain(), period), {}
    )

    unset, _ = _run(trigger, {}, store)
    framed, _ = _run(trigger, {"cell_dofree": "2Dxy"}, store)
    (constraint,) = {
        re.search(r"cell_dofree='?(\w+)'? holds", finding.message)[1]
        for finding in (*unset.blocking, *framed.blocking)
    }
    remedied, steps = _run(trigger, {"cell_dofree": constraint}, store)

    assert [finding.code for finding in unset.blocking] == ["advice.blocked"]
    assert [finding.code for finding in framed.blocking] == [
        "relax.two_d_cell_dofree_needs_xy_frame"
    ]
    assert constraint == f"epitaxial_{''.join(vacuum_axes(trigger.structure()))}"
    assert remedied.ok, _messages(remedied)
    assert f"cell_dofree      = '{constraint}'" in steps[0].files["vc-relax.in"]


@pytest.mark.parametrize(
    ("trigger", "named"),
    [
        (
            _Trigger("scf", _diamond_silicon, {"pseudo_table_id": "does-not-exist"}),
            "does-not-exist",
        ),
        (
            _Trigger(
                "scf",
                _example("Fe_bcc.cif"),
                {"starting_magnetization": {"Fe9": 0.5}},
            ),
            "unknown key(s) Fe9;",
        ),
    ],
    ids=["unknown-table", "unknown-site-label"],
)
def test_a_blocked_chain_names_its_root_cause_without_remedies(
    trigger: _Trigger, named: str, store: AssetStore
) -> None:
    """A starting_magnetization key that names no site read "unknown key(s)
    ['Fe9']", the repr of a list."""
    report, _ = _run(trigger, trigger.overrides, store)

    (finding,) = report.blocking
    assert finding.code == "advice.blocked"
    assert named in finding.message
    assert (finding.fields, finding.remedies) == ((), ())
    assert INTERNAL_TEXT.findall(finding.message) == []


@pytest.mark.parametrize(("task", "step"), [("dos", "nscf"), ("band", "bands")])
def test_a_band_count_too_low_for_both_pw_x_steps_is_refused_once(
    task: str, step: str, store: AssetStore
) -> None:
    """A flat nbnd sets a dos or band task's scf and later pw.x step alike,
    and its refusal came back twice, worded for each step. It is refused
    once, in the scf step's words, where pw.x stops; set on the later step
    alone, it is refused in that step's."""
    trigger = _Trigger(task, _diamond_silicon, {"nbnd": 2})

    flat, _ = _run(trigger, trigger.overrides, store)
    later, _ = _run(trigger, {f"steps.{step}.nbnd": 2}, store)

    (scf_finding,) = flat.blocking
    (step_finding,) = later.blocking
    assert "pw.x stops in setup with 'too few bands'" in scf_finding.message
    assert f"so this {step} step would leave occupied bands out" in (
        step_finding.message
    )


@pytest.mark.parametrize("name", ["Si.cif", "Fe_bcc.cif", "Pt_fcc.cif"])
def test_the_warnings_of_a_real_run_read_as_user_text(
    name: str, store: AssetStore
) -> None:
    """A walltime left unset requests the partition's ceiling, and the
    warning names the partition: it read "partition 'scarf''s ceiling"."""
    advice = advise(_example(name)(), hpc=load_hpc_profile("scarf"), store=store)

    warnings = advice.warnings()
    walltime = [w for w in warnings if w["code"] == "job.walltime_defaulted"]

    assert [INTERNAL_TEXT.findall(w["message"]) for w in warnings] == [
        [] for _ in warnings
    ]
    assert walltime
    assert walltime[0]["message"].startswith(
        "walltime not specified; requesting the ceiling of partition scarf (168h)."
    )
