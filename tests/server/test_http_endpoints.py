from __future__ import annotations

import pytest

from goldilocks_core.server.http import create_app

TestClient = pytest.importorskip("fastapi.testclient").TestClient


def test_health_reports_liveness(test_service) -> None:
    with TestClient(create_app(test_service)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_tasks_lists_registered_tasks(test_service) -> None:
    with TestClient(create_app(test_service)) as client:
        response = client.get("/tasks")

    assert response.status_code == 200
    tasks = response.json()["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["id"] == "scf_single_point"
    assert tasks[0]["name"] == "Single-point SCF"
    assert any(s["output_record_id"] == "k_points" for s in tasks[0]["stages"])


def test_codes_lists_available_codes(test_service) -> None:
    with TestClient(create_app(test_service)) as client:
        response = client.get("/codes")

    assert response.status_code == 200
    assert "quantum_espresso" in response.json()["codes"]


def test_models_lists_registered_models(test_service) -> None:
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


def test_generate_publishes_bundle_and_returns_core_result_json(
    test_service, request_body, tmp_path
) -> None:
    output_dir = tmp_path / "bundle"
    body = {**request_body, "output_dir": str(output_dir)}

    with TestClient(create_app(test_service)) as client:
        response = client.post("/generate", json=body)

    assert response.status_code == 200
    data = response.json()
    assert data["generated_files"][0]["path"] == "inputs/qe.in"
    assert data["bundle"]["path"] == str(output_dir)
    assert (output_dir / "inputs" / "qe.in").is_file()


def test_compute_returns_only_requested_records(test_service, request_body) -> None:
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
    body = {**request_body, "unknown": True}

    with TestClient(create_app(test_service)) as client:
        response = client.post("/recommend", json=body)

    assert response.status_code == 422
    assert "Unknown request fields" in response.json()["error"]["message"]


def test_unknown_task_maps_to_422_with_message(test_service, request_body) -> None:
    body = {**request_body, "intent": {"task": "unsupported"}}

    with TestClient(create_app(test_service)) as client:
        response = client.post("/recommend", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_task"
    assert "No Core task registered" in response.json()["error"]["message"]


def test_generate_without_installed_pseudopotentials_maps_to_424(
    test_service, request_body
) -> None:
    body = {
        name: value for name, value in request_body.items() if name != "pseudo_metadata"
    }

    with TestClient(create_app(test_service)) as client:
        response = client.post("/generate", json=body)

    assert response.status_code == 424
    assert response.json()["error"]["kind"] == "asset_not_installed"
    assert response.json()["error"]["asset_id"] == "pseudodojo-pbesol-efficiency-sr"
    assert response.json()["error"]["root"] == str(
        test_service.runtime.asset_store.root
    )


def test_pseudo_table_mismatch_maps_to_422(test_service, request_body) -> None:
    body = {
        name: value for name, value in request_body.items() if name != "pseudo_metadata"
    }
    body["pseudo_table"] = "sssp-pbe-precision-sr"

    with TestClient(create_app(test_service)) as client:
        response = client.post("/recommend", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "pseudo_table_mismatch"
    assert "functional" in response.json()["error"]["message"]


def test_asset_corrupt_maps_to_424(test_service, request_body, monkeypatch) -> None:
    from goldilocks_core.assets import AssetCorrupt

    def raise_corrupt(service, request):
        del service, request
        raise AssetCorrupt("installed pseudopotential manifest is invalid")

    monkeypatch.setattr(type(test_service), "run_preset", raise_corrupt)

    with TestClient(create_app(test_service)) as client:
        response = client.post("/recommend", json=request_body)

    assert response.status_code == 424
    assert response.json()["error"]["kind"] == "asset_corrupt"
    assert "manifest is invalid" in response.json()["error"]["message"]


def test_existing_bundle_destination_maps_to_409(
    test_service, request_body, tmp_path
) -> None:
    output_dir = tmp_path / "bundle"
    output_dir.mkdir()

    with TestClient(create_app(test_service)) as client:
        response = client.post(
            "/generate",
            json={**request_body, "output_dir": str(output_dir)},
        )

    assert response.status_code == 409
    assert response.json()["error"]["kind"] == "output_conflict"


def test_empty_bundle_destination_maps_to_422(test_service, request_body) -> None:
    with TestClient(create_app(test_service)) as client:
        response = client.post(
            "/generate",
            json={**request_body, "output_dir": ""},
        )

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


def test_directory_structure_path_maps_to_422(test_service, tmp_path) -> None:
    with TestClient(create_app(test_service)) as client:
        response = client.post(
            "/compute",
            json={"structure": str(tmp_path), "outputs": ["analysis"]},
        )

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_structure"


def test_unexpected_value_error_remains_a_500(
    test_service, request_body, monkeypatch
) -> None:

    def raise_unexpected(service, request):
        del service, request
        raise ValueError("unexpected internal defect")

    monkeypatch.setattr(type(test_service), "run_preset", raise_unexpected)

    with TestClient(create_app(test_service), raise_server_exceptions=False) as client:
        response = client.post("/recommend", json=request_body)

    assert response.status_code == 500


def test_compute_requires_outputs(test_service, request_body) -> None:
    with TestClient(create_app(test_service)) as client:
        response = client.post("/compute", json=request_body)

    assert response.status_code == 422
    assert "requires 'outputs'" in response.json()["error"]["message"]


def test_dimensionality_error_maps_to_422(
    test_service, request_body, monkeypatch
) -> None:
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
