import hashlib
import json
import os
import shutil
import threading
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from multiprocessing import get_context
from pathlib import Path

import pytest
import requests

from goldilocks_core.assets import (
    AssetCorrupt,
    AssetFile,
    AssetNotInstalled,
    AssetSpec,
    AssetStore,
    asset_root,
)
from goldilocks_core.assets.download import download


def source_spec(
    source: Path,
    *,
    checksum: str | None = None,
    preparation_revision: str = "1",
) -> AssetSpec:
    return AssetSpec(
        id="models/example",
        version="1",
        files=(
            AssetFile(
                role="payload",
                path="data/payload.bin",
                url=source.as_uri(),
                checksum=checksum,
                size=source.stat().st_size,
            ),
        ),
        preparation_revision=preparation_revision,
    )


def _install_in_process(root: str, source: str) -> str:
    store = AssetStore(root)
    return str(store.install(source_spec(Path(source))).root)


def test_install_publishes_only_complete_verified_asset(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"verified payload")
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    store = AssetStore(tmp_path / "store")

    installed = store.install(source_spec(source, checksum=f"sha256:{checksum}"))

    assert installed.path("data/payload.bin").read_bytes() == b"verified payload"
    assert store.status("models/example", "1") == "installed"
    assert not list((tmp_path / "store").glob(".example-*"))


