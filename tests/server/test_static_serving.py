"""Tests for serving the built Workbench from FastAPI."""

import pytest

from goldilocks_core.server.config import WEB_DIST_ENV
from goldilocks_core.server.http import create_app

TestClient = pytest.importorskip("fastapi.testclient").TestClient


def _write_build(tmp_path, *, index: str = "<!doctype html>") -> None:
    (tmp_path / "index.html").write_text(index, encoding="utf-8")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log('app')", encoding="utf-8")


def test_no_static_mount_without_a_build_dir(tmp_path, monkeypatch) -> None:
    """Without a build directory, API routes serve and unknown paths 404."""
    missing = tmp_path / "missing"
    monkeypatch.setenv(WEB_DIST_ENV, str(missing))

    with TestClient(create_app()) as client:
        health = client.get("/health")
        unknown = client.get("/nope")

    assert health.status_code == 200
    assert unknown.status_code == 404


def test_static_serves_index_and_assets(tmp_path, monkeypatch) -> None:
    """A present build directory serves index.html and its hashed assets."""
    _write_build(tmp_path, index="<html>goldilocks</html>")
    monkeypatch.setenv(WEB_DIST_ENV, str(tmp_path))

    with TestClient(create_app()) as client:
        root = client.get("/")
        asset = client.get("/assets/app.js")

    assert root.status_code == 200
    assert root.text == "<html>goldilocks</html>"
    assert asset.status_code == 200
    assert asset.text == "console.log('app')"


def test_static_mount_does_not_shadow_api_routes(tmp_path, monkeypatch) -> None:
    """API and health routes keep precedence; unknown GET paths are a real 404."""
    _write_build(tmp_path, index="<html>goldilocks</html>")
    monkeypatch.setenv(WEB_DIST_ENV, str(tmp_path))

    with TestClient(create_app()) as client:
        health = client.get("/health")
        tasks = client.get("/tasks")
        root = client.get("/")
        missing = client.get("/some/client/route")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert tasks.status_code == 200
    assert tasks.json()["tasks"]
    # The app has no client router: `/` serves the shell, anything else 404s.
    assert root.status_code == 200
    assert root.text == "<html>goldilocks</html>"
    assert missing.status_code == 404
