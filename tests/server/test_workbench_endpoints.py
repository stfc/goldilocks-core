from __future__ import annotations

import hashlib
import io
import json
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.advice import advise_parameters
from goldilocks_core.assets import AssetCorrupt, AssetNotInstalled
from goldilocks_core.assets.records import AssetReference
from goldilocks_core.contracts import (
    CalculationDraft,
    CalculationHints,
    CalculationIntent,
    ComputationResult,
    ComputeRequest,
    GeneratedFile,
    GeneratedFiles,
    InlineStructureSource,
    KPointSelection,
    ParameterAdvice,
    PresetSelection,
    Provenance,
    PseudopotentialSelection,
    Records,
    SelectionRecord,
    StructureAnalysisRecord,
)
from goldilocks_core.io.structures import normalize_structure
from goldilocks_core.server.http import create_app

TestClient = pytest.importorskip("fastapi.testclient").TestClient


def test_workbench_inspects_disordered_structure_without_losing_occupancies(
    test_service,
) -> None:
    structure = Structure(
        Lattice.cubic(4.0),
        [{"Fe": 0.5, "Mn": 0.5}],
        [[0.0, 0.0, 0.0]],
    )
    content = structure.to(fmt="cif")

    with TestClient(create_app(test_service)) as client:
        response = client.post(
            "/api/workbench/structure",
            json={
                "source": {
                    "name": "alloy.cif",
                    "format": "cif",
                    "content": content,
                }
            },
        )

    assert response.status_code == 200
    payload = response.json()
    document = payload["structure"]
    assert document["schema_version"] == 1
    assert document["source"] == {
        "name": "alloy.cif",
        "format": "cif",
        "sha256": hashlib.sha256(content.encode()).hexdigest(),
        "size_bytes": len(content.encode()),
    }
    assert document["periodicity"] == [True, True, True]
    assert document["site_count"] == 1
    species = document["sites"][0]["species"]
    assert {(item["symbol"], item["occupancy"]) for item in species} == {
        ("Fe", 0.5),
        ("Mn", 0.5),
    }
    assert payload["canonical_cif"].startswith("# generated using pymatgen")
    assert payload["defaults"]["intent"]["functional"] == "PBEsol"
    assert payload["pseudo_tables"]
    assert all("filepath" not in str(table) for table in payload["pseudo_tables"])


def test_workbench_only_exposes_tables_eligible_for_structure(test_service) -> None:
    structure = Structure(Lattice.cubic(5.0), ["Ce"], [[0.0, 0.0, 0.0]])

    with TestClient(create_app(test_service)) as client:
        response = client.post(
            "/api/workbench/structure",
            json={
                "source": {
                    "name": "ce.cif",
                    "format": "cif",
                    "content": structure.to(fmt="cif"),
                }
            },
        )

    assert response.status_code == 200
    tables = response.json()["pseudo_tables"]
    assert tables
    assert {table["provider"] for table in tables} == {"sssp"}
    assert all("Ce" in table["elements"] for table in tables)


def test_workbench_structure_failure_uses_typed_browser_error(test_service) -> None:
    with TestClient(create_app(test_service)) as client:
        response = client.post(
            "/api/workbench/structure",
            json={
                "source": {
                    "name": "broken.cif",
                    "format": "cif",
                    "content": "not a crystal structure",
                }
            },
        )

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "kind": "invalid_request",
            "message": response.json()["error"]["message"],
            "retryable": False,
            "details": {"operation": "structure"},
        }
    }
    assert "Could not parse structure content" in response.json()["error"]["message"]


