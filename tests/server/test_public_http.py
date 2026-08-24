from __future__ import annotations

import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from goldilocks_core.runtime import Service
from goldilocks_core.server.http import create_app

TestClient = pytest.importorskip("fastapi.testclient").TestClient


def test_http_capabilities_returns_canonical_core_document(test_service) -> None:
    with TestClient(create_app(test_service)) as client:
        response = client.get("/capabilities")

    assert response.status_code == 200
    document = response.json()
    assert document["tasks"][0]["id"] == "scf_single_point"
    assert {preset["id"] for preset in document["tasks"][0]["presets"]} == {
        "recommend",
        "generate",
    }
    assert "quantum_espresso" in document["target_codes"]


def test_http_inspect_returns_canonical_structure_inspection(
    test_service,
    sample_structure_text: str,
) -> None:
    with TestClient(create_app(test_service)) as client:
        response = client.post(
            "/inspect",
            json={
                "source": {
                    "name": "uploaded-silicon.cif",
                    "content": sample_structure_text,
                    "format": "cif",
                }
            },
        )

    assert response.status_code == 200
    inspection = response.json()
    assert inspection["source"]["name"] == "uploaded-silicon.cif"
    assert inspection["structure"]["reduced_formula"] == "Si"
    assert inspection["canonical_cif"].startswith("# generated using pymatgen")


def test_http_compute_memory_returns_the_canonical_result(
    test_service,
    sample_structure_text: str,
) -> None:
    with TestClient(create_app(test_service)) as client:
        response = client.post(
            "/compute",
            json={
                "draft": {
                    "structure": {
                        "name": "Si.cif",
                        "content": sample_structure_text,
                        "format": "cif",
                    },
                    "hints": {"k_grid": [3, 3, 3]},
                },
                "selection": {"records": ["k_points"]},
                "output": {"kind": "memory"},
            },
        )

    assert response.status_code == 200
    result = response.json()
    assert result["schema_version"] == 1
    assert result["selection"] == {"records": ["k_points"]}
    assert result["records"]["k_points"]["grid"] == [3, 3, 3]
    assert result["publication"] is None


def test_http_compute_archive_returns_an_unstored_zip(
    publishable_service,
    sample_structure_text: str,
    tmp_path,
) -> None:
    with TestClient(create_app(publishable_service)) as client:
        response = client.post(
            "/compute",
            json={
                "draft": {
                    "structure": {
                        "name": "Si.cif",
                        "content": sample_structure_text,
                        "format": "cif",
                    },
                    "hints": {"k_grid": [3, 3, 3]},
                    "pseudo_table": "fixture-table",
                },
                "selection": {"preset": "generate"},
                "output": {"kind": "archive"},
            },
        )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"] == (
        'attachment; filename="goldilocks-inputs.zip"'
    )
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert "inputs/qe.in" in archive.namelist()
        assert "goldilocks.json" in archive.namelist()
    assert not list(tmp_path.rglob("goldilocks-inputs.zip"))
    assert not list(tmp_path.rglob("goldilocks_out"))


