"""Tests for the pseudopotential table registry."""

from __future__ import annotations

import pytest

from goldilocks_core.pseudo.table_registry import (
    ACTINIDES,
    PSEUDO_REGISTRY_ENV,
    default_table,
    load_tables,
    tables_covering,
)

_MINIMAL = """
[tables."only-one"]
provider = "pseudodojo"
version = "0.4"
functional = "PBEsol"
relativistic = "SR"
accuracy = "efficiency"
licence = "CC-BY-4.0"
redistribution = "upstream-only"
upstream_url = "https://example.invalid/"
citation = "nobody"
elements = ["Si", "Ge"]
default = true
"""


@pytest.fixture(scope="module")
def packaged():
    return load_tables()


def test_the_packaged_registry_loads(packaged):
    assert packaged
    assert all(name == table.name for name, table in packaged.items())


def test_exactly_one_table_is_the_default(packaged):
    assert default_table(packaged).name == "nc-sr-04_pbesol_standard"


def test_the_default_is_fetchable_so_a_fresh_install_can_proceed(packaged):
    """A default the user has to install by hand is not a default."""
    assert default_table(packaged).fetchable


def test_every_entry_declares_terms(packaged):
    """An artifact with no stated licence is a decision nobody made."""
    for table in packaged.values():
        assert table.licence
        assert table.citation
        assert table.upstream_url
        assert table.redistribution in {"mirrored", "upstream-only", "metadata-only"}


def test_accuracy_uses_one_vocabulary_across_libraries(packaged):
    """PseudoDojo standard/stringent and SSSP efficiency/precision are one axis."""
    assert {t.accuracy for t in packaged.values()} <= {"efficiency", "precision"}


def test_a_fetchable_table_declares_what_it_will_transfer(packaged):
    """The fetch prompt quotes this; an entry without it cannot be quoted."""
    for table in packaged.values():
        if table.fetchable:
            assert table.transfer_bytes and table.transfer_bytes > 0


def test_covers_and_missing_from(packaged):
    table = packaged["nc-sr-04_pbesol_standard"]

    assert table.covers("Si")
    assert not table.covers("U")
    assert table.missing_from(("Si", "U", "Ce")) == ("U", "Ce")


def test_the_default_table_carries_almost_no_lanthanides(packaged):
    """The gap that makes the 3+ table necessary."""
    assert packaged["nc-sr-04_pbesol_standard"].lanthanides == ("La", "Lu")


def test_the_lanthanide_table_changes_the_functional(packaged):
    """Choosing it is a scientific decision, not a fallback Core may take silently."""
    default = packaged["nc-sr-04_pbesol_standard"]
    lanthanide = packaged["nc-sr-04-3plus_pbe_standard"]

    assert lanthanide.covers("Ce")
    assert not default.covers("Ce")
    assert lanthanide.functional != default.functional


def test_no_fetchable_table_covers_actinides(packaged):
    """Actinides are reachable only through a table we may not redistribute."""
    for table in packaged.values():
        if table.fetchable:
            assert not table.actinides

    sssp = packaged["sssp-1.3_pbesol_efficiency"]
    assert set(sssp.actinides) <= ACTINIDES
    assert sssp.actinides
    assert not sssp.fetchable


def test_only_a_fully_relativistic_table_can_serve_spin_orbit_coupling(packaged):
    relativistic = {t.name for t in packaged.values() if t.relativistic == "FR"}

    assert relativistic
    assert all("nc-fr" in name for name in relativistic)
    assert packaged["sssp-1.3_pbesol_efficiency"].relativistic == "SR"


@pytest.mark.parametrize(
    ("element", "expected"),
    [
        ("Si", {"available everywhere"}),
        ("Ce", {"nc-sr-04-3plus_pbe_standard", "sssp-1.3_pbesol_efficiency"}),
        ("U", {"sssp-1.3_pbesol_efficiency"}),
        ("Og", set()),
    ],
)
def test_coverage_lookup_distinguishes_the_reasons_an_element_fails(
    packaged, element, expected
):
    found = {t.name for t in tables_covering(element, packaged)}

    if expected == {"available everywhere"}:
        assert len(found) > 1
    else:
        assert found == expected


def test_an_explicit_path_overrides_the_packaged_registry(tmp_path):
    registry_file = tmp_path / "custom.toml"
    registry_file.write_text(_MINIMAL)

    tables = load_tables(registry_file)

    assert set(tables) == {"only-one"}
    assert default_table(tables).elements == ("Si", "Ge")


def test_the_environment_overrides_the_packaged_registry(tmp_path, monkeypatch):
    registry_file = tmp_path / "custom.toml"
    registry_file.write_text(_MINIMAL)
    monkeypatch.setenv(PSEUDO_REGISTRY_ENV, str(registry_file))

    assert set(load_tables()) == {"only-one"}


def test_a_registry_without_a_single_default_is_rejected(tmp_path):
    registry_file = tmp_path / "custom.toml"
    registry_file.write_text(_MINIMAL.replace("default = true", ""))

    with pytest.raises(LookupError, match="exactly one table as default"):
        default_table(load_tables(registry_file))