@pytest.mark.parametrize("operation", ["recommendation", "archive"])
def test_workbench_computation_structure_failure_uses_typed_browser_error(
    test_service, operation: str
) -> None:
    request = {
        "source": {
            "name": "broken.cif",
            "format": "cif",
            "content": "not a crystal structure",
        }
    }
    if operation == "archive":
        request["review_digest"] = "0" * 64

    with TestClient(create_app(test_service)) as client:
        response = client.post(f"/api/workbench/{operation}", json=request)

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "kind": "invalid_request",
            "message": response.json()["error"]["message"],
            "retryable": False,
            "details": {"operation": operation},
        }
    }
    assert "Could not parse structure content" in response.json()["error"]["message"]


def test_workbench_rejects_whitespace_only_source_name_at_transport_seam(
    test_service, sample_structure_text: str
) -> None:
    with TestClient(create_app(test_service), raise_server_exceptions=False) as client:
        response = client.post(
            "/api/workbench/structure",
            json={
                "source": {
                    "name": "   ",
                    "format": "cif",
                    "content": sample_structure_text,
                }
            },
        )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["kind"] == "invalid_request"
    assert error["message"] == "The request does not match the Workbench contract."
    assert error["retryable"] is False
    assert error["details"]["operation"] == "structure"
    assert error["details"]["validation_errors"][0]["path"] == "body.source.name"


def test_workbench_request_validation_uses_the_typed_error_envelope(
    test_service,
) -> None:
    with TestClient(create_app(test_service)) as client:
        response = client.post(
            "/api/workbench/recommendation",
            json={"source": {"name": "Si.cif", "format": "cif"}},
        )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["kind"] == "invalid_request"
    assert error["message"] == "The request does not match the Workbench contract."
    assert error["retryable"] is False
    assert error["details"]["operation"] == "recommendation"
    assert error["details"]["validation_errors"] == [
        {
            "path": "body.source.content",
            "type": "missing",
            "message": "Field required",
        }
    ]


def test_workbench_openapi_declares_typed_error_responses(test_service) -> None:
    with TestClient(create_app(test_service)) as client:
        schema = client.get("/openapi.json").json()

    expected = {
        "/api/workbench/structure": {"422"},
        "/api/workbench/recommendation": {"422", "503"},
        "/api/workbench/archive": {"409", "422", "503"},
    }
    for path, statuses in expected.items():
        responses = schema["paths"][path]["post"]["responses"]
        for status in statuses:
            assert (
                responses[status]["content"]["application/json"]["schema"]["$ref"]
                == "#/components/schemas/WorkbenchErrorResponse"
            )


