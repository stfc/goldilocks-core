import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from goldilocks_core.assets import (
    AssetCorrupt,
    AssetFile,
    AssetSpec,
    AssetStore,
    InstalledAsset,
)
from goldilocks_core.pseudo.import_pseudodojo import preparer as dojo_preparer
from goldilocks_core.pseudo.import_sssp import preparer as sssp_preparer
from goldilocks_core.pseudo.installed import load_installed_table
from goldilocks_core.pseudo.registry import PseudoTable
from goldilocks_core.pseudo.validation import PseudoImportError

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


def table(provider: str, spec: AssetSpec, *, functional: str = "PBEsol") -> PseudoTable:
    return PseudoTable(
        id=f"{provider}-fixture",
        provider=provider,
        upstream_table="fixture",
        version="1",
        functional=functional,
        relativistic="scalar",
        accuracy="efficiency",
        licence="fixture licence",
        citation="fixture citation",
        charge_density_dual=4.0,
        elements=("Si",),
        asset=spec,
        default=False,
    )


def install_dojo_fixture(
    tmp_path: Path,
    *,
    upf: bytes = UPF,
    report_functional: object = "PBEsol",
    table_functional: str = "PBEsol",
) -> InstalledAsset:
    """Install one synthetic PseudoDojo table."""
    upfs = tmp_path / "upfs.tgz"
    reports = tmp_path / "reports.tgz"
    archive(upfs, {"nested/Si.upf": upf})
    report = {
        "xc": report_functional,
        "md5_upf": hashlib.md5(upf).hexdigest(),
        "hints": {
            "low": {"ecut": 10.0},
            "normal": {"ecut": 15.0},
            "high": {"ecut": 20.0},
        },
    }
    archive(reports, {"nested/Si.djrepo": json.dumps(report).encode()})
    spec = AssetSpec(
        "pseudodojo-fixture",
        "1",
        (
            AssetFile("pseudopotentials", "source/upfs.tgz", upfs.as_uri()),
            AssetFile("metadata", "source/reports.tgz", reports.as_uri()),
        ),
    )
    return AssetStore(tmp_path / "store").install(
        spec,
        dojo_preparer(table("pseudodojo", spec, functional=table_functional)),
    )


def install_sssp_fixture(
    tmp_path: Path,
    *,
    upf: bytes = UPF,
    sidecar_functional: str | None = None,
) -> InstalledAsset:
    """Install one synthetic SSSP table."""
    upfs = tmp_path / "table.tar.gz"
    sidecar = tmp_path / "table.json"
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
    spec = AssetSpec(
        "sssp-fixture",
        "1",
        (
            AssetFile("pseudopotentials", "source/table.tar.gz", upfs.as_uri()),
            AssetFile("metadata", "source/table.json", sidecar.as_uri()),
        ),
    )
    return AssetStore(tmp_path / "store").install(
        spec, sssp_preparer(table("sssp", spec))
    )


def test_pseudodojo_normalizes_reports_and_verified_upfs(tmp_path: Path) -> None:
    installed = install_dojo_fixture(tmp_path)
    metadata = load_installed_table(installed)

    assert [item.element for item in metadata] == ["Si"]
    assert metadata[0].functional == "PBEsol"
    assert metadata[0].relativistic == "scalar"
    assert metadata[0].accuracy == "efficiency"
    assert metadata[0].cutoffs is not None
    assert metadata[0].cutoffs.ecutwfc_ry == 40.0
    assert metadata[0].cutoffs.ecutrho_ry == 160.0
    assert metadata[0].table_id == "pseudodojo-fixture"
    assert not list(installed.root.rglob("*.tgz"))


def test_pseudodojo_decodes_serialized_lda_functional(tmp_path: Path) -> None:
    installed = install_dojo_fixture(
        tmp_path,
        upf=UPF.replace(b'functional="PBEsol"', b'functional="SLA PW NOGX NOGC"'),
        report_functional=SERIALIZED_LDA_FUNCTIONAL,
        table_functional="LDA",
    )

    metadata = load_installed_table(installed)

    assert metadata[0].functional == "LDA"


def test_sssp_normalizes_sidecar_and_verified_upfs(tmp_path: Path) -> None:
    installed = install_sssp_fixture(tmp_path)
    metadata = load_installed_table(installed)

    assert metadata[0].provider == "sssp"
    assert metadata[0].source_identifier == "Si fixture"
    assert metadata[0].cutoffs is not None
    assert metadata[0].cutoffs.ecutwfc_ry == 30.0
    assert metadata[0].cutoffs.ecutrho_ry == 120.0
    assert metadata[0].table_id == "sssp-fixture"
    assert not list(installed.root.rglob("*.tar.gz"))


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
    """Table-level classification is authoritative; NR light elements stay valid."""
    upf = UPF.replace(b'relativistic="scalar"', b'relativistic="non-relativistic"')

    installed = install_dojo_fixture(tmp_path, upf=upf)
    metadata = load_installed_table(installed)

    assert metadata[0].relativistic == "scalar"


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
    """Table-level classification is authoritative; NR light elements stay valid."""
    upf = UPF.replace(b'relativistic="scalar"', b'relativistic="non-relativistic"')

    installed = install_sssp_fixture(tmp_path, upf=upf)
    metadata = load_installed_table(installed)

    assert metadata[0].relativistic == "scalar"


def test_installed_pseudo_manifest_rejects_unknown_entry_fields(
    tmp_path: Path,
) -> None:
    """Strictly reject unversioned nested manifest schema changes."""
    installed = install_sssp_fixture(tmp_path)
    manifest = installed.path("pseudo-table.json")
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["entries"][0]["unexpected"] = True
    manifest.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(AssetCorrupt, match="extra: unexpected"):
        load_installed_table(installed)
