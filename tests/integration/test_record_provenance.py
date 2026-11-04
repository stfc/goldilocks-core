"""#173: a value the request set reads ``human``, and a record whose
heuristic follows another record names it in ``derived_from``.

The magnetic record read ``heuristic`` with no ``field_sources`` when the
request enabled spin-orbit coupling, a pinned pseudopotential table read
``heuristic``, and no derived record linked to what decided it. Runs
offline: table selection reads the packaged registry, and the ML tiers are
not installed in the test's asset root, so the facts are the heuristic's.
"""

from __future__ import annotations

from typing import Any

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.server import _handlers
from goldilocks_core.server.documents import ComputeRequestDocument

pytestmark = pytest.mark.integration


def _fept() -> Structure:
    """L1_0 FePt, MC3D mc3d-49510: Fe at the origin, Pt at the body centre
    of the 2-atom tetragonal cell."""
    return Structure(
        Lattice.tetragonal(2.6855469198646, 3.7210360351257),
        ["Fe", "Pt"],
        [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
    )


def _records(**overrides: Any) -> dict[str, Any]:
    document = ComputeRequestDocument(
        structure_content=_fept().to(fmt="cif"), hpc="scarf", overrides=overrides
    )
    return _handlers.explain(document)["records"]


def test_a_requested_spin_orbit_coupling_reads_human() -> None:
    records = _records(spin_orbit_coupling=True)

    magnetic = records["magnetic"]
    assert magnetic["value"]["spin_orbit_enabled"] is True
    assert magnetic["source"] == "human"
    assert magnetic["field_sources"] == {
        "spin_polarized": "heuristic",
        "spin_orbit_coupling": "human",
        "magnetic_ordering": "heuristic",
        "starting_magnetization": "heuristic",
        "moment_direction": "heuristic",
    }
    assert magnetic["derived_from"] == ["is_magnetic"]


def test_the_table_and_its_treatment_follow_the_spin_orbit_switch() -> None:
    """Selection under SOC is derived, not the request's own choice: both
    records stay heuristic and name the records they follow."""
    records = _records(spin_orbit_coupling=True)

    table, relativistic = records["pseudo_table"], records["relativistic"]
    assert table["value"]["id"] == "pseudodojo-pbesol-efficiency-fr"
    assert (table["source"], table["derived_from"]) == (
        "heuristic",
        ["functional", "magnetic"],
    )
    assert (relativistic["value"], relativistic["source"]) == ("full", "heuristic")
    assert relativistic["derived_from"] == ["magnetic"]


def test_a_pinned_table_reads_human() -> None:
    table = _records(pseudo_table_id="sssp-pbesol-efficiency-sr")["pseudo_table"]

    assert table["value"]["id"] == "sssp-pbesol-efficiency-sr"
    assert table["source"] == "human"
    assert table["field_sources"] == {"pseudo_table_id": "human"}
    assert table["derived_from"] == []


def test_records_that_follow_a_fact_stay_heuristic_and_name_it() -> None:
    records = _records()

    linked = {
        name: (records[name]["source"], records[name]["derived_from"])
        for name in ("magnetic", "occupations", "k_sampling", "hubbard")
    }
    assert linked == {
        "magnetic": ("heuristic", ["is_magnetic"]),
        "occupations": ("heuristic", ["is_metal"]),
        "k_sampling": ("heuristic", ["is_metal"]),
        "hubbard": ("heuristic", ["needs_correlation"]),
    }
    assert records["is_metal"]["source"] == "heuristic"
    assert records["convergence"]["derived_from"] == []


def test_a_non_metal_s_occupations_name_the_magnetic_record_that_decided() -> None:
    """For a non-metal the magnetic record decides whether fixed occupations
    can run: FePt classified non-metal is spin-polarized with no moment to
    pin, so it gets smearing, and the record names both records it
    followed."""
    occupations = _records(is_metal="non_metal")["occupations"]

    assert occupations["value"]["occupations"] == "smearing"
    assert (occupations["source"], occupations["derived_from"]) == (
        "heuristic",
        ["is_metal", "magnetic"],
    )
