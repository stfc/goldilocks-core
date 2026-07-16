from pathlib import Path

from goldilocks_core.pseudo.pp_registry import (
    filter_by_element,
    filter_by_functional,
    filter_by_pseudo_type,
    filter_by_relativistic,
    load_pseudo_metadata,
)


def make_upf(
    *,
    element: str,
    pseudo_type: str,
    functional: str,
    relativistic: str,
    z_valence: str,
) -> str:
    """Build a minimal UPF string for tests."""
    return (
        "<UPF>"
        f'<PP_HEADER element="{element}" '
        f'pseudo_type="{pseudo_type}" '
        f'functional="{functional}" '
        f'relativistic="{relativistic}" '
        f'z_valence="{z_valence}" />'
        "</UPF>"
    )


def test_load_pseudo_metadata_loads_upf_files_under_root(tmp_path: Path) -> None:
    """Load pseudopotential metadata from a synthetic pseudo root."""
    pseudo_root = tmp_path / "pseudopotentials" / "pslibrary"
    pseudo_root.mkdir(parents=True)

    pseudo_path = pseudo_root / "Hg.pbe-n-rrkjus_psl.1.0.0.UPF"
    pseudo_path.write_text(
        make_upf(
            element="Hg",
            pseudo_type="USPP",
            functional="PBE",
            relativistic="scalar",
            z_valence="12.0",
        )
    )

    metadata_list = load_pseudo_metadata(tmp_path / "pseudopotentials")

    assert len(metadata_list) == 1
    assert metadata_list[0].filename == "Hg.pbe-n-rrkjus_psl.1.0.0.UPF"
    assert metadata_list[0].library == "pslibrary"
    assert metadata_list[0].element == "Hg"


def test_filter_by_element_returns_matching_pseudos_only(tmp_path: Path) -> None:
    """Filter loaded pseudopotential metadata by element."""
    pseudo_root = tmp_path / "pseudopotentials" / "pslibrary"
    pseudo_root.mkdir(parents=True)

    (pseudo_root / "Hg.pbe-n-rrkjus_psl.1.0.0.UPF").write_text(
        make_upf(
            element="Hg",
            pseudo_type="USPP",
            functional="PBE",
            relativistic="scalar",
            z_valence="12.0",
        )
    )
    (pseudo_root / "Si.pbe-n-rrkjus_psl.1.0.0.UPF").write_text(
        make_upf(
            element="Si",
            pseudo_type="USPP",
            functional="PBE",
            relativistic="scalar",
            z_valence="4.0",
        )
    )

    metadata_list = load_pseudo_metadata(tmp_path / "pseudopotentials")
    filtered = filter_by_element(metadata_list, "Hg")

    assert len(filtered) == 1
    assert filtered[0].element == "Hg"
    assert filtered[0].filename == "Hg.pbe-n-rrkjus_psl.1.0.0.UPF"


def test_filter_by_functional_returns_matching_pseudos_only(
    tmp_path: Path,
) -> None:
    """Filter loaded pseudopotential metadata by functional."""
    pseudo_root = tmp_path / "pseudopotentials" / "pslibrary"
    pseudo_root.mkdir(parents=True)

    (pseudo_root / "Hg.pbe-n-rrkjus_psl.1.0.0.UPF").write_text(
        make_upf(
            element="Hg",
            pseudo_type="USPP",
            functional="PBE",
            relativistic="scalar",
            z_valence="12.0",
        )
    )
    (pseudo_root / "Hg.pbesol-n-rrkjus_psl.1.0.0.UPF").write_text(
        make_upf(
            element="Hg",
            pseudo_type="USPP",
            functional="PBESOL",
            relativistic="scalar",
            z_valence="12.0",
        )
    )

    metadata_list = load_pseudo_metadata(tmp_path / "pseudopotentials")
    filtered = filter_by_functional(metadata_list, "PBE")

    assert len(filtered) == 1
    assert filtered[0].functional == "PBE"
    assert filtered[0].filename == "Hg.pbe-n-rrkjus_psl.1.0.0.UPF"


