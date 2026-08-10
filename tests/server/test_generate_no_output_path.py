"""Tests for browser-safe generate: contents returned, no caller path written."""

import pytest

from goldilocks_core.server.http import create_app

TestClient = pytest.importorskip("fastapi.testclient").TestClient


def test_generate_without_output_dir_returns_contents_and_writes_nothing(
    test_runtime, request_body
) -> None:
    """Return generated file contents without writing any caller path."""
    with TestClient(create_app(test_runtime)) as client:
        response = client.post("/generate", json=request_body)

    assert response.status_code == 200
    data = response.json()
    assert data["generated_files"][0]["path"] == "inputs/qe.in"
    assert data["generated_files"][0]["content"]
    assert data["bundle"] is None