def test_workbench_recommendation_is_typed_stable_and_browser_safe(
    sample_structure_text: str, tmp_path: Path
) -> None:
    pseudo_path = tmp_path / "Si.upf"
    pseudo_bytes = b"<UPF>trusted fixture</UPF>\\n"
    pseudo_path.write_bytes(pseudo_bytes)
    result = _result_with_pseudo(pseudo_path)
    service = _RecommendingService(result)
    body = {
        "source": {
            "name": "Si.cif",
            "format": "cif",
            "content": sample_structure_text,
        },
        "intent": {
            "code": "quantum_espresso",
            "task": "scf_single_point",
            "functional": "PBEsol",
            "pseudo_accuracy": "efficiency",
        },
        "hints": {"k_grid": [3, 3, 3]},
        "pseudo_table_id": "pseudodojo-pbesol-efficiency-sr",
    }

    with TestClient(create_app(service)) as client:
        first = client.post("/api/workbench/recommendation", json=body)
        second = client.post("/api/workbench/recommendation", json=body)

    assert first.status_code == 200
    assert second.status_code == 200
    assert isinstance(service.request, ComputeRequest)
    assert isinstance(service.request.draft.structure, InlineStructureSource)
    assert service.request.draft.hints.k_grid == (3, 3, 3)
    assert service.request.draft.pseudo_table == body["pseudo_table_id"]
    assert service.request.selection == PresetSelection("generate")
    payload = first.json()
    assert payload["review_digest"] == second.json()["review_digest"]
    assert len(payload["review_digest"]) == 64
    assert payload["generated_files"] == [
        {
            "path": "inputs/qe.in",
            "role": "input",
            "content": "&CONTROL\\n/\\n",
            "sha256": hashlib.sha256(b"&CONTROL\\n/\\n").hexdigest(),
        }
    ]
    assert payload["selection"]["table"]["id"] == body["pseudo_table_id"]
    assert (
        payload["selection"]["files"][0]["sha256"]
        == hashlib.sha256(pseudo_bytes).hexdigest()
    )
    serialized = str(payload)
    assert "filepath" not in serialized
    assert str(tmp_path) not in serialized
    assert payload["records"]["analysis"]["formula"] == "Si1"
    assert payload["decisions"] == {
        "k_grid": [3, 3, 3],
        "k_shift": [0, 0, 0],
        "k_mesh_type": "monkhorst-pack",
        "spin_polarized": False,
        "spin_orbit_coupling": False,
        "smearing_type": "fixed",
        "smearing_width_ry": None,
        "use_vdw": False,
        "pseudo_table_id": "pseudodojo-pbesol-efficiency-sr",
        "pseudo_functional": "PBEsol",
        "pseudo_accuracy": "efficiency",
        "pseudo_relativistic": "scalar",
    }
    assert payload["runtime"]["models"] == [
        {
            "name": "fixture-model",
            "version": "1",
            "model_type": "fixture",
            "target": "fixture-target",
            "feature_set": "fixture-features",
            "source": "local",
            "revision": "fixture-revision",
        }
    ]
    assert {asset["id"] for asset in payload["runtime"]["model_assets"]} == {
        "qrf-kpoints",
        "metallicity-cgcnn",
    }
    assert all(
        file["sha256"] and file["size_bytes"]
        for asset in payload["runtime"]["model_assets"]
        for file in asset["files"]
    )
    assert payload["warnings"] == ["test warning"]


def test_workbench_recommendation_reports_missing_assets(
    sample_structure_text: str, tmp_path: Path
) -> None:
    missing = AssetNotInstalled(AssetReference("metallicity-cgcnn", "1"), tmp_path)
    service = _FailingService(missing)

    with TestClient(create_app(service)) as client:
        response = client.post(
            "/api/workbench/recommendation",
            json={
                "source": {
                    "name": "Si.cif",
                    "format": "cif",
                    "content": sample_structure_text,
                }
            },
        )

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "kind": "assets_unavailable",
            "message": "Required runtime asset metallicity-cgcnn@1 is unavailable.",
            "retryable": False,
            "details": {
                "operation": "recommendation",
                "asset_id": "metallicity-cgcnn",
                "version": "1",
            },
        }
    }


