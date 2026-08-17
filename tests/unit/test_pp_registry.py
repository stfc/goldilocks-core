import hashlib
import json
from pathlib import Path

import pytest

from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata
from goldilocks_core.pseudo.validation import (
    AmbiguousCutoffMetadata,
    PseudoImportError,
)


def make_upf(
    *,
    element: str = "Si",
    pseudo_type: str = "NC",
    functional: str = "PBEsol",
    relativistic: str = "scalar",
    z_valence: str = "4.0",
) -> str:
    return (
        "<UPF>"
        f'<PP_HEADER element="{element}" '
        f'pseudo_type="{pseudo_type}" '
        f'functional="{functional}" '
        f'relativistic="{relativistic}" '
        f'z_valence="{z_valence}" />'
        "</UPF>"
    )


def test_load_pseudo_metadata_parses_only_upfs_under_explicit_root(
    tmp_path: Path,
) -> None:
    nested = tmp_path / "operator" / "pseudos"
    nested.mkdir(parents=True)
    path = nested / "Si.custom.UPF"
    path.write_text(make_upf())
    (nested / "notes.txt").write_text("not a pseudopotential")

    metadata = load_pseudo_metadata(tmp_path)

    assert len(metadata) == 1
    assert metadata[0].filepath == str(path)
    assert metadata[0].provider is None
    assert metadata[0].accuracy is None
    assert metadata[0].cutoffs is None
    assert metadata[0].warnings == (
        f"No recognized cutoff metadata found for Si under "
        f"custom pseudopotential root {tmp_path.resolve()}.",
    )


def test_sibling_dojo_report_supplies_exact_filename_cutoffs(tmp_path: Path) -> None:
    upf = tmp_path / "Si.upf"
    upf.write_text(make_upf())
    digest = hashlib.md5(upf.read_bytes()).hexdigest()
    (tmp_path / "Si.djrepo").write_text(
        json.dumps(
            {
                "md5_upf": digest,
                "xc": "PBEsol",
                "hints": {
                    "low": {"ecut": 10},
                    "normal": {"ecut": 15},
                    "high": {"ecut": 20},
                },
            }
        )
    )

    metadata = load_pseudo_metadata(tmp_path)[0]

    assert metadata.provider == "pseudodojo"
    assert metadata.accuracy is None
    assert metadata.cutoffs is not None
    assert metadata.cutoffs.ecutwfc_ry == 40.0
    assert metadata.cutoffs.ecutrho_ry is None


def test_mismatched_dojo_report_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "Si.upf").write_text(make_upf())
    (tmp_path / "Si.djrepo").write_text(
        json.dumps(
            {
                "md5_upf": "0" * 32,
                "xc": "PBEsol",
                "hints": {
                    "low": {"ecut": 10},
                    "normal": {"ecut": 15},
                    "high": {"ecut": 20},
                },
            }
        )
    )

    with pytest.raises(PseudoImportError, match="does not match"):
        load_pseudo_metadata(tmp_path)


def test_multiple_exact_cutoff_sidecars_are_ambiguous(tmp_path: Path) -> None:
    upf = tmp_path / "Si.upf"
    upf.write_text(make_upf())
    digest = hashlib.md5(upf.read_bytes()).hexdigest()
    (tmp_path / "Si.djrepo").write_text(
        json.dumps(
            {
                "md5_upf": digest,
                "xc": "PBEsol",
                "hints": {
                    "low": {"ecut": 10},
                    "normal": {"ecut": 15},
                    "high": {"ecut": 20},
                },
            }
        )
    )
    (tmp_path / "sssp.json").write_text(
        json.dumps(
            {
                "Si": {
                    "filename": "Si.upf",
                    "md5": digest,
                    "functional": "PBEsol",
                    "cutoff_wfc": 35,
                    "cutoff_rho": 140,
                }
            }
        )
    )

    with pytest.raises(AmbiguousCutoffMetadata, match="multiple cutoff records"):
        load_pseudo_metadata(tmp_path)


def test_unrelated_json_does_not_supply_cutoffs(tmp_path: Path) -> None:
    (tmp_path / "Si.upf").write_text(make_upf())
    (tmp_path / "wrong.json").write_text(
        json.dumps({"Si": {"filename": "Other.upf", "cutoff_wfc": 1}})
    )

    metadata = load_pseudo_metadata(tmp_path)[0]

    assert metadata.cutoffs is None
