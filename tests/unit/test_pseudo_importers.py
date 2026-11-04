"""Tests for goldilocks_core.assets.pseudopotentials.importers.

Two tests trimmed for v2 epic 9 (#9): they used to also exercise v1's
``selection.select_pseudopotentials`` against the freshly-loaded
metadata to prove element/functional/accuracy matching worked; that
selection logic is v2's own ``advisors/pseudo_selection.py`` now,
covered by ``test_advisors_pseudo_selection.py``. What's left here is
the part unique to this module: that the importer normalizes the
right cutoffs/relativistic treatment onto ``PseudoMetadata`` in the
first place.
"""

import hashlib
import io
import json
import tarfile
from dataclasses import replace
from pathlib import Path

import pytest
from support import dojo_fixture_table_spec

from goldilocks_core.assets.pseudopotentials.importers import (
    PseudoImportError,
    load_installed_table,
    pseudodojo_preparer as dojo_preparer,
    sssp_preparer,
)
from goldilocks_core.assets.pseudopotentials.registry import PseudoTable
from goldilocks_core.assets.records import AssetFile, AssetSpec, InstalledAsset
from goldilocks_core.assets.store import AssetCorrupt, AssetStore

UPF = (
    b'<UPF version="2.0.1">\n'
    b'<PP_HEADER element="Si" pseudo_type="NC" functional="PBEsol" '
    b'relativistic="scalar" z_valence="4.0"/>\n'
    b"</UPF>\n"
)

SERIALIZED_LDA_FUNCTIONAL = {
    "@class": "XcFunc",
    "@module": "pymatgen.core.xcfunc",
    "c": {
        "@class": "LibxcFunc",
        "@module": "pymatgen.core.libxcfunc",
        "name": "LDA_C_PW",
    },
    "x": {
        "@class": "LibxcFunc",
        "@module": "pymatgen.core.libxcfunc",
        "name": "LDA_X",
    },
}


def archive(path: Path, members: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:gz") as tar:
        for name, payload in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))


def sssp_table(spec: AssetSpec) -> PseudoTable:
    """The registry declaration of ``install_sssp_fixture``'s table: SSSP
    publishes both cutoffs, so it declares no ``charge_density_dual``."""
    return PseudoTable(
        id="sssp-fixture",
        provider="sssp",
        upstream_table="fixture",
        version="1",
        functional="PBEsol",
        relativistic="scalar",
        accuracy="efficiency",
        licence="fixture licence",
        citation="fixture citation",
        elements=("Si",),
        asset=spec,
    )


def install_dojo_fixture(
    tmp_path: Path,
    *,
    upf: bytes = UPF,
    report_functional: object = "PBEsol",
    table_functional: str = "PBEsol",
    frozen_4f_core: bool = False,
) -> tuple[InstalledAsset, PseudoTable]:
    """Install one synthetic PseudoDojo table (``dojo_fixture_table_spec``)."""
    spec, registry_table = dojo_fixture_table_spec(
        tmp_path,
        upf=upf,
        report_functional=report_functional,
        table_functional=table_functional,
        frozen_4f_core=frozen_4f_core,
    )
    installed = AssetStore(tmp_path / "store").install(
        spec,
        dojo_preparer(registry_table),
    )
    return installed, registry_table


def install_sssp_fixture(
    tmp_path: Path,
    *,
    upf: bytes = UPF,
    sidecar_functional: str | None = None,
) -> tuple[InstalledAsset, PseudoTable]:
    """Install one synthetic SSSP table."""
    upfs = tmp_path / "table.tar.gz"
    sidecar = tmp_path / "table.json"
    licence = tmp_path / "LICENSE.txt"
    archive(upfs, {"nested/Si.upf": upf})
    facts = {
        "filename": "Si.upf",
        "md5": hashlib.md5(upf).hexdigest(),
        "cutoff_wfc": 30.0,
        "cutoff_rho": 120.0,
        "pseudopotential": "Si fixture",
    }
    if sidecar_functional is not None:
        facts["functional"] = sidecar_functional
    sidecar.write_text(json.dumps({"Si": facts}))
    licence.write_text("SSSP fixture licence\n")
    spec = AssetSpec(
        "pseudopotentials/sssp-fixture",
        "1",
        (
            AssetFile("pseudopotentials", "source/table.tar.gz", upfs.as_uri()),
            AssetFile("metadata", "source/table.json", sidecar.as_uri()),
            AssetFile("licence", "source/LICENSE.txt", licence.as_uri()),
        ),
    )
    registry_table = sssp_table(spec)
    installed = AssetStore(tmp_path / "store").install(
        spec, sssp_preparer(registry_table)
    )
    return installed, registry_table


