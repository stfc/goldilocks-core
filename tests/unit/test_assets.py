import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from goldilocks_core.assets import (
    AssetCorrupt,
    AssetFile,
    AssetNotInstalled,
    AssetSpec,
    AssetStore,
    asset_root,
)


def source_spec(source: Path, *, checksum: str | None = None) -> AssetSpec:
    return AssetSpec(
        id="example",
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
    )


def test_install_publishes_only_complete_verified_asset(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"verified payload")
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    store = AssetStore(tmp_path / "store")

    installed = store.install(source_spec(source, checksum=f"sha256:{checksum}"))

    assert installed.path("data/payload.bin").read_bytes() == b"verified payload"
    assert store.status("example", "1") == "installed"
    assert not list((tmp_path / "store").glob(".example-*"))


def test_failed_install_leaves_no_false_installed_state(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    store = AssetStore(tmp_path / "store")

    with pytest.raises(ValueError, match="checksum mismatch"):
        store.install(source_spec(source, checksum="sha256:deadbeef"))

    assert store.status("example", "1") == "missing"
    installed = store.install(source_spec(source))
    assert installed.path("data/payload.bin").read_bytes() == b"payload"


def test_verify_detects_changed_and_extra_files(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    store = AssetStore(tmp_path / "store")
    installed = store.install(source_spec(source))
    installed.path("data/payload.bin").write_bytes(b"changed")

    with pytest.raises(AssetCorrupt, match="changed"):
        store.verify("example", "1")

    installed.path("data/payload.bin").write_bytes(b"payload")
    (installed.root / "extra").write_text("unexpected")
    with pytest.raises(AssetCorrupt, match="file set"):
        store.verify("example", "1")


def test_resolve_names_explicit_install_command(tmp_path: Path) -> None:
    store = AssetStore(tmp_path / "store")

    with pytest.raises(AssetNotInstalled, match="goldilocks assets install example"):
        store.resolve("example", "1")


def test_asset_paths_cannot_escape_store(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="contained"):
        AssetFile(role="payload", path="../escape", url="file:///tmp/source")
    store = AssetStore(tmp_path / "store")
    with pytest.raises(ValueError, match="one path component"):
        store.verify("../escape", "1")


def test_concurrent_installers_publish_one_valid_asset(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    store = AssetStore(tmp_path / "store")
    spec = source_spec(source)

    with ThreadPoolExecutor(max_workers=2) as executor:
        installed = list(executor.map(lambda _: store.install(spec), range(2)))

    assert installed[0].root == installed[1].root
    assert store.verify("example", "1").path("data/payload.bin").is_file()


def test_asset_root_uses_override_then_xdg(monkeypatch, tmp_path: Path) -> None:
    override = tmp_path / "override"
    monkeypatch.setenv("GOLDILOCKS_ASSET_ROOT", str(override))
    assert asset_root() == override

    monkeypatch.delenv("GOLDILOCKS_ASSET_ROOT")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert asset_root() == tmp_path / "xdg" / "goldilocks" / "assets"