def test_http_capacity_guards_only_compute(
    sample_structure_text: str,
) -> None:
    service = _BlockingService()
    body = {
        "draft": {
            "structure": {
                "name": "Si.cif",
                "content": sample_structure_text,
                "format": "cif",
            },
            "hints": {"k_grid": [3, 3, 3]},
        },
        "selection": {"records": ["k_points"]},
        "output": {"kind": "memory"},
    }
    try:
        with (
            TestClient(create_app(service, compute_wait_seconds=0.01)) as client,
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            first = pool.submit(client.post, "/compute", json=body)
            assert service.entered.wait(timeout=1)
            busy = client.post("/compute", json=body)
            capabilities = client.get("/capabilities")
            inspection = client.post(
                "/inspect", json={"source": body["draft"]["structure"]}
            )
            health = client.get("/health")
            service.release.set()

            assert first.result(timeout=2).status_code == 200
        assert busy.status_code == 503
        assert busy.json()["error"]["kind"] == "server_busy"
        assert capabilities.status_code == 200
        assert inspection.status_code == 200
        assert health.json() == {"status": "ok"}
    finally:
        service.release.set()
        service.close()


def test_http_lets_core_report_unknown_domain_values(
    test_service,
    sample_structure_text: str,
) -> None:
    with TestClient(create_app(test_service)) as client:
        response = client.post(
            "/compute",
            json={
                "draft": {
                    "structure": {
                        "name": "Si.cif",
                        "content": sample_structure_text,
                    },
                    "intent": {"task": "unsupported"},
                    "hints": {"k_grid": [3, 3, 3]},
                },
                "selection": {"records": ["k_points"]},
                "output": {"kind": "memory"},
            },
        )

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_task"
    assert "No Core task registered" in response.json()["error"]["message"]


def test_http_preserves_readiness_and_static_serving(test_service, tmp_path) -> None:
    static_root = tmp_path / "dist"
    static_root.mkdir()
    (static_root / "index.html").write_text(
        "<main>Goldilocks Workbench</main>", encoding="utf-8"
    )

    with TestClient(create_app(test_service, static_root=static_root)) as client:
        readiness = client.get("/ready")
        index = client.get("/")
        capabilities = client.get("/capabilities")

    assert readiness.status_code in {200, 503}
    if readiness.status_code == 503:
        assert readiness.json()["error"]["kind"] == "assets_unavailable"
    assert index.status_code == 200
    assert index.text == "<main>Goldilocks Workbench</main>"
    assert capabilities.status_code == 200


def test_http_does_not_relabel_unexpected_core_defects(
    sample_structure_text: str,
) -> None:
    service = _DefectiveService()
    try:
        with TestClient(create_app(service), raise_server_exceptions=False) as client:
            response = client.post(
                "/compute",
                json={
                    "draft": {
                        "structure": {
                            "name": "Si.cif",
                            "content": sample_structure_text,
                        },
                        "hints": {"k_grid": [3, 3, 3]},
                    },
                    "selection": {"records": ["k_points"]},
                    "output": {"kind": "memory"},
                },
            )
    finally:
        service.close()

    assert response.status_code == 500


def test_http_rejects_non_inline_sources_and_unknown_fields(test_service) -> None:
    with TestClient(create_app(test_service)) as client:
        path_source = client.post(
            "/inspect", json={"source": "/server/inaccessible.cif"}
        )
        unknown = client.post(
            "/compute",
            json={
                "draft": {"structure": {"name": "Si.cif", "content": ""}},
                "selection": {"records": ["analysis"]},
                "output": {"kind": "memory"},
                "mode": "recommend",
            },
        )
        directory = client.post(
            "/compute",
            json={
                "draft": {"structure": {"name": "Si.cif", "content": ""}},
                "selection": {"records": ["analysis"]},
                "output": {"kind": "directory", "path": "/server/output"},
            },
        )

    assert path_source.status_code == 422
    assert path_source.json()["error"]["kind"] == "invalid_request"
    assert (
        path_source.json()["error"]["details"]["validation_errors"][0]["path"]
        == "body.source"
    )
    assert unknown.status_code == 422
    assert any(
        item["path"] == "body.mode"
        for item in unknown.json()["error"]["details"]["validation_errors"]
    )
    assert directory.status_code == 422
    assert directory.json()["error"]["kind"] == "invalid_request"
    assert "/server/output" not in directory.text


def test_openapi_describes_canonical_json_and_archive_contracts(test_service) -> None:
    with TestClient(create_app(test_service)) as client:
        schema = client.get("/openapi.json").json()

    assert {"/capabilities", "/inspect", "/compute", "/health", "/ready"} <= set(
        schema["paths"]
    )
    assert not {
        "/tasks",
        "/codes",
        "/models",
        "/recommend",
        "/generate",
        "/api/workbench/structure",
    } & set(schema["paths"])
    capabilities = schema["paths"]["/capabilities"]["get"]["responses"]["200"]
    assert capabilities["content"]["application/json"]["schema"]["$ref"].endswith(
        "/Capabilities"
    )
    inspection = schema["paths"]["/inspect"]["post"]
    assert inspection["requestBody"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/StructureInspectionRequest")
    assert inspection["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/StructureInspection")
    compute = schema["paths"]["/compute"]["post"]
    assert compute["requestBody"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/ComputeRequest")
    assert compute["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/ComputationResult")
    assert compute["responses"]["200"]["content"]["application/zip"]["schema"] == {
        "type": "string",
        "format": "binary",
    }
    assert compute["responses"]["422"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/ErrorResponse")


def test_generated_openapi_and_typescript_match_the_public_contract(
    test_service,
) -> None:
    roots = (Path(__file__).resolve().parents[2], Path.cwd(), Path.cwd().parent)
    root = next(candidate for candidate in roots if (candidate / "web").is_dir())
    committed = json.loads((root / "web" / "openapi.json").read_text())
    with TestClient(create_app(test_service)) as client:
        generated = client.get("/openapi.json").json()

    assert committed == generated
    typescript = (root / "web" / "src" / "api" / "schema.d.ts").read_text()
    assert "readonly ComputeRequest:" in typescript
    assert "readonly ComputationResult:" in typescript
    assert "readonly StructureInspection:" in typescript
    assert "GuidedRequest" not in typescript
    assert "RecommendationResponse" not in typescript


def test_http_exposes_no_legacy_or_browser_scientific_routes(test_service) -> None:
    with TestClient(create_app(test_service)) as client:
        responses = {
            path: client.get(path)
            if path in {"/tasks", "/codes", "/models"}
            else client.post(path, json={})
            for path in (
                "/tasks",
                "/codes",
                "/models",
                "/recommend",
                "/generate",
                "/api/workbench/structure",
                "/api/workbench/recommendation",
                "/api/workbench/archive",
            )
        }

    assert {
        path for path, response in responses.items() if response.status_code != 404
    } == set()


class _DefectiveService(Service):
    def compute(self, request, *, output=None):
        del request, output
        raise ValueError("unexpected internal defect")


class _BlockingService(Service):
    def __init__(self) -> None:
        super().__init__()
        self.entered = Event()
        self.release = Event()

    def compute(self, request, *, output=None):
        self.entered.set()
        if not self.release.wait(timeout=2):
            raise RuntimeError("test did not release computation")
        return super().compute(request, output=output)
