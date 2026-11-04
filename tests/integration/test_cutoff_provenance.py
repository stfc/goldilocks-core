"""#180: a density cutoff Goldilocks derives is published as derived.

PseudoDojo publishes only wavefunction cutoff hints; its tables' density
cutoff is charge_density_dual x the resolved ecutwfc, derived by the cutoffs
advisor, which says so with ``cutoffs.ecutrho_derived_from_dual``. SSSP
publishes both cutoffs, so its record carries no such notice. The
pseudopotentials record shows what each provider published: PseudoDojo's
hints and no density cutoff, SSSP's two cutoffs.
"""

from __future__ import annotations

from typing import Any

import pytest
from pymatgen.core import Lattice, Structure
from support import (
    REAL_ASSET_ROOT,
    dojo_fixture_table_spec,
    mc3d_42058_silicon,
    sssp_fixture_table_spec,
)

from goldilocks_core.assets.pseudopotentials.importers import (
    pseudodojo_preparer,
    sssp_preparer,
)
from goldilocks_core.assets.pseudopotentials.registry import load_tables
from goldilocks_core.assets.store import AssetStore
from goldilocks_core.server import _handlers
from goldilocks_core.server.documents import ComputeRequestDocument

pytestmark = pytest.mark.integration

_DERIVED = "cutoffs.ecutrho_derived_from_dual"


def _explain(structure: Structure, **overrides: Any) -> dict[str, Any]:
    document = ComputeRequestDocument(
        structure_content=structure.to(fmt="cif"), hpc="scarf", overrides=overrides
    )
    return _handlers.explain(document)


def _serve_only(table, monkeypatch) -> None:
    monkeypatch.setattr(
        "goldilocks_core.service._pseudo.load_tables",
        lambda *_args, **_kwargs: {table.id: table},
    )


@pytest.fixture
def dojo_table(tmp_path, monkeypatch) -> None:
    """The offline PseudoDojo-shaped Si table, installed into the test's
    asset root and the only table selection can pick."""
    spec, table = dojo_fixture_table_spec(tmp_path / "dojo-sources")
    AssetStore().install(spec, pseudodojo_preparer(table))
    _serve_only(table, monkeypatch)


@pytest.fixture
def sssp_table(tmp_path, monkeypatch) -> None:
    spec, table = sssp_fixture_table_spec(tmp_path / "sssp-sources")
    AssetStore().install(spec, sssp_preparer(table))
    _serve_only(table, monkeypatch)


def test_a_pseudodojo_density_cutoff_is_published_as_derived(dojo_table) -> None:
    explained = _explain(mc3d_42058_silicon())

    record = explained["records"]["cutoffs"]
    assert record["source"] == "heuristic"
    assert (record["value"]["ecutwfc_ry"], record["value"]["ecutrho_ry"]) == (
        40.0,
        160.0,
    )
    (notice,) = record["value"]["warnings"]
    assert notice["code"] == _DERIVED
    assert notice["message"] == (
        "ecutrho derived as charge_density_dual x ecutwfc = 4 x 40 = 160 Ry: "
        "table pseudodojo-fixture publishes no density cutoff for Si"
    )
    assert [
        warning["record"]
        for warning in explained["warnings"]
        if warning["code"] == _DERIVED
    ] == ["cutoffs"]
    (pseudo,) = explained["records"]["pseudopotentials"]["value"]
    assert pseudo["cutoffs"] == {"ecutwfc_ry": 40.0, "ecutrho_ry": None}
    assert pseudo["cutoff_hints"] == {"low": 20.0, "normal": 30.0, "high": 40.0}


def test_a_human_ecutwfc_sets_the_derived_density_cutoff(dojo_table) -> None:
    record = _explain(mc3d_42058_silicon(), ecutwfc_ry=60.0)["records"]["cutoffs"]

    assert record["source"] == "human"
    assert (record["value"]["ecutwfc_ry"], record["value"]["ecutrho_ry"]) == (
        60.0,
        240.0,
    )
    assert [notice["code"] for notice in record["value"]["warnings"]] == [_DERIVED]


def test_sssp_published_cutoffs_carry_no_derivation_notice(sssp_table) -> None:
    explained = _explain(mc3d_42058_silicon())

    record = explained["records"]["cutoffs"]
    assert (record["value"]["ecutwfc_ry"], record["value"]["ecutrho_ry"]) == (
        30.0,
        120.0,
    )
    assert record["value"]["warnings"] == []
    assert _DERIVED not in {warning["code"] for warning in explained["warnings"]}
    (pseudo,) = explained["records"]["pseudopotentials"]["value"]
    assert pseudo["cutoffs"] == {"ecutwfc_ry": 30.0, "ecutrho_ry": 120.0}
    assert pseudo["cutoff_hints"] is None


def _nickel_oxide() -> Structure:
    """Rock-salt NiO, MC3D mc3d-29856: the 2-atom primitive cell."""
    return Structure(
        Lattice.from_parameters(*(2.89336877724759,) * 3, *(60.00000000000001,) * 3),
        ["Ni", "O"],
        [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
    )


def _require_installed(table_id: str) -> None:
    table = load_tables()[table_id]
    if AssetStore(REAL_ASSET_ROOT).status_spec(table.asset) != "installed":
        pytest.skip(f"{table_id} is not installed at {REAL_ASSET_ROOT}")


def test_nio_on_the_installed_pseudodojo_table_reports_a_derived_ecutrho(
    real_assets,
) -> None:
    """The issue's reproduction: tables installed before #180 store
    ecutrho_ry = 4 x ecutwfc_ry and need no re-installation."""
    explained = _explain(_nickel_oxide())

    assert explained["records"]["pseudo_table"]["value"]["id"] == (
        "pseudodojo-pbesol-efficiency-sr"
    )
    record = explained["records"]["cutoffs"]["value"]
    assert (record["ecutwfc_ry"], record["ecutrho_ry"]) == (110.0, 440.0)
    (notice,) = record["warnings"]
    assert notice["message"] == (
        "ecutrho derived as charge_density_dual x ecutwfc = 4 x 110 = 440 Ry: "
        "table pseudodojo-pbesol-efficiency-sr publishes no density cutoff for "
        "Ni, O"
    )
    nickel = explained["records"]["pseudopotentials"]["value"][0]
    assert nickel["element"] == "Ni"
    assert nickel["cutoffs"] == {"ecutwfc_ry": 110.0, "ecutrho_ry": None}
    assert nickel["cutoff_hints"] == {"low": 90.0, "normal": 98.0, "high": 110.0}


def test_nio_on_the_installed_sssp_table_reports_published_cutoffs(
    real_assets,
) -> None:
    _require_installed("sssp-pbesol-efficiency-sr")

    explained = _explain(_nickel_oxide(), pseudo_table_id="sssp-pbesol-efficiency-sr")

    record = explained["records"]["cutoffs"]["value"]
    assert (record["ecutwfc_ry"], record["ecutrho_ry"]) == (50.0, 400.0)
    assert record["warnings"] == []
