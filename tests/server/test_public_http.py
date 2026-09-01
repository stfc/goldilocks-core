from __future__ import annotations

import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
from threading import Event, Lock

import pytest

from goldilocks_core.assets import AssetCorrupt, AssetNotInstalled, AssetReference
from goldilocks_core.contracts import KPointSelection, Provenance
from goldilocks_core.runtime import Runtime, Service
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


def test_http_compute_returns_one_reviewed_result_without_an_unrequested_archive(
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
            },
        )

    assert response.status_code == 200
    parts = _multipart_parts(response)
    assert set(parts) == {"result"}
    assert parts["result"][0] == "application/json"
    result = json.loads(parts["result"][2])
    assert result["schema_version"] == 1
    assert result["selection"] == {"records": ["k_points"]}
    assert result["records"]["k_points"]["grid"] == [3, 3, 3]
    assert result["publication"] is None


def test_http_selects_and_returns_custom_registered_records(
    custom_record_service,
    sample_structure_text: str,
) -> None:
    app = create_app(custom_record_service)
    with TestClient(app) as client:
        response = client.post(
            "/compute",
            json={
                "draft": {
                    "structure": {
                        "name": "Si.cif",
                        "content": sample_structure_text,
                        "format": "cif",
                    },
                    "intent": {"task": "custom_task"},
                },
                "selection": {"records": ["custom_summary"]},
            },
        )
        schema = client.get("/openapi.json").json()

    assert response.status_code == 200, response.text
    result = json.loads(_multipart_parts(response)["result"][2])
    assert result["records"] == {"custom_summary": {"value": "custom result"}}
    records = schema["components"]["schemas"]["Records"]
    assert "custom_summary" in records["properties"]
    custom_ref = records["properties"]["custom_summary"]["$ref"].rsplit("/", 1)[-1]
    assert schema["components"]["schemas"][custom_ref]["properties"]["value"] == {
        "title": "Value",
        "type": "string",
    }
    analysis_ref = records["properties"]["analysis"]["$ref"].rsplit("/", 1)[-1]
    assert (
        "reduced_formula" in schema["components"]["schemas"][analysis_ref]["properties"]
    )


def test_http_returns_the_exact_archive_with_its_reviewed_result(
    publishable_service,
    sample_structure_text: str,
    tmp_path,
) -> None:
    service = _CountingService(publishable_service)
    with TestClient(create_app(service)) as client:
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
            },
        )

    assert response.status_code == 200, response.text
    assert service.compute_calls == 1
    parts = _multipart_parts(response)
    assert set(parts) == {"result", "archive"}
    assert parts["archive"][:2] == (
        "application/zip",
        "goldilocks-inputs.zip",
    )
    reviewed = json.loads(parts["result"][2])
    assert reviewed["draft"]["pseudo_table"] == "fixture-table"
    assert reviewed["draft"]["pseudo_root"] is None
    assert reviewed["draft"]["pseudo_metadata"] is None
    assert reviewed["draft"]["kmesh_model"] is None
    with zipfile.ZipFile(io.BytesIO(parts["archive"][2])) as archive:
        assert "inputs/qe.in" in archive.namelist()
        manifest = json.loads(archive.read("goldilocks.json"))
    assert manifest["records"]["k_points"] == reviewed["records"]["k_points"]
    assert not list(tmp_path.rglob("goldilocks-inputs.zip"))
    assert not list(tmp_path.rglob("goldilocks_out"))


def test_http_runs_concurrent_computations(
    sample_structure_text: str,
) -> None:
    backend = _BlockingKmeshBackend(expected_calls=2)
    runtime = Runtime(kmesh_service=backend)
    service = Service(runtime)
    body = {
        "draft": {
            "structure": {
                "name": "Si.cif",
                "content": sample_structure_text,
                "format": "cif",
            },
        },
        "selection": {"records": ["k_points"]},
    }
    try:
        with (
            TestClient(create_app(service)) as client,
            ThreadPoolExecutor(max_workers=5) as pool,
        ):
            first = pool.submit(client.post, "/compute", json=body)
            second = pool.submit(client.post, "/compute", json=body)
            assert backend.all_entered.wait(timeout=2)
            capabilities = pool.submit(client.get, "/capabilities")
            inspection = pool.submit(
                client.post,
                "/inspect",
                json={"source": body["draft"]["structure"]},
            )
            health = pool.submit(client.get, "/health")
            try:
                assert capabilities.result(timeout=0.5).status_code == 200
                assert inspection.result(timeout=0.5).status_code == 200
                assert health.result(timeout=0.5).json() == {"status": "ok"}
            finally:
                backend.release.set()

            assert first.result(timeout=2).status_code == 200
            assert second.result(timeout=2).status_code == 200
    finally:
        backend.release.set()
        service.close()
        runtime.close()


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
                },
            )
    finally:
        service.close()

    assert response.status_code == 500


