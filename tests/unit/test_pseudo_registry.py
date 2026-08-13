from goldilocks_core.pseudo.registry import default_table, load_tables


def test_registry_declares_complete_provider_assets() -> None:
    tables = load_tables()

    dojo = tables["pseudodojo-pbesol-efficiency-sr"]
    assert dojo.functional == "PBEsol"
    assert dojo.accuracy == "efficiency"
    assert dojo.relativistic == "SR"
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
