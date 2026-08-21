from __future__ import annotations

import hashlib
import io
import json
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.advice import advise_parameters
from goldilocks_core.assets import AssetCorrupt, AssetNotInstalled
from goldilocks_core.assets.records import AssetReference
from goldilocks_core.contracts import (
    CalculationIntent,
    GeneratedFile,
    KPointSelection,
    PresetRequest,
    Provenance,
    PseudopotentialSelection,
    Result,
    SelectionRecord,
    StructureAnalysisRecord,
)
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
    assert isinstance(service.request, PresetRequest)
    assert isinstance(service.request.structure, Structure)
    assert service.request.hints.k_grid == (3, 3, 3)
    assert service.request.pseudo_table == body["pseudo_table_id"]
    assert service.request.mode == "generate"
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
    assert payload["warnings"] == ["test warning"]


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
            "pseudopotentials/Si.upf",
            "source/Si.cif",
            "structure/canonical.cif",
        }
        assert archive.read("source/Si.cif") == sample_structure_text.encode()
        assert archive.read("pseudopotentials/Si.upf") == pseudo_bytes
        assert (
            archive.read("licences/pseudodojo-pbesol-efficiency-sr.txt").decode()
            == licence_text
        )
        manifest = json.loads(archive.read("goldilocks.json"))
        assert manifest["review_digest"] == review["review_digest"]
        assert manifest["archive_schema_version"] == 1
        assert "goldilocks_core_version" in manifest
        assert "filepath" not in str(manifest)
        assert str(tmp_path) not in str(manifest)
        checksums = archive.read("checksums.sha256").decode().splitlines()
        assert {line.split("  ", 1)[1] for line in checksums} == names - {
            "checksums.sha256"
        }
        for line in checksums:
            digest, name = line.split("  ", 1)
            assert digest == hashlib.sha256(archive.read(name)).hexdigest()


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
        TestClient(create_app(service, compute_wait_seconds=0.05)) as client,
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

        assert first.result(timeout=1).status_code == 422
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
    def __init__(self, result: Result, installed_root: Path | None = None) -> None:
        self.runtime = SimpleNamespace(
            pseudo_registry_path=None,
            asset_store=(
                _AssetStore(installed_root) if installed_root is not None else None
            ),
        )
        self.result = result
        self.request: PresetRequest | None = None
        self.calls = 0

    def generate(self, request: PresetRequest) -> Result:
        self.calls += 1
        self.request = request
        return self.result


class _BlockingService(_RecommendingService):
    def __init__(self, result: Result, *, fail_first: bool) -> None:
        super().__init__(result)
        self.entered = Event()
        self.release = Event()
        self.fail_first = fail_first
        self._calls_lock = Lock()

    def generate(self, request: PresetRequest) -> Result:
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
        return self.result


class _ReadinessStore:
    def __init__(self, *, failure: str | None = None, root: Path | None = None) -> None:
        self.verified: list[tuple[str, str]] = []
        self.failure = failure
        self.root = root or Path("/")

    def verify(self, asset_id: str, version: str) -> SimpleNamespace:
        self.verified.append((asset_id, version))
        if self.failure == "missing":
            raise AssetNotInstalled(AssetReference(asset_id, version), self.root)
        if self.failure == "corrupt":
            raise AssetCorrupt(f"runtime asset {asset_id}@{version} is corrupt")
        return SimpleNamespace(id=asset_id, version=version)


class _AssetStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def resolve(self, asset_id: str, version: str) -> SimpleNamespace:
        assert asset_id
        assert version
        return SimpleNamespace(root=self.root)


def _result_with_pseudo(path: Path) -> Result:
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
    return Result(
        intent=CalculationIntent(),
        analysis=analysis,
        advice=advise_parameters(analysis),
        k_points=KPointSelection(
            grid=(3, 3, 3),
            shift=(0, 0, 0),
            mesh_type="monkhorst-pack",
            provenance=Provenance(source="user_hint", reason="test"),
        ),
        selection=SelectionRecord(
            pseudopotentials=(
                PseudopotentialSelection(
                    element="Si",
                    filename=path.name,
                    filepath=str(path),
                    functional="PBEsol",
                    ecutwfc_ry=30.0,
                    ecutrho_ry=120.0,
                    provenance=Provenance(
                        source="lookup",
                        reason="test",
                        data_source="pseudodojo-pbesol-efficiency-sr",
                    ),
                ),
            )
        ),
        generated_files=(
            GeneratedFile(path="inputs/qe.in", content="&CONTROL\\n/\\n"),
        ),
        warnings=("test warning",),
    )
