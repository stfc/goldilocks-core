"""Whenever ``check()`` passes, ``generate()`` renders the input (#135).

The gate and the writers must agree: a request the gate accepts must
never fail inside a writer. This runs ``advise``/``check``/``generate``
end to end over a matrix of correlated compounds on a synthetic
SSSP-shaped table (so it runs in CI) and asserts, for every scenario and
task, that ``check`` is ok, that generation succeeds, and that every
``pw.x`` input carries exactly the expected HUBBARD lines under the
expected projectors (or no Hubbard card at all). Pinning the card means a
regression that drops or invents a U value fails here, not only one that
raises. +U-specific convergence
output follows the same decision (#166): ``mixing_fixed_ns`` appears only
as the user set it, and a nonzero value carries the frozen-occupation
warning exactly when a card is rendered.

The phonon tasks run the scenarios their own gate accepts, where a U is
written on atomic projectors, the only ones ph.x takes, and the first step
runs on fixed occupations, which a phonon task needs for a compound that is
not all-metallic unless the user confirms a metal: their first step's pw.x
input carries the same card.

A request no input can express is refused by ``check`` itself, where
``/explain`` shows it, and never reaches a writer: spin-orbit coupling
with a ``tot_magnetization``, which pw.x accepts only with nspin=2 (#146),
and an explicit ``occupations=fixed`` on a collinear spin-polarized run with
no moment to pin (#138). A default never is: a spin-polarized non-metal
without a known moment gets smearing. Spin-orbit scenarios select a second,
fully relativistic table.

Add a scenario here whenever another rule can let ``check`` pass while a
writer refuses.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import pytest
from pymatgen.core import Lattice, Structure
from support import sssp_fixture_table_spec

from goldilocks_core.assets.pseudopotentials.importers import sssp_preparer
from goldilocks_core.assets.store import AssetStore
from goldilocks_core.inputs.hpc import Hardware, HpcProfile, Partition
from goldilocks_core.service import TASK_PHASES, advise, check
from goldilocks_core.set_overrides import build_overrides

_Z_VALENCES = {
    "Ce": 12.0,
    "Cf": 20.0,
    "Cr": 14.0,
    "Cu": 19.0,
    "Eu": 17.0,
    "La": 11.0,
    "Lu": 25.0,
    "N": 5.0,
    "Ni": 18.0,
    "O": 6.0,
    "Th": 12.0,
    "Ti": 12.0,
    "U": 14.0,
    "Zn": 20.0,
    "Zr": 12.0,
}
_FULLY_RELATIVISTIC_Z_VALENCES = {"Fe": 16.0, "Pt": 16.0}


def _rock_salt(cation: str, a: float, anion: str = "O") -> Structure:
    return Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(a), [cation, anion], [[0, 0, 0], [0.5, 0.5, 0.5]]
    ).get_primitive_structure()


def _fluorite(cation: str, a: float) -> Structure:
    return Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(a), [cation, "O"], [[0, 0, 0], [0.25, 0.25, 0.25]]
    ).get_primitive_structure()


def _perovskite(a_site: str, b_site: str, a: float) -> Structure:
    return Structure.from_spacegroup(
        "Pm-3m",
        Lattice.cubic(a),
        [a_site, b_site, "O"],
        [[0, 0, 0], [0.5, 0.5, 0.5], [0.5, 0.5, 0]],
    )


def _rutile_tio2() -> Structure:
    return Structure.from_spacegroup(
        "P4_2/mnm",
        Lattice.tetragonal(4.594, 2.959),
        ["Ti", "O"],
        [[0, 0, 0], [0.305, 0.305, 0]],
    )


def _wurtzite_zno() -> Structure:
    return Structure.from_spacegroup(
        "P6_3mc",
        Lattice.hexagonal(3.25, 5.207),
        ["Zn", "O"],
        [[1 / 3, 2 / 3, 0], [1 / 3, 2 / 3, 0.382]],
    )


def _l10_fept() -> Structure:
    """L1_0 FePt (MC3D mc3d-49510)."""
    return Structure.from_spacegroup(
        "P4/mmm",
        Lattice.tetragonal(2.6855, 3.7210),
        ["Fe", "Pt"],
        [[0, 0, 0], [0.5, 0.5, 0.5]],
    )


@dataclass(frozen=True)
class _Scenario:
    structure: Callable[[], Structure]
    hubbard: tuple[str, ...]
    """The exact ``U`` lines of the HUBBARD card; empty means no card."""
    overrides: dict[str, object] = field(default_factory=dict)
    projectors: str = "ortho-atomic"
    """The projectors the HUBBARD card's header names."""


