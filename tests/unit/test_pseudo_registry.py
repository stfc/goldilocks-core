from pathlib import Path

import pytest

from goldilocks_core.assets.pseudopotentials.registry import (
    InvalidPseudoRegistry,
    default_table,
    load_tables,
)


def test_registry_declares_complete_provider_assets() -> None:
    tables = load_tables()

    dojo = tables["pseudodojo-pbesol-efficiency-sr"]
    assert dojo.functional == "PBEsol"
    assert dojo.accuracy == "efficiency"
    assert dojo.relativistic == "scalar"
    assert {file.role for file in dojo.asset.files} == {
        "pseudopotentials",
        "metadata",
    }
    assert all(
        file.url.startswith("https://www.pseudo-dojo.org/") for file in dojo.asset.files
    )
    assert dojo.asset.preparation_revision == "2"

    sssp = tables["sssp-pbe-efficiency-sr"]
    assert {file.role for file in sssp.asset.files} == {
        "pseudopotentials",
        "metadata",
        "licence",
    }
    assert all(
        "archive.materialscloud.org/api" in file.url for file in sssp.asset.files
    )
    assert all("rcyfm-68h65" in file.url for file in sssp.asset.files)
    assert sssp.asset.preparation_revision == "1"
    assert all(
        file.checksum is not None and file.size is not None
        for table in tables.values()
        for file in table.asset.files
    )


def test_registry_has_one_exact_default() -> None:
    table = default_table()

    assert table.id == "pseudodojo-pbesol-efficiency-sr"
    assert table.asset.version == "0.4"


def test_frozen_4f_core_is_a_declared_field_not_inferred_at_import_time() -> None:
    """v2 epic 3 (#4) bug fix: frozen_4f_core used to be guessed by
    substring-matching upstream_table for "3plus" at import time
    (pseudo/import_pseudodojo.py); it is now a typed registry field."""
    tables = load_tables()

    assert tables["pseudodojo-pbe-lanthanides-sr"].frozen_4f_core is True
    assert tables["pseudodojo-pbesol-efficiency-sr"].frozen_4f_core is False


def test_note_and_record_reach_the_parsed_table_instead_of_being_dropped() -> None:
    """v2 epic 3 (#4) bug fix: note/record were validated as allowed
    optional TOML fields but never copied onto PseudoTable, so e.g. a
    table's licence caveat in note never reached anything downstream."""
    table = load_tables()["sssp-pbe-efficiency-sr"]

    assert table.note is not None
    assert "never redistributed" in table.note
    assert table.record == "rcyfm-68h65"
    other = load_tables()["pseudodojo-pbesol-efficiency-sr"]
    assert other.note is not None
    assert "never redistributed" not in other.note
    assert other.record is None


def test_registry_rejects_unknown_table_fields(tmp_path: Path) -> None:
    registry = tmp_path / "registry.toml"
    registry.write_text(
        """
[tables.fixture]
provider = "sssp"
upstream_table = "fixture"
version = "1"
functional = "PBEsol"
relativistic = "scalar"
accuracy = "efficiency"
licence = "fixture"
citation = "fixture"
upstream_url = "https://example.invalid/fixture"
transfer_bytes = 1
installed_bytes = 1
elements = ["Si"]
default = true
unexpected = "ignored"

[[tables.fixture.files]]
role = "pseudopotentials"
path = "source/pseudos.tgz"
url = "file:///tmp/pseudos.tgz"

[[tables.fixture.files]]
role = "metadata"
path = "source/metadata.json"
url = "file:///tmp/metadata.json"
""".strip()
    )

    with pytest.raises(InvalidPseudoRegistry, match="extra: unexpected"):
        load_tables(registry)