def test_filter_by_functional_excludes_malformed_recognized_aliases(
    tmp_path: Path,
) -> None:
    """Filter only exact recognized aliases, never labels with extra tokens."""
    pseudo_root = tmp_path / "pseudopotentials" / "pslibrary"
    pseudo_root.mkdir(parents=True)
    for filename, functional in (
        ("Hg.pbesol.UPF", "SLA PW PSX PSC"),
        ("Hg.rpbe-psx-psc.UPF", "RPBE PSX PSC"),
        ("Hg.pbx-pbc-experimental.UPF", "PBX PBC experimental"),
        ("Hg.pz-experimental.UPF", "PZ experimental"),
        ("Hg.pbesol-experimental.UPF", "SLA PW PSX PSC experimental"),
    ):
        (pseudo_root / filename).write_text(
            make_upf(
                element="Hg",
                pseudo_type="USPP",
                functional=functional,
                relativistic="scalar",
                z_valence="12.0",
            )
        )

    metadata_list = load_pseudo_metadata(tmp_path / "pseudopotentials")

    assert [
        metadata.filename for metadata in filter_by_functional(metadata_list, "PBE-sol")
    ] == ["Hg.pbesol.UPF"]
    assert filter_by_functional(metadata_list, "PBE") == []
    assert filter_by_functional(metadata_list, "LDA") == []


def test_filter_by_pseudo_type_returns_matching_pseudos_only(
    tmp_path: Path,
) -> None:
    """Filter loaded pseudopotential metadata by pseudo type."""
    pseudo_root = tmp_path / "pseudopotentials" / "pslibrary"
    pseudo_root.mkdir(parents=True)

    (pseudo_root / "Hg.pbe-n-rrkjus_psl.1.0.0.UPF").write_text(
        make_upf(
            element="Hg",
            pseudo_type="USPP",
            functional="PBE",
            relativistic="scalar",
            z_valence="12.0",
        )
    )
    (pseudo_root / "Hg.pbe-n-kjpaw_psl.1.0.0.UPF").write_text(
        make_upf(
            element="Hg",
            pseudo_type="PAW",
            functional="PBE",
            relativistic="scalar",
            z_valence="12.0",
        )
    )

    metadata_list = load_pseudo_metadata(tmp_path / "pseudopotentials")
    filtered = filter_by_pseudo_type(metadata_list, "PAW")

    assert len(filtered) == 1
    assert filtered[0].pseudo_type == "PAW"
    assert filtered[0].filename == "Hg.pbe-n-kjpaw_psl.1.0.0.UPF"


def test_filter_by_relativistic_returns_matching_pseudos_only(
    tmp_path: Path,
) -> None:
    """Filter loaded pseudopotential metadata by relativistic mode."""
    pseudo_root = tmp_path / "pseudopotentials" / "pslibrary"
    pseudo_root.mkdir(parents=True)

    (pseudo_root / "Hg.pbe-n-rrkjus_psl.1.0.0.UPF").write_text(
        make_upf(
            element="Hg",
            pseudo_type="USPP",
            functional="PBE",
            relativistic="scalar",
            z_valence="12.0",
        )
    )
    (pseudo_root / "Hg.rel-pbe-n-rrkjus_psl.1.0.0.UPF").write_text(
        make_upf(
            element="Hg",
            pseudo_type="USPP",
            functional="PBE",
            relativistic="full",
            z_valence="12.0",
        )
    )

    metadata_list = load_pseudo_metadata(tmp_path / "pseudopotentials")
    filtered = filter_by_relativistic(metadata_list, "full")

    assert len(filtered) == 1
    assert filtered[0].relativistic == "full"
    assert filtered[0].filename == "Hg.rel-pbe-n-rrkjus_psl.1.0.0.UPF"
