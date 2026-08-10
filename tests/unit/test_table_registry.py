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
upstream_table = "pseudodojo-pbesol-efficiency"
version = "0.4"
functional = "PBEsol"
relativistic = "SR"
accuracy = "efficiency"
licence = "CC-BY-4.0"
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
    assert default_table(packaged).name == "pseudodojo-pbesol-efficiency"


def test_the_default_is_the_cheapest_clean_licence_table(packaged):
    """It is installed most often, so it should be the smallest and least encumbered."""
    default = default_table(packaged)

    assert default.licence == "CC-BY-4.0"
    assert default.functional == "PBEsol"
    assert all(
        default.transfer_bytes <= t.transfer_bytes
        for t in packaged.values()
        if t.functional == "PBEsol" and t.relativistic == "SR"
    )


def test_every_entry_declares_terms(packaged):
    """An artifact with no stated licence is a decision nobody made."""
    for table in packaged.values():
        assert table.licence
        assert table.citation
        assert table.upstream_url
        assert table.upstream_table


def test_accuracy_uses_one_vocabulary_across_libraries(packaged):
    """PseudoDojo standard/stringent and SSSP efficiency/precision are one axis."""
    assert {t.accuracy for t in packaged.values()} <= {"efficiency", "precision"}


def test_every_table_declares_what_it_will_transfer(packaged):
    """`gl download` reports this before fetching; an entry without it cannot."""
    for table in packaged.values():
        assert table.transfer_bytes and table.transfer_bytes > 0


def test_covers_and_missing_from(packaged):
    table = packaged["pseudodojo-pbesol-efficiency"]

    assert table.covers("Si")
    assert not table.covers("U")
    assert table.missing_from(("Si", "U", "Ce")) == ("U", "Ce")


def test_the_default_table_carries_almost_no_lanthanides(packaged):
    """The gap that makes the 3+ table necessary."""
    assert packaged["pseudodojo-pbesol-efficiency"].lanthanides == ("La", "Lu")


def test_the_lanthanide_table_changes_the_functional(packaged):
    """Choosing it is a scientific decision, not a fallback Core may take silently."""
    default = packaged["pseudodojo-pbesol-efficiency"]
    lanthanide = packaged["pseudodojo-pbe-lanthanides"]

    assert lanthanide.covers("Ce")
    assert not default.covers("Ce")
    assert lanthanide.functional != default.functional


def test_actinides_come_only_from_the_table_with_encumbered_licensing(packaged):
    """Reachable, but not without the user knowing what lands on their disk."""
    with_actinides = [t for t in packaged.values() if t.actinides]

    assert [t.name for t in with_actinides] == ["sssp-pbesol-efficiency"]
    assert set(with_actinides[0].actinides) <= ACTINIDES
    assert "GPL" in with_actinides[0].licence


def test_no_pseudodojo_table_covers_actinides(packaged):
    """The whole PseudoDojo catalogue stops before the actinides."""
    for table in packaged.values():
        if table.provider == "pseudodojo":
            assert not table.actinides


def test_only_a_fully_relativistic_table_can_serve_spin_orbit_coupling(packaged):
    relativistic = {t.name for t in packaged.values() if t.relativistic == "FR"}

    assert relativistic
    assert all(name.endswith("-fr") for name in relativistic)
    assert packaged["sssp-pbesol-efficiency"].relativistic == "SR"


@pytest.mark.parametrize(
    ("element", "expected"),
    [
        ("Si", {"available everywhere"}),
        ("Ce", {"pseudodojo-pbe-lanthanides", "sssp-pbesol-efficiency"}),
        ("U", {"sssp-pbesol-efficiency"}),
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


def test_every_functional_has_a_matching_table(packaged):
    """XC consistency is enforced at generation; every functional needs a table."""
    for functional in ("PBEsol", "PBE", "LDA"):
        assert any(t.functional == functional for t in packaged.values())


def test_names_encode_what_distinguishes_a_table(packaged):
    """A user picks from `gl list pp` by reading names, not by opening the registry."""
    for table in packaged.values():
        assert table.functional.lower() in table.name.lower()
        if table.relativistic == "FR":
            assert table.name.endswith("-fr")
