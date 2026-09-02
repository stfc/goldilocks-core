from __future__ import annotations

import os

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