def test_pseudodojo_normalizes_reports_and_verified_upfs(tmp_path: Path) -> None:
    installed, _ = install_dojo_fixture(tmp_path)
    metadata = load_installed_table(installed)

    assert [item.element for item in metadata] == ["Si"]
    assert metadata[0].functional == "PBEsol"
    assert metadata[0].relativistic == "scalar"
    assert metadata[0].accuracy == "efficiency"
    assert metadata[0].cutoffs == {"ecutwfc_ry": 40.0, "ecutrho_ry": None}
    assert metadata[0].cutoff_hints == {"low": 20.0, "normal": 30.0, "high": 40.0}
    assert metadata[0].table_id == "pseudopotentials/pseudodojo-fixture"
    assert not list(installed.root.rglob("*.tgz"))
    assert "CC BY 4.0" in installed.path("LICENSE.txt").read_text()


def test_pseudodojo_stored_density_cutoff_is_not_read_as_published(
    tmp_path: Path,
) -> None:
    """#180: PseudoDojo publishes only wavefunction cutoff hints. The
    manifest still stores the importer's charge_density_dual x high (160 Ry
    here), so tables installed before the fix stay valid without
    re-preparation, but the reader does not hand it on as a published
    value: the cutoffs advisor derives the density cutoff."""
    installed, _ = install_dojo_fixture(tmp_path)
    (entry,) = json.loads(installed.path("pseudo-table.json").read_text())["entries"]

    (metadata,) = load_installed_table(installed)

    assert (entry["ecutwfc_ry"], entry["ecutrho_ry"]) == (40.0, 160.0)
    assert metadata.cutoffs == {"ecutwfc_ry": 40.0, "ecutrho_ry": None}


def test_installed_pseudo_manifest_rejects_invalid_cutoff_hints(
    tmp_path: Path,
) -> None:
    installed, _ = install_dojo_fixture(tmp_path)
    manifest = installed.path("pseudo-table.json")
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["entries"][0]["cutoff_hints"]["high"] = -40.0
    manifest.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(AssetCorrupt, match=r"cutoff_hints\.high"):
        load_installed_table(installed)


def test_pseudodojo_frozen_4f_core_comes_from_the_registry_field(
    tmp_path: Path,
) -> None:
    """v2 epic 3 (#4) bug fix: frozen_4f_core used to be guessed by
    substring-matching upstream_table for "3plus" here; a fixture table
    with an unrelated upstream_table name proves it now comes from the
    registry's own typed field instead."""
    installed, _ = install_dojo_fixture(tmp_path, frozen_4f_core=True)
    metadata = load_installed_table(installed)

    assert metadata[0].frozen_4f_core is True


def test_pseudodojo_decodes_serialized_lda_functional(tmp_path: Path) -> None:
    installed, _ = install_dojo_fixture(
        tmp_path,
        upf=UPF.replace(b'functional="PBEsol"', b'functional="SLA PW NOGX NOGC"'),
        report_functional=SERIALIZED_LDA_FUNCTIONAL,
        table_functional="LDA",
    )

    metadata = load_installed_table(installed)

    assert metadata[0].functional == "LDA"


def test_sssp_normalizes_sidecar_and_verified_upfs(tmp_path: Path) -> None:
    installed, _ = install_sssp_fixture(tmp_path)
    metadata = load_installed_table(installed)

    assert metadata[0].provider == "sssp"
    assert metadata[0].source_identifier == "Si fixture"
    assert metadata[0].cutoffs == {"ecutwfc_ry": 30.0, "ecutrho_ry": 120.0}
    assert metadata[0].cutoff_hints is None
    assert metadata[0].table_id == "pseudopotentials/sssp-fixture"
    assert not list(installed.root.rglob("*.tar.gz"))
    assert installed.path("LICENSE.txt").read_text() == "SSSP fixture licence\n"


@pytest.mark.parametrize("install", [install_sssp_fixture, install_dojo_fixture])
def test_installed_metadata_names_its_upf_by_table_path_and_content(
    tmp_path: Path, install
) -> None:
    """#177: each UPF is referenced by its path inside the installed table
    and the hash and size of its bytes, not only by the host path it was
    read from."""
    installed, _ = install(tmp_path)

    (metadata,) = load_installed_table(installed)

    assert metadata.content_sha256 == hashlib.sha256(UPF).hexdigest()
    assert metadata.content_size_bytes == len(UPF)
    assert metadata.asset_path == "pseudos/Si.upf"


