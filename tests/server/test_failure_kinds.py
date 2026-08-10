"""Tests for the stable structured HTTP failure contract."""

import pytest

from goldilocks_core.server.http import create_app

TestClient = pytest.importorskip("fastapi.testclient").TestClient


def _error_of(client: TestClient, method: str, path: str, **kwargs) -> dict:
    """Perform a request and return its structured error envelope."""
    response = getattr(client, method)(path, **kwargs)
    body = response.json()
    assert response.status_code >= 400
    return response.status_code, body["error"]


def _client(*, raise_server_exceptions: bool = True):
    """Build a TestClient around a fresh app."""
    return TestClient(create_app(), raise_server_exceptions=raise_server_exceptions)


def test_request_error_carries_kind_status_message_details(
    test_runtime, request_body
) -> None:
    """Return a stable invalid_request envelope for a malformed request."""
    body = {**request_body, "surprise": True}
    with TestClient(create_app(test_runtime)) as client:
        status, error = _error_of(client, "post", "/recommend", json=body)

    assert status == 422
    assert error["kind"] == "invalid_request"
    assert "Unknown request fields" in error["message"]
    assert error["status"] == 422
    assert "details" in error


def test_stage_error_carries_kind_status_message(test_runtime, request_body) -> None:
    """Return a stable stage_error envelope for a domain failure."""
    body = {**request_body, "intent": {"task": "unsupported"}}
    with TestClient(create_app(test_runtime)) as client:
        status, error = _error_of(client, "post", "/recommend", json=body)

    assert status == 400
    assert error["kind"] == "stage_error"
    assert error["status"] == 400


def test_not_found_maps_to_structured_envelope(
    test_runtime, monkeypatch, sample_structure_text: str
) -> None:
    """Return a stable not_found envelope for a missing server resource."""
    import goldilocks_core.server.http as http_module

    def missing(request, runtime):
        raise FileNotFoundError("Missing pseudo resource")

    monkeypatch.setattr(http_module, "run_core_job", missing)
    with _client(raise_server_exceptions=False) as client:
        status, error = _error_of(
            client,
            "post",
            "/recommend",
            json={"structure": {"content": sample_structure_text, "format": "cif"}},
        )

    assert status == 404
    assert error["kind"] == "not_found"
    assert error["status"] == 404


def test_unexpected_failure_is_500_with_structured_body(
    test_runtime, request_body, monkeypatch
) -> None:
    """Surface unexpected exceptions as a noisy structured 500."""
    import goldilocks_core.server.http as http_module

    def boom(request, runtime):
        raise RuntimeError("internal catastrophe")

    monkeypatch.setattr(http_module, "run_core_job", boom)
    with _client(raise_server_exceptions=False) as client:
        status, error = _error_of(client, "post", "/recommend", json=request_body)

    assert status == 500
    assert error["kind"] == "unexpected"
    assert error["status"] == 500
