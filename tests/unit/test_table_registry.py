"""Tests for the pseudopotential table registry."""

from __future__ import annotations

import pytest

from goldilocks_core.artifacts import cache
from goldilocks_core.pseudo.table_registry import (
    ACTINIDES,
    PSEUDO_REGISTRY_ENV,
    default_table,
    load_tables,
    local_registry_path,
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


_SSSP = {
    "sssp-pbe-efficiency-sr",
    "sssp-pbe-precision-sr",
    "sssp-pbesol-efficiency-sr",
    "sssp-pbesol-precision-sr",
}
"""Every SSSP table, which all cover exactly the same elements."""


@pytest.fixture(scope="module")
def packaged():
    return load_tables(include_local=False)


def test_the_packaged_registry_loads(packaged):
    assert packaged
    assert all(name == table.name for name, table in packaged.items())


def test_exactly_one_table_is_the_default(packaged):
    assert default_table(packaged).name == "pseudodojo-pbesol-efficiency-sr"


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


def test_every_table_declares_what_it_costs_on_disk(packaged):
    """The compressed size is not the number that has to fit."""
    for table in packaged.values():
        assert table.installed_bytes and table.installed_bytes > 0


def test_installed_size_exceeds_transfer_size_everywhere(packaged):
    """A table smaller unpacked than compressed would mean the two were swapped."""
    for table in packaged.values():
        assert table.installed_bytes > table.transfer_bytes


def test_covers_and_missing_from(packaged):
    table = packaged["pseudodojo-pbesol-efficiency-sr"]

    assert table.covers("Si")
    assert not table.covers("U")
    assert table.missing_from(("Si", "U", "Ce")) == ("U", "Ce")


def test_the_default_table_carries_almost_no_lanthanides(packaged):
    """The gap that makes the 3+ table necessary."""
    assert packaged["pseudodojo-pbesol-efficiency-sr"].lanthanides == ("La", "Lu")


def test_the_lanthanide_table_changes_the_functional(packaged):
    """Choosing it is a scientific decision, not a fallback Core may take silently."""
    default = packaged["pseudodojo-pbesol-efficiency-sr"]
    lanthanide = packaged["pseudodojo-pbe-lanthanides-sr"]

    assert lanthanide.covers("Ce")
    assert not default.covers("Ce")
    assert lanthanide.functional != default.functional


def test_actinides_come_only_from_the_library_with_encumbered_licensing(packaged):
    """Reachable, but not without the user knowing what lands on their disk."""
    with_actinides = [t for t in packaged.values() if t.actinides]

    assert with_actinides
    assert all(t.name.startswith("sssp-") for t in with_actinides)
    for table in with_actinides:
        assert set(table.actinides) <= ACTINIDES
        assert "GPL" in table.licence


def test_registry_order_is_pinned(packaged):
    """`gl pp install N` numbers tables by this order, so it is an interface.

    Appending is free. Inserting or removing renumbers everything after it,
    which would silently repoint a scripted `gl pp install 12` at a different
    table -- so that has to be a deliberate edit here, not a side effect.
    """
    assert list(packaged) == [
        "pseudodojo-pbesol-efficiency-sr",
        "pseudodojo-pbesol-precision-sr",
        "pseudodojo-pbe-efficiency-sr",
        "pseudodojo-pbe-precision-sr",
        "pseudodojo-lda-efficiency-sr",
        "pseudodojo-lda-precision-sr",
        "pseudodojo-pbe-lanthanides-sr",
        "pseudodojo-pbesol-efficiency-fr",
        "pseudodojo-pbesol-precision-fr",
        "pseudodojo-pbe-efficiency-fr",
        "pseudodojo-pbe-precision-fr",
        "sssp-pbe-efficiency-sr",
        "sssp-pbe-precision-sr",
        "sssp-pbesol-efficiency-sr",
        "sssp-pbesol-precision-sr",
    ]


def test_all_four_sssp_tables_are_registered(packaged):
    """SSSP 1.3.0 publishes four; registering one left PBE f-elements uncovered."""
    assert _SSSP <= set(packaged)


def test_every_sssp_table_covers_the_same_elements(packaged):
    """They differ in functional and accuracy, never in reach."""
    coverage = {frozenset(packaged[name].elements) for name in _SSSP}

    assert len(coverage) == 1


def test_every_functional_reaches_the_f_elements(packaged):
    """Lanthanides and actinides are routed to SSSP, so each needs an SSSP table."""
    for functional in ("PBE", "PBEsol"):
        assert any(
            t.functional == functional and t.actinides for t in packaged.values()
        )


def test_no_pseudodojo_table_covers_actinides(packaged):
    """The whole PseudoDojo catalogue stops before the actinides."""
    for table in packaged.values():
        if table.provider == "pseudodojo":
            assert not table.actinides


def test_only_a_fully_relativistic_table_can_serve_spin_orbit_coupling(packaged):
    relativistic = {t.name for t in packaged.values() if t.relativistic == "FR"}

    assert relativistic
    assert packaged["sssp-pbesol-efficiency-sr"].relativistic == "SR"


@pytest.mark.parametrize(
    ("element", "expected"),
    [
        ("Si", "every table"),
        ("Ce", {"pseudodojo-pbe-lanthanides-sr"} | _SSSP),
        ("U", _SSSP),
        ("Og", set()),
    ],
)
def test_coverage_lookup_distinguishes_the_reasons_an_element_fails(
    packaged, element, expected
):
    found = {t.name for t in tables_covering(element, packaged)}

    if expected == "every table":
        assert len(found) > 1
    else:
        assert found == expected


def test_an_explicit_path_overrides_the_packaged_registry(tmp_path):
    registry_file = tmp_path / "custom.toml"
    registry_file.write_text(_MINIMAL)

    tables = load_tables(registry_file, include_local=False)

    assert set(tables) == {"only-one"}
    assert default_table(tables).elements == ("Si", "Ge")


def test_the_environment_overrides_the_packaged_registry(tmp_path, monkeypatch):
    registry_file = tmp_path / "custom.toml"
    registry_file.write_text(_MINIMAL)
    monkeypatch.setenv(PSEUDO_REGISTRY_ENV, str(registry_file))

    assert set(load_tables(include_local=False)) == {"only-one"}


def test_a_registry_without_a_single_default_is_rejected(tmp_path):
    registry_file = tmp_path / "custom.toml"
    registry_file.write_text(_MINIMAL.replace("default = true", ""))

    with pytest.raises(LookupError, match="exactly one table as default"):
        default_table(load_tables(registry_file, include_local=False))


def test_every_functional_has_a_matching_table(packaged):
    """XC consistency is enforced at generation; every functional needs a table."""
    for functional in ("PBEsol", "PBE", "LDA"):
        assert any(t.functional == functional for t in packaged.values())


def test_names_encode_what_distinguishes_a_table(packaged):
    """A user picks from `gl pp available` by reading names, not the registry."""
    suffix = {"SR": "-sr", "FR": "-fr", "NR": "-nr"}
    for table in packaged.values():
        assert table.functional.lower() in table.name.lower()
        assert table.name.endswith(suffix[table.relativistic])


def test_local_registry_is_merged_after_the_packaged_registry(tmp_path, monkeypatch):
    """`gl pp add` entries should list and select like installed tables."""
    monkeypatch.setenv(cache.CACHE_ENV, str(tmp_path / "cache"))
    path = local_registry_path()
    path.parent.mkdir(parents=True)
    path.write_text(
        """
[tables."mine-sr"]
provider = "local"
upstream_table = "mine-sr"
version = "local"
functional = "PBEsol"
relativistic = "SR"
accuracy = "efficiency"
licence = "not stated"
upstream_url = "/tmp/mine"
citation = "not stated"
elements = ["Si"]
installed_bytes = 12
""".strip(),
        encoding="utf-8",
    )

    tables = load_tables()

    assert list(tables)[-1] == "mine-sr"
    assert tables["mine-sr"].provider == "local"