def test_http_rejects_paths_and_deployment_configuration(test_service) -> None:
    inline = {"name": "Si.cif", "content": ""}
    with TestClient(create_app(test_service)) as client:
        path_source = client.post(
            "/inspect", json={"source": "/server/inaccessible.cif"}
        )
        path_draft = client.post(
            "/compute",
            json={
                "draft": {
                    "structure": {
                        "kind": "path",
                        "path": "/server/inaccessible.cif",
                    }
                },
                "selection": {"records": ["analysis"]},
            },
        )
        unknown = client.post(
            "/compute",
            json={
                "draft": {"structure": inline},
                "selection": {"records": ["analysis"]},
                "unexpected": True,
            },
        )
        directory = client.post(
            "/compute",
            json={
                "draft": {"structure": inline},
                "selection": {"records": ["analysis"]},
                "output": {"kind": "directory", "path": "/server/output"},
            },
        )
        deployment_fields = {
            field: client.post(
                "/compute",
                json={
                    "draft": {"structure": inline, field: value},
                    "selection": {"records": ["analysis"]},
                },
            )
            for field, value in (
                ("pseudo_root", "/server/pseudos"),
                ("pseudo_metadata", []),
                ("kmesh_model", {"location": "/server/model.pkl"}),
            )
        }

    assert path_source.status_code == 422
    assert path_source.json()["error"]["kind"] == "invalid_request"
    assert (
        path_source.json()["error"]["details"]["validation_errors"][0]["path"]
        == "body.source"
    )
    assert "Transports do not accept file paths" in path_source.text
    assert "/server/inaccessible.cif" not in path_source.text
    assert path_draft.status_code == 422
    assert "Transports do not accept file paths" in path_draft.text
    assert "/server/inaccessible.cif" not in path_draft.text
    assert unknown.status_code == 422
    assert any(
        item["path"] == "body.unexpected"
        for item in unknown.json()["error"]["details"]["validation_errors"]
    )
    assert directory.status_code == 422
    assert directory.json()["error"]["kind"] == "invalid_request"
    assert "/server/output" not in directory.text
    for field, response in deployment_fields.items():
        assert response.status_code == 422
        errors = response.json()["error"]["details"]["validation_errors"]
        assert any(item["path"] == f"body.draft.{field}" for item in errors)


def test_http_asset_not_installed_error_omits_server_paths(
    sample_structure_text: str,
) -> None:
    service = _MissingAssetService()
    try:
        with TestClient(create_app(service)) as client:
            response = client.post(
                "/compute",
                json={
                    "draft": {
                        "structure": {
                            "name": "Si.cif",
                            "content": sample_structure_text,
                        }
                    },
                    "selection": {"records": ["analysis"]},
                },
            )
    finally:
        service.close()

    assert response.status_code == 424
    assert response.json() == {
        "error": {
            "kind": "asset_not_installed",
            "message": "Runtime asset models/model-fixture@7 is not installed.",
            "asset_id": "models/model-fixture",
            "version": "7",
            "reason": "is not installed",
        }
    }
    assert "/srv/goldilocks/secret-assets" not in response.text


def test_http_does_not_expose_internal_filesystem_failures(
    sample_structure_text: str,
) -> None:
    secret = "/srv/goldilocks/private/runtime-secret.bin"
    service = _MissingInternalFileService(secret)
    try:
        with TestClient(create_app(service), raise_server_exceptions=False) as client:
            response = client.post(
                "/compute",
                json={
                    "draft": {
                        "structure": {
                            "name": "Si.cif",
                            "content": sample_structure_text,
                        }
                    },
                    "selection": {"records": ["analysis"]},
                },
            )
    finally:
        service.close()

    assert response.status_code == 500
    assert secret not in response.text


def test_http_sanitizes_corrupt_asset_failures(
    sample_structure_text: str,
) -> None:
    secret = "/opt/goldilocks/assets/private/model.pt"
    service = _CorruptAssetService(secret)
    try:
        with TestClient(create_app(service), raise_server_exceptions=False) as client:
            response = client.post(
                "/compute",
                json={
                    "draft": {
                        "structure": {
                            "name": "Si.cif",
                            "content": sample_structure_text,
                        }
                    },
                    "selection": {"records": ["analysis"]},
                },
            )
    finally:
        service.close()

    assert response.status_code == 424
    assert response.json() == {
        "error": {
            "kind": "asset_corrupt",
            "message": "A required runtime asset failed integrity verification.",
        }
    }
    assert secret not in response.text


