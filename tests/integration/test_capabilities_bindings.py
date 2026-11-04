"""Every setting's ``resolved_in`` and every response's ``layout``, checked
against real advice (#187).

The Workbench reads a setting's resolved value and tier only through the
record and path ``/capabilities`` declares for it, and places each record
by the ``layout`` of the response it came in. A declaration naming a record
or a field that no advice publishes would show nothing, silently, and a
record missing from ``layout`` would be shown nowhere. These advise bcc Fe
(the bundled example) for every task, and once with spin-orbit coupling,
which records a moment direction, then walk every declaration through the
published records. They run on synthetic SSSP-shaped tables, a scalar one
and the fully relativistic one spin-orbit coupling selects, so they run in
CI.
"""

from __future__ import annotations

from typing import Any

import pytest
from support import sssp_fixture_table_spec

from goldilocks_core.assets.pseudopotentials.importers import sssp_preparer
from goldilocks_core.assets.store import AssetStore
from goldilocks_core.capabilities import capabilities
from goldilocks_core.examples.structures import structure
from goldilocks_core.server import _handlers
from goldilocks_core.server.documents import ComputeRequestDocument

pytestmark = pytest.mark.integration

_CASES: tuple[tuple[str, dict[str, object]], ...] = (
    ("scf_single_point", {}),
    ("dos", {}),
    ("band", {}),
    ("relax", {}),
    ("vc-relax", {}),
    ("phonon", {}),
    ("relax-phonon", {}),
    ("vc-relax-phonon", {}),
    ("scf_single_point", {"spin_orbit_coupling": True}),
)

_PHONON_FIRST_STEPS = {
    "phonon": "scf",
    "relax-phonon": "relax",
    "vc-relax-phonon": "vc-relax",
}
"""Each phonon task's first pw.x step."""

_MISSING = object()
_CUT = object()


@pytest.fixture
def tables(tmp_path, monkeypatch) -> None:
    """The scalar and fully relativistic tables for Fe and Si, installed at
    the default asset root, which ``/explain`` reads."""
    z_valences = {"Fe": 16.0, "Si": 4.0}
    specs = (
        sssp_fixture_table_spec(tmp_path / "scalar", z_valences),
        sssp_fixture_table_spec(tmp_path / "full", z_valences, relativistic="full"),
    )
    monkeypatch.setattr(
        "goldilocks_core.service._pseudo.load_tables",
        lambda *_args, **_kwargs: {table.id: table for _, table in specs},
    )
    store = AssetStore()
    for spec, table in specs:
        store.install(spec, sssp_preparer(table))


def _explain(name: str, task: str, overrides: dict[str, object]) -> dict[str, Any]:
    """The ``/explain`` response for the bundled example ``name``."""
    return _handlers.explain(
        ComputeRequestDocument(
            structure_content=structure(name).read_text(),
            structure_name=name,
            hpc="scarf",
            task=task,
            overrides=overrides,
        )
    )


@pytest.fixture
def explained(tables) -> list[tuple[str, dict[str, Any]]]:
    """Each case's task and ``/explain`` response for bcc Fe."""
    return [
        (task, _explain("Fe_bcc.cif", task, overrides)) for task, overrides in _CASES
    ]


def _walk(value: object, path: list[str]) -> object:
    """The value at ``path`` in ``value``, which may be ``None``:
    ``_MISSING`` where a key is absent, ``_CUT`` where a ``None`` comes
    before the path's last key (``moment_direction`` without spin-orbit
    coupling)."""
    for key in path:
        if value is None:
            return _CUT
        if not isinstance(value, dict) or key not in value:
            return _MISSING
        value = value[key]
    return value


