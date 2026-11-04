from __future__ import annotations

import os
from unittest.mock import patch

from goldilocks_core.assets.records import AssetFile, AssetInstallation, AssetSpec
from goldilocks_core.assets.store import AssetStore
from goldilocks_core.server.readiness import AssetReadiness


def test_readiness_rechecks_when_installed_asset_state_changes(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"healthy")
    spec = AssetSpec(
        id="models/fixture",
        version="1",
        files=(
            AssetFile(
                role="data",
                path="data.bin",
                url=source.as_uri(),
            ),
        ),
    )
    monkeypatch.setattr(
        "goldilocks_core.server.readiness.catalogue", lambda **kwargs: {}
    )
    monkeypatch.setattr(
        "goldilocks_core.server.readiness.references",
        lambda profile, entries: (AssetInstallation(spec),),
    )
    store = AssetStore(tmp_path / "assets")
    readiness = AssetReadiness(store)

    assert readiness.check().state == "missing"
    installed = store.install(spec)
    assert readiness.check().ready

    data = installed.path("data.bin")
    modified = data.stat().st_mtime_ns + 1
    data.write_bytes(b"damaged")
    os.utime(data, ns=(modified, modified))

    report = readiness.check()
    assert not report.ready
    assert report.state == "corrupt"


def test_readiness_check_never_walks_the_tree(tmp_path, monkeypatch) -> None:
    """The fix itself (v2 epic 8, #8, issue evidence #4): the old
    implementation called ``Path.rglob`` on every single ``check()``.
    The new one only stats the manifest and the files it lists.

    ``verify_spec`` itself still legitimately calls ``rglob`` once, to
    compare the actual directory listing against the manifest -- that
    is real validation, not the cache-invalidation heuristic this fix
    targets. So the first ``check()`` (a cache miss -- state starts as
    ``None``) runs unpatched; only the *second* call (a cache hit, since
    nothing changed) must avoid ``rglob`` entirely.
    """
    source = tmp_path / "source.bin"
    source.write_bytes(b"healthy")
    spec = AssetSpec(
        id="models/fixture",
        version="1",
        files=(AssetFile(role="data", path="data.bin", url=source.as_uri()),),
    )
    monkeypatch.setattr(
        "goldilocks_core.server.readiness.catalogue", lambda **kwargs: {}
    )
    monkeypatch.setattr(
        "goldilocks_core.server.readiness.references",
        lambda profile, entries: (AssetInstallation(spec),),
    )
    store = AssetStore(tmp_path / "assets")
    store.install(spec)
    readiness = AssetReadiness(store)
    assert readiness.check().ready  # cache miss: real verify_spec runs once

    with patch("pathlib.Path.rglob") as rglob:
        assert readiness.check().ready  # cache hit: must not walk anything

    rglob.assert_not_called()


def test_readiness_treats_a_missing_manifest_as_changed_state(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"healthy")
    spec = AssetSpec(
        id="models/fixture",
        version="1",
        files=(AssetFile(role="data", path="data.bin", url=source.as_uri()),),
    )
    monkeypatch.setattr(
        "goldilocks_core.server.readiness.catalogue", lambda **kwargs: {}
    )
    monkeypatch.setattr(
        "goldilocks_core.server.readiness.references",
        lambda profile, entries: (AssetInstallation(spec),),
    )
    store = AssetStore(tmp_path / "assets")
    installed = store.install(spec)
    readiness = AssetReadiness(store)
    assert readiness.check().ready

    (installed.root / "manifest.json").unlink()

    report = readiness.check()
    assert not report.ready
    # AssetStore.verify treats a missing manifest as "not installed",
    # not "corrupt" -- this test only needs the cache to notice *some*
    # change and re-verify; the resulting classification is verify_spec's
    # call, not this cache layer's.
    assert report.state == "missing"
