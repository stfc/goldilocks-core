from pathlib import Path

import pytest

from goldilocks_core.pseudo.registry import (
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
    assert all("pseudo-dojo.org" in file.url for file in dojo.asset.files)

    sssp = tables["sssp-pbe-efficiency-sr"]
    assert all(
        "archive.materialscloud.org/api" in file.url for file in sssp.asset.files
    )
    assert all("rcyfm-68h65" in file.url for file in sssp.asset.files)
    assert all(
        file.checksum is not None and file.size is not None
        for table in tables.values()
        for file in table.asset.files
    )


def test_registry_has_one_exact_default() -> None:
    table = default_table()

    assert table.id == "pseudodojo-pbesol-efficiency-sr"
    assert table.asset.version == "0.4"


def test_registry_rejects_unknown_table_fields(tmp_path: Path) -> None:
    """Do not silently accept an unversioned registry schema extension."""
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