def test_workbench_archive_reruns_core_and_contains_every_trusted_input(
    sample_structure_text: str, tmp_path: Path
) -> None:
    pseudo_path = tmp_path / "Si.upf"
    pseudo_bytes = b"<UPF>trusted fixture</UPF>\\n"
    pseudo_path.write_bytes(pseudo_bytes)
    installed_root = tmp_path / "installed"
    installed_root.mkdir()
    licence_text = "Creative Commons Attribution 4.0 International\\n"
    (installed_root / "LICENSE.txt").write_text(licence_text)
    model_cards = {
        "qrf-kpoints": b"---\nlicense: cc-by-4.0\n---\nQRF attribution\n",
        "metallicity-cgcnn": b"---\nlicense: cc-by-4.0\n---\n",
    }
    for asset_id, content in model_cards.items():
        model_root = installed_root / asset_id
        model_root.mkdir()
        (model_root / "MODEL_CARD.md").write_bytes(content)
    service = _RecommendingService(
        _result_with_pseudo(pseudo_path), installed_root=installed_root
    )
    request = {
        "source": {
            "name": "Si.cif",
            "format": "cif",
            "content": sample_structure_text,
        },
        "intent": {
            "code": "quantum_espresso",
            "task": "scf_single_point",
            "functional": "PBEsol",
            "pseudo_accuracy": "efficiency",
        },
        "hints": {"k_grid": [3, 3, 3]},
        "pseudo_table_id": "pseudodojo-pbesol-efficiency-sr",
    }

    with TestClient(create_app(service)) as client:
        review = client.post("/api/workbench/recommendation", json=request).json()
        response = client.post(
            "/api/workbench/archive",
            json={**request, "review_digest": review["review_digest"]},
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "attachment" in response.headers["content-disposition"]
    assert service.calls == 2

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        assert names == {
            "README.md",
            "CITATIONS.md",
            "checksums.sha256",
            "goldilocks.json",
            "inputs/qe.in",
            "licences/pseudodojo-pbesol-efficiency-sr.txt",
            "licences/qrf-kpoints-QRF95.md",
            "licences/metallicity-cgcnn-1.md",
            "pseudo/Si.upf",
            "source/Si.cif",
            "structure/canonical.cif",
        }
        assert archive.read("source/Si.cif") == sample_structure_text.encode()
        assert archive.read("pseudo/Si.upf") == pseudo_bytes
        assert (
            archive.read("licences/pseudodojo-pbesol-efficiency-sr.txt").decode()
            == licence_text
        )
        assert (
            archive.read("licences/qrf-kpoints-QRF95.md") == model_cards["qrf-kpoints"]
        )
        assert (
            archive.read("licences/metallicity-cgcnn-1.md")
            == model_cards["metallicity-cgcnn"]
        )
        manifest = json.loads(archive.read("goldilocks.json"))
        assert manifest["review_digest"] == review["review_digest"]
        assert manifest["archive_schema_version"] == 1
        assert "goldilocks_core_version" in manifest
        assert manifest["structure"] == review["structure"]
        assert manifest["runtime"] == review["runtime"]
        assert manifest["archive_files"]["pseudo/Si.upf"] == {
            "sha256": hashlib.sha256(pseudo_bytes).hexdigest(),
            "size_bytes": len(pseudo_bytes),
        }
        assert b"Selected pseudopotentials: `pseudo/`" in archive.read("README.md")
        assert b"`pw.x -in inputs/qe.in`" in archive.read("README.md")
        assert b"Runtime models" in archive.read("CITATIONS.md")
        assert "filepath" not in str(manifest)
        assert str(tmp_path) not in str(manifest)
        checksums = archive.read("checksums.sha256").decode().splitlines()
        assert {line.split("  ", 1)[1] for line in checksums} == names - {
            "checksums.sha256"
        }
        for line in checksums:
            digest, name = line.split("  ", 1)
            assert digest == hashlib.sha256(archive.read(name)).hexdigest()


def test_workbench_archive_reports_missing_licence_without_a_server_path(
    sample_structure_text: str, tmp_path: Path
) -> None:
    pseudo_path = tmp_path / "Si.upf"
    pseudo_path.write_text("<UPF/>")
    installed_root = tmp_path / "installed"
    installed_root.mkdir()
    service = _RecommendingService(
        _result_with_pseudo(pseudo_path), installed_root=installed_root
    )
    request = {
        "source": {
            "name": "Si.cif",
            "format": "cif",
            "content": sample_structure_text,
        },
        "pseudo_table_id": "pseudodojo-pbesol-efficiency-sr",
    }

    with TestClient(create_app(service)) as client:
        review = client.post("/api/workbench/recommendation", json=request).json()
        response = client.post(
            "/api/workbench/archive",
            json={**request, "review_digest": review["review_digest"]},
        )

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "kind": "assets_unavailable",
            "message": (
                "Required licence material for runtime asset "
                "'pseudodojo-pbesol-efficiency-sr' is unavailable."
            ),
            "retryable": True,
            "details": {
                "operation": "archive",
                "asset_id": "pseudodojo-pbesol-efficiency-sr",
                "version": "0.4",
            },
        }
    }
    assert str(tmp_path) not in response.text