_SCENARIOS = {
    # No U by convention: plain DFT, no card.
    "TiO2": _Scenario(_rutile_tio2, ()),
    "ZnO": _Scenario(_wurtzite_zno, ()),
    "ZrO2": _Scenario(lambda: _fluorite("Zr", 5.07), ()),
    "ThO2": _Scenario(lambda: _fluorite("Th", 5.60), ()),
    "LuO": _Scenario(lambda: _rock_salt("Lu", 4.80), ()),
    # No published U: plain DFT (and a warning), no card.
    "CfO2": _Scenario(lambda: _fluorite("Cf", 5.31), ()),
    # Built-in table.
    "NiO": _Scenario(lambda: _rock_salt("Ni", 4.17), ("U  Ni-3d  6.2",)),
    "CeO2": _Scenario(lambda: _fluorite("Ce", 5.41), ("U  Ce-4f  5",)),
    "EuO": _Scenario(lambda: _rock_salt("Eu", 5.14), ("U  Eu-4f  3",)),
    "UO2": _Scenario(lambda: _fluorite("U", 5.47), ("U  U-5f  4",)),
    # La gets no U, so only Cu does.
    "LaCuO3": _Scenario(lambda: _perovskite("La", "Cu", 3.82), ("U  Cu-3d  4",)),
    # A spin-polarized non-metal without a known moment runs on smearing
    # (#138).
    "NiO is_metal non_metal": _Scenario(
        lambda: _rock_salt("Ni", 4.17), ("U  Ni-3d  6.2",), {"is_metal": "non_metal"}
    ),
    # Overrides.
    "TiO2 u_by_element": _Scenario(
        _rutile_tio2, ("U  Ti-3d  4",), {"u_by_element": {"Ti": 4.0}}
    ),
    "CeCrO3 u_by_element": _Scenario(
        lambda: _perovskite("Ce", "Cr", 3.88),
        ("U  Ce-4f  4.5", "U  Cr-3d  3.5"),
        {"u_by_element": {"Cr": 3.5, "Ce": 4.5}},
    ),
    "NiO u_by_element absent": _Scenario(
        lambda: _rock_salt("Ni", 4.17), (), {"u_by_element": {"Fe": 5.0}}
    ),
    "CeO2 no +U": _Scenario(
        lambda: _fluorite("Ce", 5.41), (), {"hubbard_needs_correlation": False}
    ),
    # The projectors ph.x requires for DFPT+U, in every pw.x input.
    "NiO hubbard_projectors atomic": _Scenario(
        lambda: _rock_salt("Ni", 4.17),
        ("U  Ni-3d  6.2",),
        {"hubbard_projectors": "atomic"},
        projectors="atomic",
    ),
    # On fixed occupations, as the phonon tasks need a compound that is not a
    # confirmed metal: TiO2 as a non-metal, ferromagnetic NiO with its moment.
    "TiO2 is_metal non_metal": _Scenario(_rutile_tio2, (), {"is_metal": "non_metal"}),
    "NiO hubbard_projectors atomic, is_metal non_metal, tot_magnetization": _Scenario(
        lambda: _rock_salt("Ni", 4.17),
        ("U  Ni-3d  6.2",),
        {
            "hubbard_projectors": "atomic",
            "is_metal": "non_metal",
            "tot_magnetization": 2,
        },
        projectors="atomic",
    ),
    # A user mixing_fixed_ns, flagged only where a U is applied, whatever
    # needs_correlation says (#166): true for ThO2, false for the nitride UN.
    "ThO2 no +U, mixing_fixed_ns": _Scenario(
        lambda: _fluorite("Th", 5.60),
        (),
        {"hubbard_needs_correlation": False, "mixing_fixed_ns": 50},
    ),
    "UN u_by_element, mixing_fixed_ns": _Scenario(
        lambda: _rock_salt("U", 4.89, "N"),
        ("U  U-5f  4",),
        {"u_by_element": {"U": 4.0}, "mixing_fixed_ns": 50},
    ),
    # An explicit spin_polarized=false ignores tot_magnetization, so the
    # noncollinear input carries none (#146).
    "FePt spin_orbit_coupling, spin_polarized false, tot_magnetization": _Scenario(
        _l10_fept,
        (),
        {
            "spin_orbit_coupling": True,
            "spin_polarized": False,
            "tot_magnetization": 3.0,
        },
    ),
}


