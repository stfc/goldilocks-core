from pathlib import Path

import pytest

from goldilocks_core.pseudo.parse_upf import parse_upf_metadata


def write_attr_upf(
    path: Path,
    *,
    element: str,
    pseudo_type: str,
    functional: str,
    relativistic: str,
    z_valence: str,
) -> Path:
    """Write a minimal attribute-style UPF fixture."""
    path.write_text(
        "<UPF>"
        f'<PP_HEADER element="{element}" '
        f'pseudo_type="{pseudo_type}" '
        f'functional="{functional}" '
        f'relativistic="{relativistic}" '
        f'z_valence="{z_valence}" />'
        "</UPF>",
        encoding="utf-8",
    )
    return path


def write_text_upf(path: Path) -> Path:
    """Write a minimal text-style UPF fixture."""
    path.write_text(
        """
<UPF>
<PP_HEADER>
Li    Element
3.0    Z valence
USPP    Ultrasoft pseudopotential
PBE    Exchange-Correlation functional
</PP_HEADER>
<PP_INFO>
Generated using a non-relativistic calculation.
</PP_INFO>
</UPF>
""".strip(),
        encoding="utf-8",
    )
    return path


def test_parse_upf_metadata_parses_attribute_style_pslibrary_file(
    tmp_path: Path,
) -> None:
    """Parse metadata from a synthetic PSLibrary-style UPF file."""
    pseudo_root = tmp_path / "pseudopotentials" / "pslibrary"
    pseudo_root.mkdir(parents=True)
    pseudo_path = write_attr_upf(
        pseudo_root / "Hg.pbe-n-rrkjus_psl.1.0.0.UPF",
        element="Hg",
        pseudo_type="USPP",
        functional="PBE",
        relativistic="scalar",
        z_valence="12.0",
    )

    metadata = parse_upf_metadata(pseudo_path)

    assert metadata.element == "Hg"
    assert metadata.filename == "Hg.pbe-n-rrkjus_psl.1.0.0.UPF"
    assert metadata.library == "pslibrary"
    assert metadata.pseudo_type == "USPP"
    assert metadata.functional == "PBE"
    assert metadata.relativistic == "scalar"
    assert metadata.z_valence == 12.0


def test_parse_upf_metadata_parses_gbrv_text_header(tmp_path: Path) -> None:
    """Parse metadata from a synthetic GBRV text-style PP_HEADER."""
    pseudo_root = tmp_path / "pseudopotentials" / "GBRV" / "all_pbe_UPF_v1.5"
    pseudo_root.mkdir(parents=True)
    pseudo_path = write_text_upf(pseudo_root / "li_pbe_v1.4.uspp.F.UPF")

    metadata = parse_upf_metadata(pseudo_path)

    assert metadata.element == "Li"
    assert metadata.filename == "li_pbe_v1.4.uspp.F.UPF"
    assert metadata.library == "GBRV"
    assert metadata.source_set == "all_pbe_UPF_v1.5"
    assert metadata.pseudo_type == "USPP"
    assert metadata.functional == "PBE"
    assert metadata.relativistic == "non-relativistic"
    assert metadata.z_valence == 3.0


def test_parse_upf_metadata_raises_for_missing_file(tmp_path: Path) -> None:
    """Raise an error when the UPF file does not exist."""
    pseudo_path = tmp_path / "missing.UPF"

    with pytest.raises(FileNotFoundError):
        parse_upf_metadata(pseudo_path)


@pytest.mark.parametrize(
    ("functional", "expected"),
    [
        ("PBEsol", "PBEsol"),
        ("PBESOL", "PBEsol"),
        ("pbe-sol", "PBEsol"),
        ("PBE_SOL", "PBEsol"),
        ("PBE sol", "PBEsol"),
        ("SLA PW PSX PSC", "PBEsol"),
        ("SLA PW PBX PBC", "PBE"),
        ("PZ", "LDA"),
        ("SLA PZ NOGX NOGC", "LDA"),
    ],
)
def test_parse_upf_metadata_canonicalizes_recognized_functional_labels(
    tmp_path: Path,
    functional: str,
    expected: str,
) -> None:
    """Canonicalize only recognized PBE, PBEsol, and LDA UPF labels."""
    pseudo_root = tmp_path / "pseudopotentials" / "pslibrary"
    pseudo_root.mkdir(parents=True)
    pseudo_path = write_attr_upf(
        pseudo_root / "Al.pbesol-n-kjpaw_psl.1.0.0.UPF",
        element="Al",
        pseudo_type="PAW",
        functional=functional,
        relativistic="scalar",
        z_valence="3.0",
    )

    metadata = parse_upf_metadata(pseudo_path)

    assert metadata.element == "Al"
    assert metadata.filename == "Al.pbesol-n-kjpaw_psl.1.0.0.UPF"
    assert metadata.pseudo_type == "PAW"
    assert metadata.functional == expected
    assert metadata.relativistic == "scalar"
    assert metadata.z_valence == 3.0


@pytest.mark.parametrize(
    "functional",
    [
        "RPBE",
        "RPBE PSX PSC",
        "PBX PBC experimental",
        "PZ experimental",
        "SLA PW PSX PSC experimental",
        "SLA PW PSX PSC PBX PBC",
    ],
)
def test_parse_upf_metadata_preserves_unknown_functional_labels(
    tmp_path: Path,
    functional: str,
) -> None:
    """Do not reinterpret conflicting or extra UPF functional labels."""
    pseudo_root = tmp_path / "pseudopotentials" / "pslibrary"
    pseudo_root.mkdir(parents=True)
    pseudo_path = write_attr_upf(
        pseudo_root / "C.unknown.UPF",
        element="C",
        pseudo_type="NC",
        functional=functional,
        relativistic="scalar",
        z_valence="4.0",
    )

    metadata = parse_upf_metadata(pseudo_path)

    assert metadata.functional == functional


def test_parse_upf_metadata_prefers_header_pseudo_type_over_filename_hint(
    tmp_path: Path,
) -> None:
    """Prefer PP_HEADER pseudo_type over filename naming conventions."""
    pseudo_root = tmp_path / "pseudopotentials" / "pslibrary"
    pseudo_root.mkdir(parents=True)
    pseudo_path = write_attr_upf(
        pseudo_root / "B.pbe-n-kjpaw_psl.0.1.UPF",
        element="B",
        pseudo_type="USPP",
        functional="PBE",
        relativistic="scalar",
        z_valence="3.0",
    )

    metadata = parse_upf_metadata(pseudo_path)

    assert metadata.element == "B"
    assert metadata.pseudo_type == "USPP"
    assert metadata.functional == "PBE"
    assert metadata.relativistic == "scalar"