def test_openapi_describes_canonical_json_and_archive_contracts(test_service) -> None:
    with TestClient(create_app(test_service)) as client:
        schema = client.get("/openapi.json").json()

    assert set(schema["paths"]) == {
        "/capabilities",
        "/inspect",
        "/compute",
        "/health",
        "/ready",
    }
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
    assert compute["responses"]["200"]["content"]["multipart/form-data"]["schema"][
        "$ref"
    ].endswith("/PreparedComputation")
    assert compute["responses"]["422"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/ErrorResponse")

    schemas = schema["components"]["schemas"]
    prepared = schemas["PreparedComputation"]["properties"]
    assert prepared["result"]["$ref"].endswith("/ComputationResult")
    assert prepared["archive"]["anyOf"][0] == {
        "type": "string",
        "contentMediaType": "application/octet-stream",
    }
    request = schemas["ComputeRequest"]
    assert set(request["properties"]) == {"draft", "selection"}
    draft = schemas["CalculationDraft"]
    assert set(draft["properties"]) == {
        "structure",
        "intent",
        "hints",
        "pseudo_table",
    }
    assert draft["additionalProperties"] is False
    intent = schemas["CalculationIntent-Input"]["properties"]
    assert intent["pseudo_accuracy"]["enum"] == ["efficiency", "precision"]
    hints = schemas["CalculationHints-Input"]["properties"]
    assert hints["smearing_type"]["anyOf"][0]["enum"] == [
        "fixed",
        "gaussian",
        "mp",
        "cold",
    ]
    assert hints["pseudo_type"]["anyOf"][0]["enum"] == ["NC", "USPP", "PAW"]
    assert hints["relativistic_mode"]["anyOf"][0]["enum"] == [
        "scalar",
        "full",
        "non-relativistic",
    ]
    assert hints["vdw_method"]["anyOf"][0]["enum"] == ["d3", "d3bj", "ts", "mbd"]

    result = schemas["ComputationResult"]["properties"]
    assert result["draft"]["$ref"].endswith("/SerializedCalculationDraft")
    selection_document = schemas[result["selection"]["$ref"].rsplit("/", 1)[-1]]
    assert {
        item["$ref"].rsplit("/", 1)[-1] for item in selection_document["anyOf"]
    } == {"PresetSelection", "RecordSelection"}
    assert result["records"]["$ref"].endswith("/Records")
    records = schemas["Records"]
    assert records["additionalProperties"] is False
    assert set(records["properties"]) == {
        "analysis",
        "advice",
        "k_points",
        "selection",
        "generated_files",
        "dft_input_data",
    }
    analysis_ref = records["properties"]["analysis"]["$ref"].rsplit("/", 1)[-1]
    assert "reduced_formula" in schemas[analysis_ref]["properties"]
    selection_ref = records["properties"]["selection"]["$ref"].rsplit("/", 1)[-1]
    assert "pseudopotentials" in schemas[selection_ref]["properties"]
    assert "location" not in schemas["SerializedModel"]["properties"]
    assert "filepath" not in schemas["SerializedPseudoMetadata"]["properties"]
    assert "filepath" not in schemas["SerializedPseudopotentialSelection"]["properties"]


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
    assert "readonly PreparedComputation:" in typescript
    assert "readonly ComputationResult:" in typescript
    assert "readonly StructureInspection:" in typescript
    assert 'readonly records: components["schemas"]["Records"];' in typescript
    assert "readonly Records:" in typescript
    assert "readonly analysis?:" in typescript


def _multipart_parts(response) -> dict[str, tuple[str, str | None, bytes]]:
    message = BytesParser(policy=default).parsebytes(
        (
            f"Content-Type: {response.headers['content-type']}\r\n"
            "MIME-Version: 1.0\r\n\r\n"
        ).encode("ascii")
        + response.content
    )
    return {
        part.get_param("name", header="content-disposition"): (
            part.get_content_type(),
            part.get_filename(),
            part.get_payload(decode=True),
        )
        for part in message.iter_parts()
    }


class _CountingService:
    def __init__(self, service: Service) -> None:
        self._service = service
        self.runtime = service.runtime
        self.compute_calls = 0

    def capabilities(self):
        return self._service.capabilities()

    def inspect_structure(self, source):
        return self._service.inspect_structure(source)

    def compute(self, request, *, output=None):
        self.compute_calls += 1
        return self._service.compute(request, output=output)


class _DefectiveService(Service):
    def compute(self, request, *, output=None):
        del request, output
        raise ValueError("unexpected internal defect")


class _BlockingKmeshBackend:
    def __init__(self, *, expected_calls: int) -> None:
        self._expected_calls = expected_calls
        self._calls = 0
        self._lock = Lock()
        self.all_entered = Event()
        self.release = Event()

    def __call__(self, structure) -> KPointSelection:
        del structure
        with self._lock:
            self._calls += 1
            if self._calls == self._expected_calls:
                self.all_entered.set()
        if not self.release.wait(timeout=2):
            raise RuntimeError("test did not release computation")
        return KPointSelection(
            grid=(3, 3, 3),
            shift=(0, 0, 0),
            mesh_type="monkhorst-pack",
            provenance=Provenance(source="model", reason="test"),
        )

    def close(self) -> None:
        pass


class _MissingAssetService(Service):
    def compute(self, request, *, output=None):
        del request, output
        raise AssetNotInstalled(
            AssetReference("models/model-fixture", "7"),
            Path("/srv/goldilocks/secret-assets"),
        )


class _MissingInternalFileService(Service):
    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = path

    def compute(self, request, *, output=None):
        del request, output
        raise FileNotFoundError(self.path)


class _CorruptAssetService(Service):
    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = path

    def compute(self, request, *, output=None):
        del request, output
        raise AssetCorrupt(f"installed file changed: {self.path}")
