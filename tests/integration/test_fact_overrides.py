"""Every overridable fact changes a generated input (#186).

/capabilities publishes a fact as overridable exactly when its key takes a
human value (``capabilities._facts``), and a human value only belongs there
when a decision reads it. ``needs_soc`` was overridable while only the
``magnetic.soc_suggested`` notice read it: ``--set needs_soc=true`` left every
generated file byte for byte the same, and the Workbench offered an On/Off
select that did nothing. ``advise``/``check``/``generate`` run end to end on a
synthetic SSSP-shaped table covering the bundled example structures, so this
runs in CI.
"""

from __future__ import annotations

import pytest
from pymatgen.core import Structure
from support import sssp_fixture_table_spec

from goldilocks_core.assets.pseudopotentials.importers import sssp_preparer
from goldilocks_core.assets.store import AssetStore
from goldilocks_core.capabilities import Fact, capabilities
from goldilocks_core.examples.structures import available_structures, structure
from goldilocks_core.inputs.hpc import load_hpc_profile
from goldilocks_core.service import advise, check, generate
from goldilocks_core.set_overrides import build_overrides

pytestmark = pytest.mark.integration

_Z_VALENCES = {"Fe": 16.0, "Pt": 16.0, "Si": 4.0}
"""A UPF valence for every element of the bundled example structures."""


@pytest.fixture
def store(tmp_path, monkeypatch) -> AssetStore:
    spec, registry_table = sssp_fixture_table_spec(tmp_path / "sources", _Z_VALENCES)
    monkeypatch.setattr(
        "goldilocks_core.service._pseudo.load_tables",
        lambda *_args, **_kwargs: {registry_table.id: registry_table},
    )
    store = AssetStore(tmp_path / "store")
    store.install(spec, sssp_preparer(registry_table))
    return store


def _advertised_values(fact: Fact) -> list[object]:
    """Every value /capabilities tells a client it may send for ``fact``."""
    if fact["type"] == "boolean":
        return [True, False]
    return list(fact["values"] or [])


def _inputs(
    store: AssetStore, cell: Structure, overrides: dict[str, object]
) -> dict[str, str] | None:
    """The input files of a single-point SCF on ``cell`` under ``overrides``,
    or None when ``check`` refuses the request."""
    advice = advise(
        cell,
        hpc=load_hpc_profile("scarf"),
        overrides=build_overrides(overrides, task="scf_single_point"),
        store=store,
    )
    report = check(advice)
    if not report.ok:
        return None
    steps = generate(advice, report)
    return {name: text for step in steps for name, text in step.files.items()}


def _changes_an_input(store: AssetStore, fact: Fact) -> bool:
    """Whether the advertised values of ``fact`` give different input files on
    at least one bundled example structure that ``check`` accepts under each
    of them."""
    for name in available_structures():
        cell = Structure.from_file(structure(name))
        inputs = [
            _inputs(store, cell, {fact["key"]: value})
            for value in _advertised_values(fact)
        ]
        if None not in inputs and any(other != inputs[0] for other in inputs[1:]):
            return True
    return False


def test_every_overridable_fact_changes_a_generated_input(store) -> None:
    """``needs_soc`` did not, on any of them: SOC follows
    ``spin_orbit_coupling`` alone."""
    overridable = [fact for fact in capabilities()["facts"] if fact["overridable"]]

    assert overridable
    inert = [fact["key"] for fact in overridable if not _changes_an_input(store, fact)]
    assert inert == []