@dataclass(frozen=True)
class _Refusal:
    structure: Callable[[], Structure]
    overrides: dict[str, object]
    reason: str
    """A phrase of the gate's blocking reason."""


_REFUSALS = {
    # pw.x takes tot_magnetization only with nspin=2, and spin-orbit
    # coupling runs noncollinear (#146).
    "FePt spin_orbit_coupling, tot_magnetization": _Refusal(
        _l10_fept,
        {"spin_orbit_coupling": True, "tot_magnetization": 3.0},
        "tot_magnetization",
    ),
    # fixed occupations on nspin=2 need an integer tot_magnetization, which
    # nothing gives a ferromagnetic start (#138).
    "NiO occupations fixed": _Refusal(
        lambda: _rock_salt("Ni", 4.17),
        {"occupations": "fixed"},
        "integer tot_magnetization",
    ),
}

_MULTI_TASK_SCENARIOS = (
    "NiO",
    "LaCuO3",
    "TiO2",
    "NiO is_metal non_metal",
    "NiO hubbard_projectors atomic",
)

_PHONON_SCENARIOS = (
    "TiO2 is_metal non_metal",
    "NiO hubbard_projectors atomic, is_metal non_metal, tot_magnetization",
)
"""The scenarios the phonon tasks' gate accepts: no U, or a U on atomic
projectors, on fixed occupations."""

_FROZEN_NS = "convergence.mixing_fixed_ns_freezes_hubbard_occupations"


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


def _generate(task: str, scenario: _Scenario, store: AssetStore):
    """``task``'s advice for ``scenario`` and the steps its row of
    ``TASK_PHASES`` renders, after asserting the check passes."""
    task = "scf_single_point" if task == "scf" else task
    phases = TASK_PHASES[task]
    advice = phases.advise(
        scenario.structure(),
        hpc=_hpc(),
        overrides=build_overrides(scenario.overrides, task=task),
        store=store,
    )
    report = phases.check(advice)
    assert report.ok, [finding.message for finding in report.blocking]
    return advice, phases.generate(advice, report)


def _hubbard_lines(content: str, projectors: str) -> tuple[str, ...]:
    """The U lines under the HUBBARD card's header, which must name
    ``projectors``."""
    lines = content.splitlines()
    start = lines.index(f"HUBBARD ({projectors})") + 1
    card = []
    for line in lines[start:]:
        if not line.strip():
            break
        card.append(line.strip())
    return tuple(card)


_CASES = (
    [pytest.param("scf", name, id=f"scf-{name}") for name in _SCENARIOS]
    + [
        pytest.param(task, name, id=f"{task}-{name}")
        for task in ("relax", "vc-relax", "dos", "band")
        for name in _MULTI_TASK_SCENARIOS
    ]
    + [
        pytest.param(task, name, id=f"{task}-{name}")
        for task in ("phonon", "relax-phonon", "vc-relax-phonon")
        for name in _PHONON_SCENARIOS
    ]
)


@pytest.mark.parametrize(("task", "name"), _CASES)
def test_check_ok_implies_generate_renders_the_expected_hubbard_card(
    task: str, name: str, store: AssetStore
) -> None:
    scenario = _SCENARIOS[name]
    fixed_ns = scenario.overrides.get("mixing_fixed_ns")

    advice, steps = _generate(task, scenario, store)

    pw_inputs = [
        content
        for step in steps
        if step.executable == "pw.x"
        for content in step.files.values()
    ]
    assert pw_inputs
    for content in pw_inputs:
        assert ("mixing_fixed_ns" in content) is (fixed_ns is not None)
        if scenario.hubbard:
            assert _hubbard_lines(content, scenario.projectors) == scenario.hubbard
        else:
            assert "hubbard" not in content.lower()
    codes = {warning["code"] for warning in advice.warnings()}
    assert (_FROZEN_NS in codes) is bool(scenario.hubbard and fixed_ns)


@pytest.mark.parametrize("name", list(_REFUSALS))
def test_check_refuses_a_request_no_input_can_express(
    name: str, store: AssetStore
) -> None:
    refusal = _REFUSALS[name]
    advice = advise(
        refusal.structure(),
        hpc=_hpc(),
        overrides=build_overrides(refusal.overrides, task="scf_single_point"),
        store=store,
    )

    report = check(advice)

    messages = [finding.message for finding in report.blocking]
    assert any(refusal.reason in message for message in messages), messages
