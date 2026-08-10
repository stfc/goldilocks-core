from __future__ import annotations

import pytest

from goldilocks_core.server.http import create_app

TestClient = pytest.importorskip("fastapi.testclient").TestClient


def test_health_reports_liveness(test_runtime) -> None:
    """Return a minimal health response."""
    with TestClient(create_app(test_runtime)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_recommend_returns_core_result_json(test_runtime, request_body) -> None:
    """Expose the recommend preset as CoreResult JSON."""
    with TestClient(create_app(test_runtime)) as client:
        response = client.post("/recommend", json=request_body)

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {
        "intent",
        "analysis",
        "advice",
        "k_points",
        "selection",
        "generated_files",
        "warnings",
        "bundle",
    }
    assert data["analysis"]["reduced_formula"] == "Si"
    assert data["k_points"]["grid"] == [3, 3, 3]
    assert data["generated_files"] == []


def test_generate_returns_contents_and_writes_no_caller_path(
    test_runtime, request_body
) -> None:
    """Return generated contents; the browser never supplies an output path."""
    with TestClient(create_app(test_runtime)) as client:
        response = client.post("/generate", json=request_body)

    assert response.status_code == 200
    data = response.json()
    assert data["generated_files"][0]["path"] == "inputs/qe.in"
    assert data["bundle"] is None


def test_generate_rejects_client_output_dir(test_runtime, request_body) -> None:
    """Reject a client-supplied output_dir as a structured invalid_request."""
    body = {**request_body, "output_dir": "/tmp/bundle"}

    with TestClient(create_app(test_runtime)) as client:
        response = client.post("/generate", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


def test_recommend_rejects_server_path_concepts(test_runtime, request_body) -> None:
    """Reject pseudo_root, path-shaped structure, and pseudo filepath."""
    with TestClient(create_app(test_runtime)) as client:
        pseudo_root = client.post(
            "/recommend", json={**request_body, "pseudo_root": "/pseudo"}
        )
        structure_path = client.post("/recommend", json={"structure": "/pseudo/Si.cif"})
        filepath = client.post(
            "/recommend",
            json={
                **request_body,
                "pseudo_metadata": [
                    {**request_body["pseudo_metadata"][0], "filepath": "/pseudo/Si.UPF"}
                ],
            },
        )

    # Path-shaped structure is rejected by the inline-only schema.
    assert structure_path.status_code == 422
    # Server-path concepts that pass the schema are rejected as structured errors.
    for response in (pseudo_root, filepath):
        assert response.status_code == 422
        assert response.json()["error"]["kind"] == "invalid_request"


def test_compute_returns_only_requested_records(test_runtime, request_body) -> None:
    """Expose arbitrary record queries through the compute endpoint."""
    body = {
        **request_body,
        "outputs": ["analysis", "advice"],
    }

    with TestClient(create_app(test_runtime)) as client:
        response = client.post("/compute", json=body)

    assert response.status_code == 200
    data = response.json()
    assert data["analysis"]["reduced_formula"] == "Si"
    assert data["advice"]["smearing"] is not None
    # The typed response has a stable shape: unrequested records are null.
    assert data["k_points"] is None
    assert data["selection"] is None
    assert data["generated_files"] is None


def test_request_error_maps_to_422_with_message(test_runtime, request_body) -> None:
    """Preserve parser error text in a client response."""
    body = {**request_body, "unknown": True}

    with TestClient(create_app(test_runtime)) as client:
        response = client.post("/recommend", json=body)

    assert response.status_code == 422
    assert "Unknown request fields" in response.json()["error"]["message"]


def test_stage_value_error_maps_to_400_with_message(test_runtime, request_body) -> None:
    """Preserve stage ValueError text in a 4xx response."""
    body = {**request_body, "intent": {"task": "unsupported"}}

    with TestClient(create_app(test_runtime)) as client:
        response = client.post("/recommend", json=body)

    assert response.status_code == 400
    assert "No Core task registered" in response.json()["error"]["message"]


def test_compute_requires_outputs(test_runtime, request_body) -> None:
    """Reject compute calls that do not select records."""
    with TestClient(create_app(test_runtime)) as client:
        response = client.post("/compute", json=request_body)

    assert response.status_code == 422
    assert "requires 'outputs'" in response.json()["error"]["message"]