def test_failed_install_leaves_no_false_installed_state(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    store = AssetStore(tmp_path / "store")

    with pytest.raises(ValueError, match="checksum mismatch"):
        store.install(source_spec(source, checksum=f"sha256:{'0' * 64}"))

    assert store.status("models/example", "1") == "missing"
    installed = store.install(source_spec(source))
    assert installed.path("data/payload.bin").read_bytes() == b"payload"


def test_verify_detects_changed_and_extra_files(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    store = AssetStore(tmp_path / "store")
    installed = store.install(source_spec(source))
    installed.path("data/payload.bin").write_bytes(b"changed")

    with pytest.raises(AssetCorrupt, match="changed"):
        store.verify("models/example", "1")

    installed.path("data/payload.bin").write_bytes(b"payload")
    (installed.root / "extra").write_text("unexpected")
    with pytest.raises(AssetCorrupt, match="file set"):
        store.verify("models/example", "1")


def test_verify_rejects_unknown_manifest_fields(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    store = AssetStore(tmp_path / "store")
    installed = store.install(source_spec(source))
    manifest = installed.root / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["unexpected"] = True
    manifest.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(AssetCorrupt, match="manifest fields are invalid"):
        store.verify("models/example", "1")


def test_install_replaces_a_stale_preparation_revision(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"first payload")
    store = AssetStore(tmp_path / "store")
    first = store.install(source_spec(source))
    first_fingerprint = json.loads(
        (first.root / "manifest.json").read_text(encoding="utf-8")
    )["preparation_fingerprint"]

    source.write_bytes(b"other payload")
    revised = source_spec(source, preparation_revision="2")
    second = store.install(revised)

    assert second.path("data/payload.bin").read_bytes() == b"other payload"
    second_fingerprint = json.loads(
        (second.root / "manifest.json").read_text(encoding="utf-8")
    )["preparation_fingerprint"]
    assert second_fingerprint == revised.preparation_fingerprint
    assert second_fingerprint != first_fingerprint


def test_install_repairs_a_corrupt_asset(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    store = AssetStore(tmp_path / "store")
    spec = source_spec(source)
    installed = store.install(spec)
    installed.path("data/payload.bin").write_bytes(b"changed")

    repaired = store.install(spec)

    assert repaired.path("data/payload.bin").read_bytes() == b"payload"
    assert store.status("models/example", "1") == "installed"


def test_install_repairs_non_directory_asset_paths(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    store = AssetStore(tmp_path / "store")
    store.root.mkdir()
    asset_id_path = store.root / "models" / "example"
    asset_id_path.parent.mkdir()
    asset_id_path.write_text("corrupt")

    installed = store.install(source_spec(source))

    assert installed.path("data/payload.bin").read_bytes() == b"payload"

    version_path = installed.root
    shutil.rmtree(version_path)
    os.mkfifo(version_path)

    repaired = store.install(source_spec(source))
    assert repaired.path("data/payload.bin").read_bytes() == b"payload"


def test_resolve_names_explicit_install_command(tmp_path: Path) -> None:
    store = AssetStore(tmp_path / "store")

    with pytest.raises(
        AssetNotInstalled, match="goldilocks assets install models/example"
    ):
        store.resolve("models/example", "1")


def test_asset_paths_cannot_escape_store(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="contained"):
        AssetFile(role="payload", path="../escape", url="file:///tmp/source")
    store = AssetStore(tmp_path / "store")
    with pytest.raises(ValueError, match="one non-empty path component"):
        store.verify("../escape", "1")


def test_concurrent_installers_publish_one_valid_asset(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    store = AssetStore(tmp_path / "store")
    spec = source_spec(source)

    with ThreadPoolExecutor(max_workers=2) as executor:
        installed = list(executor.map(lambda _: store.install(spec), range(2)))

    assert installed[0].root == installed[1].root
    assert store.verify("models/example", "1").path("data/payload.bin").is_file()


def test_process_concurrent_installers_publish_one_valid_asset(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    root = tmp_path / "store"

    with ProcessPoolExecutor(
        max_workers=2, mp_context=get_context("spawn")
    ) as executor:
        futures = [
            executor.submit(_install_in_process, str(root), str(source))
            for _ in range(2)
        ]
        roots = [future.result() for future in futures]

    assert roots[0] == roots[1]
    assert (
        AssetStore(root)
        .verify("models/example", "1")
        .path("data/payload.bin")
        .read_bytes()
        == b"payload"
    )


def test_verify_rejects_non_regular_installed_paths(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    store = AssetStore(tmp_path / "store")
    installed = store.install(source_spec(source))
    os.mkfifo(installed.root / "unmanifested-pipe")

    with pytest.raises(AssetCorrupt, match="non-regular path"):
        store.verify("models/example", "1")


def test_asset_root_uses_override_then_xdg(monkeypatch, tmp_path: Path) -> None:
    override = tmp_path / "override"
    monkeypatch.setenv("GOLDILOCKS_ASSET_ROOT", str(override))
    assert asset_root() == override

    monkeypatch.delenv("GOLDILOCKS_ASSET_ROOT")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert asset_root() == tmp_path / "xdg" / "goldilocks" / "assets"


def _flaky_server(failures: int, payload: bytes):
    """Serve the given number of 503s, then the payload, over a real socket."""
    served = {"count": 0}

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            served["count"] += 1
            if served["count"] <= failures:
                self.send_response(503)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args: object) -> None:
            del args

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, served


def test_download_retries_transient_server_failures(tmp_path: Path) -> None:
    """A transient 503 is retried instead of failing the download."""
    payload = b"verified payload"
    server, thread, served = _flaky_server(failures=1, payload=payload)
    destination = tmp_path / "payload.bin"

    try:
        download(
            AssetFile(
                role="payload",
                path="data/payload.bin",
                url=f"http://127.0.0.1:{server.server_port}/payload.bin",
            ),
            destination,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert destination.read_bytes() == payload
    assert served["count"] == 2


def test_download_fails_after_exhausted_retries(tmp_path: Path) -> None:
    """A persistently failing source raises after exhausting the retry budget."""
    server, thread, served = _flaky_server(failures=99, payload=b"never")
    destination = tmp_path / "payload.bin"

    try:
        with pytest.raises(requests.RequestException):
            download(
                AssetFile(
                    role="payload",
                    path="data/payload.bin",
                    url=f"http://127.0.0.1:{server.server_port}/payload.bin",
                ),
                destination,
            )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert served["count"] == 4


def test_references_resolves_bare_registry_table_id() -> None:
    """The operator-facing table id resolves without the storage prefix."""
    from goldilocks_core.assets.runtime import catalogue, references

    resolved = references("pseudodojo-pbesol-efficiency-sr", catalogue())

    assert len(resolved) == 1
    assert resolved[0].spec.id == "pseudopotentials/pseudodojo-pbesol-efficiency-sr"


def test_references_resolves_asset_ids_and_profiles() -> None:
    """Exact asset ids and the shipped profile keep resolving as before."""
    from goldilocks_core.assets.runtime import catalogue, references

    entries = catalogue()

    direct = references("pseudopotentials/pseudodojo-pbesol-efficiency-sr", entries)
    assert direct[0].spec.id == "pseudopotentials/pseudodojo-pbesol-efficiency-sr"

    profile_assets = references("default", entries)
    assert {installation.spec.id for installation in profile_assets} >= {
        "pseudopotentials/pseudodojo-pbesol-efficiency-sr"
    }


def test_references_rejects_unknown_names() -> None:
    """A name that is no asset, table, or profile fails with guidance."""
    from goldilocks_core.assets.runtime import references

    with pytest.raises(KeyError, match="unknown asset 'not-a-table-or-profile'"):
        references("not-a-table-or-profile", {})