def test_every_setting_resolves_in_a_published_record_and_field(
    explained,
) -> None:
    """A setting's record is published for every task the setting applies
    to; its path names keys of that record's value in every response that
    resolves it, all the way down in at least one."""
    for setting in capabilities()["settings"]:
        resolved_in = setting["resolved_in"]
        applicable = [
            (task, response["records"])
            for task, response in explained
            if task in setting["tasks"]
        ]
        assert applicable, setting["key"]
        for task, records in applicable:
            assert resolved_in["record"] in records, (task, setting["key"])
        if resolved_in["path"] is None:
            continue
        values = [
            _walk(records[resolved_in["record"]]["value"], resolved_in["path"])
            for _task, records in applicable
            if records[resolved_in["record"]]["status"] == "resolved"
        ]
        assert values, setting["key"]
        assert _MISSING not in values, setting["key"]
        assert any(value is not _CUT for value in values), setting["key"]


def test_each_layout_places_every_record_once_by_tier_and_step(
    explained,
) -> None:
    """The analysis tier holds the structure-only records, the system tier
    what every step shares, then each step of the task in run order: the
    task's one job with its first step, a dos task's nscf decisions under
    their nscf_ names, a band task's bands-step path as k_path and its other
    decisions under their bands_ names (bands.x has none), a relaxation's own
    record with its step, and a phonon task's first step with its relax
    record and FFT grid, then its ph, q2r and phonon_dos steps and its
    dispersion step's path as k_path (d3hess.x has none)."""
    facts = {fact["key"] for fact in capabilities()["facts"]}
    for task, response in explained:
        layout = response["layout"]
        steps = {step["name"]: step["records"] for step in layout["steps"]}
        names = [
            *layout["analysis"],
            *layout["system"],
            *(name for records in steps.values() for name in records),
        ]
        assert len(names) == len(set(names)), task
        assert set(names) == set(response["records"]), task
        assert set(layout["analysis"]) == facts | {
            "composition",
            "geometry",
            "symmetry",
        }
        assert {"magnetic", "pseudopotentials", "symmetry_eff"} <= set(layout["system"])
        if task == "dos":
            assert list(steps) == ["scf", "nscf", "dos"]
            assert steps["dos"] == ["dos"]
            assert steps["nscf"]
            assert all(name.startswith("nscf_") for name in steps["nscf"])
        elif task == "band":
            assert list(steps) == ["scf", "bands"]
            assert steps["bands"] == [
                "bands_occupations",
                "k_path",
                "bands_nbnd",
                "bands_convergence",
                "bands_parallelisation",
            ]
        elif task in ("relax", "vc-relax"):
            assert list(steps) == [task]
            assert "relax" in steps[task]
        elif task in _PHONON_FIRST_STEPS:
            first_step = _PHONON_FIRST_STEPS[task]
            assert list(steps) == [
                first_step,
                "ph",
                "q2r",
                "phonon_dos",
                "dispersion",
            ]
            assert steps[first_step][-1] == "fft_grid"
            assert ("relax" in steps[first_step]) is (first_step != "scf")
            assert steps["ph"] == ["q_sampling", "phonon"]
            assert (steps["q2r"], steps["phonon_dos"]) == (["q2r"], ["phonon_dos"])
            assert steps["dispersion"] == ["k_path"]
        else:
            assert list(steps) == ["scf"]
        assert "job" in next(iter(steps.values())), task


def test_a_run_without_spin_polarization_shows_no_magnetic_ordering(
    tables,
) -> None:
    """A run without spin polarization applies no ordering, so the path
    magnetic_ordering resolves in leads to no value and the record gives it
    no tier: the Workbench showed "fm", a value that asks for spin
    polarization, captioned "Heuristic default" next to spin polarized off."""
    (setting,) = (
        setting
        for setting in capabilities()["settings"]
        if setting["key"] == "magnetic_ordering"
    )
    resolved_in = setting["resolved_in"]

    record = _explain("Si.cif", "scf_single_point", {})["records"][
        resolved_in["record"]
    ]

    assert record["value"]["spin_polarized"] is False
    assert _walk(record["value"], resolved_in["path"]) is None
    assert "magnetic_ordering" not in record["field_sources"]
