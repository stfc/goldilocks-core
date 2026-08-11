from pathlib import Path

from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata
from goldilocks_core.pseudo.pp_selector import select_pseudos


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


def test_select_pseudos_applies_multiple_filters(tmp_path: Path) -> None:
    """Select pseudopotentials matching multiple filter criteria."""
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
    selected = select_pseudos(
        metadata_list,
        element="Hg",
        functional="PBE",
        pseudo_type="USPP",
        relativistic="full",
    )

    assert len(selected) == 1
    assert selected[0].filename == "Hg.rel-pbe-n-rrkjus_psl.1.0.0.UPF"
