from pathlib import Path

from pymatgen.core import Lattice, Structure

from goldilocks_core.pseudo.pp_policy import PseudoPolicy
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata
from goldilocks_core.pseudo.pp_selector import (
    group_pseudos_by_element,
    select_pp_candidates_for_structure,
    select_pseudos,
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


def test_select_pps_applies_multiple_filters(tmp_path: Path) -> None:
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


def test_group_pseudos_by_element_returns_candidates_for_structure(
    tmp_path: Path,
) -> None:
    """Group candidate pseudopotentials by element for a structure."""
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
    (pseudo_root / "O.pbe-n-kjpaw_psl.1.0.0.UPF").write_text(
        make_upf(
            element="O",
            pseudo_type="PAW",
            functional="PBE",
            relativistic="scalar",
            z_valence="6.0",
        )
    )

    structure = Structure(
        lattice=Lattice.cubic(4.0),
        species=["Hg", "O"],
        coords=[
            [0.0, 0.0, 0.0],
            [0.5, 0.5, 0.5],
        ],
    )

    metadata_list = load_pseudo_metadata(tmp_path / "pseudopotentials")
    grouped = group_pseudos_by_element(structure, metadata_list)

    assert set(grouped) == {"Hg", "O"}
    assert len(grouped["Hg"]) == 1
    assert len(grouped["O"]) == 1
    assert grouped["Hg"][0].element == "Hg"
    assert grouped["O"][0].element == "O"


def test_select_pp_candidates_for_structure_applies_policy_per_element(
    tmp_path: Path,
) -> None:
    """Select structure-aware pseudo candidates under a policy."""
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
    (pseudo_root / "O.pbe-n-kjpaw_psl.1.0.0.UPF").write_text(
        make_upf(
            element="O",
            pseudo_type="PAW",
            functional="PBE",
            relativistic="full",
            z_valence="6.0",
        )
    )

    structure = Structure(
        lattice=Lattice.cubic(4.0),
        species=["Hg", "O"],
        coords=[
            [0.0, 0.0, 0.0],
            [0.5, 0.5, 0.5],
        ],
    )

    metadata_list = load_pseudo_metadata(tmp_path / "pseudopotentials")
    policy = PseudoPolicy(
        relativistic_mode="full",
        preferred_functional="PBE",
    )

    selected = select_pp_candidates_for_structure(
        structure,
        metadata_list,
        policy,
    )

    assert set(selected) == {"Hg", "O"}
    assert len(selected["Hg"]) == 1
    assert len(selected["O"]) == 1
    assert selected["Hg"][0].filename == "Hg.rel-pbe-n-rrkjus_psl.1.0.0.UPF"
    assert selected["O"][0].filename == "O.pbe-n-kjpaw_psl.1.0.0.UPF"
