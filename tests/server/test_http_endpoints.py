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


def test_recommend_treats_null_outputs_as_omitted(test_service, request_body) -> None:
    with TestClient(create_app(test_service)) as client:
        response = client.post(
            "/recommend",
            json={**request_body, "outputs": None},
        )

    assert response.status_code == 200
    assert response.json()["analysis"]["reduced_formula"] == "Si"


def test_generate_uses_core_publication_and_returns_result_json(
    test_service, request_body, tmp_path
) -> None:
    """Return generated files; output locations are server-managed."""
    with TestClient(create_app(test_service)) as client:
        response = client.post("/generate", json=request_body)

    assert response.status_code == 200
    data = response.json()
    assert data["generated_files"][0]["path"] == "inputs/qe.in"
    assert data["bundle"]["path"] == str(output_dir)
    assert (output_dir / "inputs" / "qe.in").is_file()
    assert (output_dir / "goldilocks.json").is_file()
    assert not (output_dir / "manifest.json").exists()


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
    assert "Unknown draft fields" in response.json()["error"]["message"]


def test_unknown_task_maps_to_422_with_message(test_service, request_body) -> None:
    """Report an unknown task as invalid operator input."""
    body = {**request_body, "intent": {"task": "unsupported"}}

    with TestClient(create_app(test_service)) as client:
        response = client.post("/recommend", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_task"
    assert "No Core task registered" in response.json()["error"]["message"]


def test_asset_corrupt_maps_to_424(test_service, request_body, monkeypatch) -> None:
    """Expose a corrupt installed asset as a deployment integrity error."""
    from goldilocks_core.assets import AssetCorrupt

    def raise_corrupt(service, request, *, output=None):
        del service, request, output
        raise AssetCorrupt("installed pseudopotential manifest is invalid")

    monkeypatch.setattr(type(test_service), "compute", raise_corrupt)

    with TestClient(create_app(test_service)) as client:
        response = client.post("/recommend", json=request_body)

    assert response.status_code == 424
    assert response.json()["error"]["kind"] == "asset_corrupt"
    assert "manifest is invalid" in response.json()["error"]["message"]


def test_asset_not_installed_maps_to_424(
    test_service, request_body, tmp_path, monkeypatch
) -> None:
    """Expose a missing runtime asset as a structured dependency error."""
    from goldilocks_core.assets import AssetNotInstalled, AssetReference

    reference = AssetReference("pseudopotentials/pseudodojo", "0.4")

    def raise_missing(service, request):
        del service, request
        raise AssetNotInstalled(reference, tmp_path / "assets")

    monkeypatch.setattr(type(test_service), "run_preset", raise_missing)

    with TestClient(create_app(test_service)) as client:
        response = client.post("/recommend", json=request_body)

    assert response.status_code == 424
    assert response.json()["error"]["kind"] == "asset_not_installed"
    assert response.json()["error"]["asset_id"] == "pseudopotentials/pseudodojo"
    assert response.json()["error"]["version"] == "0.4"


def test_pseudo_table_mismatch_maps_to_422(
    test_service, request_body, monkeypatch
) -> None:
    """Expose a table that cannot satisfy the request as invalid input."""
    from goldilocks_core.pseudo.source import PseudoTableMismatch

    def raise_mismatch(service, request):
        del service, request
        raise PseudoTableMismatch("table cannot satisfy the request")

    monkeypatch.setattr(type(test_service), "run_preset", raise_mismatch)

    with TestClient(create_app(test_service)) as client:
        response = client.post("/recommend", json=request_body)

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "pseudo_table_mismatch"
    assert "cannot satisfy" in response.json()["error"]["message"]


def test_unexpected_value_error_remains_a_500(
    test_service, request_body, monkeypatch
) -> None:
    """Do not mislabel an internal ValueError as an operator error."""

    def raise_unexpected(service, request):
        del service, request
        raise ValueError("unexpected internal defect")

    monkeypatch.setattr(type(test_service), "compute", raise_unexpected)

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
