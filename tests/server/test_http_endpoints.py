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


def test_generate_publishes_bundle_and_returns_core_result_json(
    test_runtime, request_body, tmp_path
) -> None:
    """Pass body output_dir to the generate preset."""
    output_dir = tmp_path / "bundle"
    body = {**request_body, "output_dir": str(output_dir)}

    with TestClient(create_app(test_runtime)) as client:
        response = client.post("/generate", json=body)

    assert response.status_code == 200
    data = response.json()
    assert data["generated_files"][0]["path"] == "inputs/qe.in"
    assert data["bundle"]["path"] == str(output_dir)
    assert (output_dir / "inputs" / "qe.in").is_file()


def test_compute_returns_only_requested_records(test_runtime, request_body) -> None:
    """Expose arbitrary record queries through the compute endpoint."""
    body = {
        **request_body,
        "outputs": ["StructureAnalysisRecord", "ParameterAdvice"],
    }

    with TestClient(create_app(test_runtime)) as client:
        response = client.post("/compute", json=body)

    assert response.status_code == 200
    assert set(response.json()) == {"StructureAnalysisRecord", "ParameterAdvice"}
    assert response.json()["StructureAnalysisRecord"]["reduced_formula"] == "Si"


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
