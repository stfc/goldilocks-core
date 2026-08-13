import hashlib
import io
import json
import tarfile
from pathlib import Path

from goldilocks_core.assets import AssetFile, AssetSpec, AssetStore
from goldilocks_core.pseudo.import_pseudodojo import preparer as dojo_preparer
from goldilocks_core.pseudo.import_sssp import preparer as sssp_preparer
from goldilocks_core.pseudo.installed import load_installed_table
from goldilocks_core.pseudo.registry import PseudoTable

UPF = (
    b'<UPF version="2.0.1">\n'
    b'<PP_HEADER element="Si" pseudo_type="NC" functional="PBEsol" '
    b'relativistic="scalar" z_valence="4.0"/>\n'
    b"</UPF>\n"
)


def archive(path: Path, members: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:gz") as tar:
        for name, payload in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))


def table(provider: str, spec: AssetSpec) -> PseudoTable:
    return PseudoTable(
        id=f"{provider}-fixture",
        provider=provider,
        upstream_table="fixture",
        version="1",
        functional="PBEsol",
        relativistic="SR",
        accuracy="efficiency",
        licence="fixture licence",
        citation="fixture citation",
        elements=("Si",),
        asset=spec,
        default=False,
    )


def test_pseudodojo_normalizes_reports_and_verified_upfs(tmp_path: Path) -> None:
    upfs = tmp_path / "upfs.tgz"
    reports = tmp_path / "reports.tgz"
    archive(upfs, {"nested/Si.upf": UPF})
    report = {
        "md5_upf": hashlib.md5(UPF).hexdigest(),
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
    pseudo_table = table("pseudodojo", spec)
    store = AssetStore(tmp_path / "store")

    installed = store.install(spec, dojo_preparer(pseudo_table))
    metadata = load_installed_table(installed)

    assert [item.element for item in metadata] == ["Si"]
    assert metadata[0].functional == "PBEsol"
    assert metadata[0].relativistic == "scalar"
    assert metadata[0].source_set == "efficiency"
    assert metadata[0].sssp_recommended_cutoff == {
        "ecutwfc_ry": 40.0,
        "ecutrho_ry": 160.0,
    }
    assert metadata[0].pseudo_info["cutoff_hints"] == {
        "high": 40.0,
        "low": 20.0,
        "normal": 30.0,
    }
    assert not list(installed.root.rglob("*.tgz"))


def test_sssp_normalizes_sidecar_and_verified_upfs(tmp_path: Path) -> None:
    upfs = tmp_path / "table.tar.gz"
    sidecar = tmp_path / "table.json"
    archive(upfs, {"nested/Si.upf": UPF})
    sidecar.write_text(
        json.dumps(
            {
                "Si": {
                    "filename": "Si.upf",
                    "md5": hashlib.md5(UPF).hexdigest(),
                    "cutoff_wfc": 30.0,
                    "cutoff_rho": 120.0,
                    "pseudopotential": "Si fixture",
                }
            }
        )
    )
    spec = AssetSpec(
        "sssp-fixture",
        "1",
        (
            AssetFile("pseudopotentials", "source/table.tar.gz", upfs.as_uri()),
            AssetFile("metadata", "source/table.json", sidecar.as_uri()),
        ),
    )
    pseudo_table = table("sssp", spec)
    store = AssetStore(tmp_path / "store")

    installed = store.install(spec, sssp_preparer(pseudo_table))
    metadata = load_installed_table(installed)

    assert metadata[0].is_sssp
    assert metadata[0].source_pseudopotential == "Si fixture"
    assert metadata[0].sssp_recommended_cutoff == {
        "ecutwfc_ry": 30.0,
        "ecutrho_ry": 120.0,
    }
    assert not list(installed.root.rglob("*.tar.gz"))