def test_workbench_archive_rejects_a_stale_review(
    sample_structure_text: str, tmp_path: Path
) -> None:
    pseudo_path = tmp_path / "Si.upf"
    pseudo_path.write_text("<UPF/>")
    service = _RecommendingService(_result_with_pseudo(pseudo_path))

    with TestClient(create_app(service)) as client:
        response = client.post(
            "/api/workbench/archive",
            json={
                "source": {
                    "name": "Si.cif",
                    "format": "cif",
                    "content": sample_structure_text,
                },
                "pseudo_table_id": "pseudodojo-pbesol-efficiency-sr",
                "review_digest": "0" * 64,
            },
        )

    assert response.status_code == 409
    assert response.json()["error"]["kind"] == "stale_review"
    assert response.json()["error"]["retryable"] is False
    assert len(response.json()["error"]["details"]["current_review_digest"]) == 64
    assert service.calls == 1


def test_workbench_capacity_times_out_without_blocking_health_and_releases(
    sample_structure_text: str, tmp_path: Path
) -> None:
    pseudo_path = tmp_path / "Si.upf"
    pseudo_path.write_text("<UPF/>")
    service = _BlockingService(_result_with_pseudo(pseudo_path), fail_first=True)
    body = {
        "source": {
            "name": "Si.cif",
            "format": "cif",
            "content": sample_structure_text,
        },
        "pseudo_table_id": "pseudodojo-pbesol-efficiency-sr",
    }

    with (
        TestClient(
            create_app(service, compute_wait_seconds=0.05),
            raise_server_exceptions=False,
        ) as client,
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        first = executor.submit(client.post, "/api/workbench/recommendation", json=body)
        assert service.entered.wait(timeout=1)
        try:
            assert client.get("/health").json() == {"status": "ok"}
            busy = client.post("/api/workbench/recommendation", json=body)
            assert busy.status_code == 503
            assert busy.json()["error"] == {
                "kind": "server_busy",
                "message": "The computation slot is busy; retry this request.",
                "retryable": True,
                "details": {"retry_after_seconds": 0.05},
            }
        finally:
            service.release.set()

        assert first.result(timeout=1).status_code == 500
        assert (
            client.post("/api/workbench/recommendation", json=body).status_code == 200
        )
        assert service.calls == 2


def test_workbench_capacity_allows_a_waiting_request_within_the_bound(
    sample_structure_text: str, tmp_path: Path
) -> None:
    pseudo_path = tmp_path / "Si.upf"
    pseudo_path.write_text("<UPF/>")
    service = _BlockingService(_result_with_pseudo(pseudo_path), fail_first=False)
    body = {
        "source": {
            "name": "Si.cif",
            "format": "cif",
            "content": sample_structure_text,
        },
        "pseudo_table_id": "pseudodojo-pbesol-efficiency-sr",
    }

    with (
        TestClient(create_app(service, compute_wait_seconds=0.5)) as client,
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        first = executor.submit(client.post, "/api/workbench/recommendation", json=body)
        assert service.entered.wait(timeout=1)
        second = executor.submit(
            client.post, "/api/workbench/recommendation", json=body
        )
        time.sleep(0.05)
        assert not second.done()
        service.release.set()

        assert first.result(timeout=1).status_code == 200
        assert second.result(timeout=1).status_code == 200
        assert service.calls == 2


def test_ready_verifies_and_caches_the_complete_workbench_asset_profile() -> None:
    store = _ReadinessStore()
    service = SimpleNamespace(
        runtime=SimpleNamespace(asset_store=store, pseudo_registry_path=None)
    )

    with TestClient(create_app(service)) as client:
        first = client.get("/ready")
        second = client.get("/ready")

    assert first.status_code == 200
    assert first.json() == {"status": "ready", "asset_count": 17}
    assert second.json() == first.json()
    assert len(store.verified) == 17
    assert len({asset_id for asset_id, _ in store.verified}) == 17


def test_ready_uses_the_runtime_pseudopotential_registry(tmp_path: Path) -> None:
    registry = tmp_path / "pseudos.toml"
    registry.write_text(
        """
[tables.fixture]
provider = "sssp"
upstream_table = "fixture"
version = "1"
functional = "PBEsol"
relativistic = "scalar"
accuracy = "efficiency"
licence = "CC BY 4.0"
citation = "fixture"
elements = ["Si"]
default = true

[[tables.fixture.files]]
role = "pseudopotentials"
path = "source/pseudos.tgz"
url = "file:///tmp/pseudos.tgz"

[[tables.fixture.files]]
role = "metadata"
path = "source/metadata.json"
url = "file:///tmp/metadata.json"

[[tables.fixture.files]]
role = "licence"
path = "source/LICENSE.txt"
url = "file:///tmp/LICENSE.txt"
""".strip(),
        encoding="utf-8",
    )
    store = _ReadinessStore()
    service = SimpleNamespace(
        runtime=SimpleNamespace(
            asset_store=store,
            model_registry_path=None,
            pseudo_registry_path=registry,
        )
    )

    with TestClient(create_app(service)) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "asset_count": 3}
    assert {asset_id for asset_id, _ in store.verified} == {
        "fixture",
        "metallicity-cgcnn",
        "qrf-kpoints",
    }


@pytest.mark.parametrize("failure", ["missing", "corrupt"])
def test_ready_reports_missing_and_corrupt_assets(failure: str, tmp_path: Path) -> None:
    store = _ReadinessStore(failure=failure, root=tmp_path)
    service = SimpleNamespace(
        runtime=SimpleNamespace(asset_store=store, pseudo_registry_path=None)
    )

    with TestClient(create_app(service)) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["kind"] == "assets_unavailable"
    assert error["retryable"] is False
    assert error["details"] == {
        "asset_id": store.verified[0][0],
        "version": store.verified[0][1],
        "state": failure,
        "required_asset_count": 17,
    }


def test_workbench_static_root_is_served_after_api_routes(
    test_service, tmp_path: Path
) -> None:
    static_root = tmp_path / "dist"
    assets = static_root / "assets"
    assets.mkdir(parents=True)
    (static_root / "index.html").write_text("<main>Goldilocks Workbench</main>")
    (assets / "app.js").write_text("window.workbench = true;")

    with TestClient(create_app(test_service, static_root=static_root)) as client:
        index = client.get("/")
        script = client.get("/assets/app.js")
        health = client.get("/health")
        api_missing = client.get("/api/workbench/missing")

    assert index.status_code == 200
    assert index.text == "<main>Goldilocks Workbench</main>"
    assert script.text == "window.workbench = true;"
    assert health.json() == {"status": "ok"}
    assert api_missing.status_code == 404
    assert "Goldilocks Workbench" not in api_missing.text


class _RecommendingService:
    def __init__(
        self,
        result: ComputationResult,
        installed_root: Path | None = None,
    ) -> None:
        self.runtime = SimpleNamespace(
            pseudo_registry_path=None,
            model_registry_path=None,
            describe_models=lambda: [
                {
                    "name": "fixture-model",
                    "version": "1",
                    "target": "fixture-target",
                    "feature_set": "fixture-features",
                    "model_type": "fixture",
                    "revision": "fixture-revision",
                    "source": "local",
                }
            ],
            asset_store=(
                _AssetStore(installed_root) if installed_root is not None else None
            ),
        )
        self.result = result
        self.request: ComputeRequest | None = None
        self.calls = 0

    def compute(self, request: ComputeRequest) -> ComputationResult:
        self.calls += 1
        self.request = request
        return _normalized_result(self.result, request)


class _FailingService:
    def __init__(self, error: Exception) -> None:
        self.runtime = SimpleNamespace(
            pseudo_registry_path=None,
            model_registry_path=None,
            asset_store=None,
            describe_models=lambda: [],
        )
        self.error = error

    def compute(self, request: ComputeRequest) -> ComputationResult:
        del request
        raise self.error


class _BlockingService(_RecommendingService):
    def __init__(self, result: ComputationResult, *, fail_first: bool) -> None:
        super().__init__(result)
        self.entered = Event()
        self.release = Event()
        self.fail_first = fail_first
        self._calls_lock = Lock()

    def compute(self, request: ComputeRequest) -> ComputationResult:
        with self._calls_lock:
            self.calls += 1
            call_number = self.calls
        self.request = request
        if call_number == 1:
            self.entered.set()
            if not self.release.wait(timeout=2):
                raise RuntimeError("test did not release computation")
            if self.fail_first:
                raise ValueError("synthetic calculation failure")
        return _normalized_result(self.result, request)


class _ReadinessStore:
    def __init__(self, *, failure: str | None = None, root: Path | None = None) -> None:
        self.verified: list[tuple[str, str]] = []
        self.failure = failure
        self.root = root or Path("/")

    def verify_spec(self, spec) -> SimpleNamespace:
        self.verified.append((spec.id, spec.version))
        if self.failure == "missing":
            raise AssetNotInstalled(AssetReference(spec.id, spec.version), self.root)
        if self.failure == "corrupt":
            raise AssetCorrupt(f"runtime asset {spec.id}@{spec.version} is corrupt")
        return SimpleNamespace(id=spec.id, version=spec.version)


class _AssetStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def resolve_spec(self, spec) -> SimpleNamespace:
        assert spec.id
        assert spec.version
        asset_root = self.root / spec.id
        root = asset_root if asset_root.is_dir() else self.root

        def path(relative: str) -> Path:
            resolved = root / relative
            if not resolved.is_file():
                raise FileNotFoundError(relative)
            return resolved

        return SimpleNamespace(root=root, path=path)


def _normalized_result(
    result: ComputationResult, request: ComputeRequest
) -> ComputationResult:
    inspection = normalize_structure(request.draft.structure).inspection
    return replace(
        result,
        draft=replace(request.draft, structure=inspection),
    )


def _result_with_pseudo(path: Path) -> ComputationResult:
    analysis = StructureAnalysisRecord(
        formula="Si1",
        reduced_formula="Si",
        site_count=1,
        elements=("Si",),
        contains_transition_metals=False,
        contains_lanthanides=False,
        contains_actinides=False,
        contains_heavy_elements=False,
        magnetic_elements=(),
        heavy_elements=(),
    )
    advice = advise_parameters(analysis)
    k_points = KPointSelection(
        grid=(3, 3, 3),
        shift=(0, 0, 0),
        mesh_type="monkhorst-pack",
        provenance=Provenance(source="user_hint", reason="test"),
    )
    selection = SelectionRecord(
        pseudopotentials=(
            PseudopotentialSelection(
                element="Si",
                filename=path.name,
                filepath=str(path),
                functional="PBEsol",
                relativistic="scalar",
                ecutwfc_ry=30.0,
                ecutrho_ry=120.0,
                provenance=Provenance(
                    source="lookup",
                    reason="test",
                    data_source="pseudodojo-pbesol-efficiency-sr",
                ),
            ),
        )
    )
    return ComputationResult(
        draft=CalculationDraft(
            structure=Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]]),
            intent=CalculationIntent(),
            hints=CalculationHints(),
        ),
        task="scf_single_point",
        task_revision="1",
        selection=PresetSelection("generate"),
        records=Records(
            {
                StructureAnalysisRecord: analysis,
                ParameterAdvice: advice,
                KPointSelection: k_points,
                SelectionRecord: selection,
                GeneratedFiles: (
                    GeneratedFile(path="inputs/qe.in", content="&CONTROL\\n/\\n"),
                ),
            }
        ),
        warnings=("test warning",),
    )