def test_sssp_preserves_nonrelativistic_upf_provenance(tmp_path: Path) -> None:
    upf = UPF.replace(b'relativistic="scalar"', b'relativistic="non-relativistic"')
    installed, _ = install_sssp_fixture(tmp_path, upf=upf)

    metadata = load_installed_table(installed)

    assert metadata[0].relativistic == "non-relativistic"
    assert metadata[0].pseudo_info["upf_relativistic"] == "non-relativistic"


def test_pseudodojo_rejects_report_registry_disagreement(tmp_path: Path) -> None:
    """A report cannot override the table's declared functional."""
    with pytest.raises(PseudoImportError, match="report functional PBE"):
        install_dojo_fixture(tmp_path, report_functional="PBE")


def test_pseudodojo_rejects_upf_registry_disagreement(tmp_path: Path) -> None:
    """A fully-relativistic UPF header contradicts a scalar table declaration."""
    upf = UPF.replace(b'relativistic="scalar"', b'relativistic="full"')

    with pytest.raises(PseudoImportError, match="relativistic treatment full"):
        install_dojo_fixture(tmp_path, upf=upf)


def test_pseudodojo_accepts_nonrelativistic_header_in_scalar_table(
    tmp_path: Path,
) -> None:
    """Scalar-table compatibility preserves the original UPF treatment."""
    upf = UPF.replace(b'relativistic="scalar"', b'relativistic="non-relativistic"')

    installed, _ = install_dojo_fixture(tmp_path, upf=upf)
    metadata = load_installed_table(installed)

    assert metadata[0].relativistic == "non-relativistic"
    assert metadata[0].pseudo_info["upf_relativistic"] == "non-relativistic"
    assert metadata[0].filepath == str(installed.path("pseudos/Si.upf"))
    assert metadata[0].cutoffs == {"ecutwfc_ry": 40.0, "ecutrho_ry": None}


def test_sssp_rejects_sidecar_registry_disagreement(tmp_path: Path) -> None:
    """An SSSP sidecar cannot override the table functional."""
    with pytest.raises(PseudoImportError, match="SSSP functional PBE"):
        install_sssp_fixture(tmp_path, sidecar_functional="PBE")


def test_sssp_rejects_upf_registry_disagreement(tmp_path: Path) -> None:
    """A fully-relativistic UPF contradicts the SSSP table's scalar declaration."""
    upf = UPF.replace(b'relativistic="scalar"', b'relativistic="full"')

    with pytest.raises(PseudoImportError, match="relativistic treatment full"):
        install_sssp_fixture(tmp_path, upf=upf)


def test_sssp_accepts_nonrelativistic_header_in_scalar_table(tmp_path: Path) -> None:
    """Scalar-table compatibility preserves the original UPF treatment."""
    upf = UPF.replace(b'relativistic="scalar"', b'relativistic="non-relativistic"')

    installed, _ = install_sssp_fixture(tmp_path, upf=upf)
    metadata = load_installed_table(installed)

    assert metadata[0].relativistic == "non-relativistic"
    assert metadata[0].pseudo_info["upf_relativistic"] == "non-relativistic"
    assert metadata[0].cutoffs["ecutwfc_ry"] == 30.0
    assert metadata[0].cutoffs["ecutrho_ry"] == 120.0


def test_installed_pseudo_manifest_rejects_unknown_entry_fields(
    tmp_path: Path,
) -> None:
    """Strictly reject unversioned nested manifest schema changes."""
    installed, _ = install_sssp_fixture(tmp_path)
    manifest = installed.path("pseudo-table.json")
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["entries"][0]["unexpected"] = True
    manifest.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(AssetCorrupt, match="extra: unexpected"):
        load_installed_table(installed)


def test_installed_pseudo_manifest_agrees_with_registry_declaration(
    tmp_path: Path,
) -> None:
    """A table whose registry id differs from its asset id round-trips."""
    installed, declared = install_dojo_fixture(tmp_path)
    assert declared.id != declared.asset.id

    metadata = load_installed_table(installed, table=declared)

    assert [item.element for item in metadata] == ["Si"]
    assert metadata[0].table_id == declared.asset.id


def test_installed_pseudo_manifest_rejects_registry_disagreement(
    tmp_path: Path,
) -> None:
    """Loading against a declaration the manifest does not record fails."""
    installed, declared = install_sssp_fixture(tmp_path)
    tampered = replace(declared, citation="different citation")

    with pytest.raises(AssetCorrupt, match="disagrees with registry"):
        load_installed_table(installed, table=tampered)
