from __future__ import annotations

import pytest

from goldilocks_core.server.http import create_app

TestClient = pytest.importorskip("fastapi.testclient").TestClient


def test_health_reports_liveness(test_service) -> None:
    """Return a minimal health response."""
    with TestClient(create_app(test_service)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_tasks_lists_registered_tasks(test_service) -> None:
    """Expose registered task descriptions with stable ids."""
    with TestClient(create_app(test_service)) as client:
        response = client.get("/tasks")

    assert response.status_code == 200
    tasks = response.json()["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["id"] == "scf_single_point"
    assert tasks[0]["name"] == "Single-point SCF"
    assert any(s["output_record_id"] == "k_points" for s in tasks[0]["stages"])


def test_codes_lists_available_codes(test_service) -> None:
    """Expose target DFT codes with registered writers."""
    with TestClient(create_app(test_service)) as client:
        response = client.get("/codes")

    assert response.status_code == 200
    assert "quantum_espresso" in response.json()["codes"]


def test_models_lists_registered_models(test_service) -> None:
    """Expose the QRF k-distance and CGCNN metallicity model specs."""
    with TestClient(create_app(test_service)) as client:
        response = client.get("/models")

    assert response.status_code == 200
    models = response.json()["models"]
    assert len(models) == 2
    qrf = next(m for m in models if m["target"] == "k_distance")
    assert qrf["name"] == "kpoints-goldilocks-QRF"
    cgcnn = next(m for m in models if m["target"] == "metallicity")
    assert cgcnn["name"] == "metallicity-goldilocks-CGCNN"
    assert cgcnn["model_type"] == "cgcnn"


def test_recommend_returns_core_result_json(test_service, request_body) -> None:
    """Expose the recommend preset as CoreResult JSON."""
    with TestClient(create_app(test_service)) as client:
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


def test_generate_returns_generated_files_without_bundle(
    test_service, request_body
) -> None:
    """Return generated files; output locations are server-managed."""
    with TestClient(create_app(test_service)) as client:
        response = client.post("/generate", json=request_body)

    assert response.status_code == 200
    data = response.json()
    assert data["generated_files"][0]["path"] == "inputs/qe.in"
    assert data["bundle"] is None


def test_path_form_structure_maps_to_422(test_service, tmp_path) -> None:
    """Reject a file-path structure; transports require inline content."""
    with TestClient(create_app(test_service)) as client:
        response = client.post(
            "/compute",
            json={"structure": str(tmp_path / "Si.cif"), "outputs": ["analysis"]},
        )

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"
    assert "do not accept file paths" in response.json()["error"]["message"]


def test_compute_returns_only_requested_records(test_service, request_body) -> None:
    """Expose arbitrary record queries through the compute endpoint."""
    body = {
        **request_body,
        "outputs": ["analysis", "advice"],
    }

    with TestClient(create_app(test_service)) as client:
        response = client.post("/compute", json=body)

    assert response.status_code == 200
    assert set(response.json()) == {"analysis", "advice"}
    assert response.json()["analysis"]["reduced_formula"] == "Si"


def test_request_error_maps_to_422_with_message(test_service, request_body) -> None:
    """Preserve parser error text in a client response."""
    body = {**request_body, "unknown": True}

    with TestClient(create_app(test_service)) as client:
        response = client.post("/recommend", json=body)

    assert response.status_code == 422
    assert "Unknown request fields" in response.json()["error"]["message"]


def test_unknown_task_maps_to_422_with_message(test_service, request_body) -> None:
    """Report an unknown task as invalid operator input."""
    body = {**request_body, "intent": {"task": "unsupported"}}

    with TestClient(create_app(test_service)) as client:
        response = client.post("/recommend", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_task"
    assert "No Core task registered" in response.json()["error"]["message"]


def test_unexpected_value_error_remains_a_500(
    test_service, request_body, monkeypatch
) -> None:
    """Do not mislabel an internal ValueError as an operator error."""

    def raise_unexpected(service, request):
        del service, request
        raise ValueError("unexpected internal defect")

    monkeypatch.setattr(type(test_service), "run_preset", raise_unexpected)

    with TestClient(create_app(test_service), raise_server_exceptions=False) as client:
        response = client.post("/recommend", json=request_body)

    assert response.status_code == 500


def test_compute_requires_outputs(test_service, request_body) -> None:
    """Reject compute calls that do not select records."""
    with TestClient(create_app(test_service)) as client:
        response = client.post("/compute", json=request_body)

    assert response.status_code == 422
    assert "requires 'outputs'" in response.json()["error"]["message"]


def test_dimensionality_error_maps_to_422(
    test_service, request_body, monkeypatch
) -> None:
    """Map a stage DimensionalityClassificationError to a 422 response."""
    from goldilocks_core.analysis import DimensionalityClassificationError

    def raise_dimensionality(structure, *, metallicity_classifier):
        raise DimensionalityClassificationError(structure)

    monkeypatch.setattr(
        "goldilocks_core.runtime.scf.analyze_structure", raise_dimensionality
    )

    with TestClient(create_app(test_service)) as client:
        response = client.post("/recommend", json=request_body)

    assert response.status_code == 422
    assert "Could not classify dimensionality" in response.json()["error"]["message"]
