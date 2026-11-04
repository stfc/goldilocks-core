"""#177: published pseudopotential records name each UPF portably -- its
table, its path inside the table and its content hash -- and carry no path
of the machine that served the request.

The same offline SSSP table is installed into two asset roots. Every
transport's records (``/explain``, ``/run``, CLI ``explain --json``) and the
published ``goldilocks.json`` must contain neither root, and the two
manifests must be byte-identical. The table's sources stay outside both
roots, because ``records.pseudo_table`` publishes their ``file://`` URLs.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from support import (
    SSSP_FIXTURE_UPF,
    mc3d_42058_silicon,
    run_cli,
    sssp_fixture_table_spec,
    strict_json,
    write_registry,
)

from goldilocks_core.assets.pseudopotentials.importers import sssp_preparer
from goldilocks_core.assets.store import AssetStore
from goldilocks_core.bundle import bundle_files
from goldilocks_core.server import _handlers
from goldilocks_core.server.documents import ComputeRequestDocument


@pytest.fixture
def two_asset_roots(tmp_path, monkeypatch) -> tuple[Path, Path]:
    """The offline Si table installed into two asset roots, its sources
    beside them, and the registry (in-process and for subprocesses)
    declaring only that table."""
    spec, table = sssp_fixture_table_spec(tmp_path / "sources")
    roots = (tmp_path / "root-a", tmp_path / "root-b")
    for root in roots:
        AssetStore(root).install(spec, sssp_preparer(table))
    monkeypatch.setattr(
        "goldilocks_core.service._pseudo.load_tables",
        lambda *_args, **_kwargs: {table.id: table},
    )
    registry = tmp_path / "registry.toml"
    write_registry(registry, table)
    monkeypatch.setenv("GOLDILOCKS_PSEUDO_REGISTRY", str(registry))
    return roots


def _publish(root: Path, monkeypatch) -> tuple[dict, dict, bytes]:
    """``/explain``, the ``/run`` summary and ``goldilocks.json`` for
    MC3D Si served from the asset root ``root``."""
    monkeypatch.setenv("GOLDILOCKS_ASSET_ROOT", str(root))
    document = ComputeRequestDocument(
        structure_content=mc3d_42058_silicon().to(fmt="cif"), hpc="scarf"
    )
    explained = _handlers.explain(document)
    summary, bundle_input = _handlers.run(document)
    published = {file["path"]: file["content"] for file in bundle_files(bundle_input)}
    return explained, summary, published["goldilocks.json"]


def _host_paths(text: str, root: Path) -> list[str]:
    return [path for path in {str(root), str(root.resolve())} if path in text]


def test_no_output_names_the_asset_root_and_two_installs_publish_the_same_bytes(
    two_asset_roots, monkeypatch
) -> None:
    manifests = []
    for root in two_asset_roots:
        explained, summary, manifest = _publish(root, monkeypatch)
        for output in (json.dumps(explained), json.dumps(summary), manifest.decode()):
            assert _host_paths(output, root) == []
        manifests.append(manifest)

    assert manifests[0] == manifests[1]


def test_cli_json_does_not_name_the_asset_root(
    two_asset_roots, monkeypatch, tmp_path
) -> None:
    root = two_asset_roots[0]
    monkeypatch.setenv("GOLDILOCKS_ASSET_ROOT", str(root))
    structure = tmp_path / "Si.cif"
    mc3d_42058_silicon().to(filename=str(structure))

    completed = run_cli("explain", str(structure), "--hpc", "scarf", "--json")

    assert completed.returncode == 0, completed.stderr
    assert _host_paths(completed.stdout, root) == []
    (entry,) = strict_json(completed.stdout)["records"]["pseudopotentials"]["value"]
    assert entry["content_sha256"] == hashlib.sha256(SSSP_FIXTURE_UPF).hexdigest()
    assert entry["asset_path"] == "pseudos/Si.upf"


def test_a_published_upf_record_is_its_table_path_and_content_hash(
    two_asset_roots, monkeypatch
) -> None:
    """The record names the UPF by table id and path inside the table, and
    its content hash and size are those of the copy the bundle ships."""
    explained, summary, manifest_bytes = _publish(two_asset_roots[0], monkeypatch)
    manifest: dict[str, Any] = strict_json(manifest_bytes)

    (entry,) = manifest["records"]["pseudopotentials"]["value"]
    shipped = manifest["files"]["pseudo/Si.upf"]
    assert (entry["content_sha256"], entry["content_size_bytes"]) == (
        shipped["sha256"],
        shipped["size_bytes"],
    )
    assert "filepath" not in entry
    assert "pseudo_info" not in entry
    assert (entry["table_id"], entry["asset_path"], entry["filename"]) == (
        "pseudopotentials/sssp-fixture",
        "pseudos/Si.upf",
        "Si.upf",
    )
    published = manifest["records"]["pseudopotentials"]
    for output in (explained, summary):
        assert output["records"]["pseudopotentials"] == published
