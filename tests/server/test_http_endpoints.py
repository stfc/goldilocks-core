from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    pass

# These tests hit the HTTP endpoints over FastAPI's in-process TestClient. No
# real model is loaded (every request uses an explicit k-grid hint and a
# heuristic-kpoints runtime), and no network is involved.


def _recommend_body(
    si_cif: str, *, with_pseudo: bool = False, si_pseudo_metadata: dict | None = None
) -> dict:
    """Return a /recommend-shaped body with an explicit k-grid hint."""
    body: dict = {
        "structure": {"content": si_cif, "format": "cif"},
        "hints": {"k_grid": [3, 3, 3]},
    }
    if with_pseudo and si_pseudo_metadata is not None:
        body["pseudo_metadata"] = [si_pseudo_metadata]
    return body


def test_health_returns_ok_without_running_a_job(client) -> None:
    """GET /health reports liveness and does not return a CoreResult."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_recommend_returns_strict_core_result_json(client, si_cif: str) -> None:
    """POST /recommend returns a CoreResult JSON with provenance and warnings."""
    response = client.post("/recommend", json=_recommend_body(si_cif))

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {
        "intent",
        "analysis",
        "advice",
        "selection",
        "generated_files",
        "warnings",
        "bundle",
        "stages",
    }
    assert [stage["name"] for stage in data["stages"]] == [
        "load",
        "analyze",
        "advise",
        "kmesh",
        "select",
    ]
    assert data["selection"]["k_points"]["grid"] == [3, 3, 3]
    assert data["selection"]["k_points"]["provenance"]["source"] == "user_hint"
    assert isinstance(data["warnings"], list)
    assert data["generated_files"] == []
    assert data["bundle"] is None


def test_recommend_with_missing_pseudo_returns_fallback_provenance(
    client, si_cif: str
) -> None:
    """Missing pseudo metadata is not an error; selection records fallback."""
    response = client.post("/recommend", json=_recommend_body(si_cif))

    assert response.status_code == 200
    pseudo = response.json()["selection"]["pseudopotentials"][0]
    assert pseudo["provenance"]["source"] == "fallback"
    assert pseudo["filename"] is None


def test_generate_returns_generated_files(
    client, si_cif: str, si_pseudo_metadata: dict
) -> None:
    """POST /generate runs through Generate and returns generated input files."""
    response = client.post(
        "/generate",
        json=_recommend_body(
            si_cif, with_pseudo=True, si_pseudo_metadata=si_pseudo_metadata
        ),
    )

    assert response.status_code == 200
    data = response.json()
    assert [stage["name"] for stage in data["stages"]] == [
        "load",
        "analyze",
        "advise",
        "kmesh",
        "select",
        "generate",
    ]
    assert [file["path"] for file in data["generated_files"]] == ["inputs/qe.in"]
    assert "CONTROL" in data["generated_files"][0]["content"]


def test_bundle_writes_under_bundle_root(
    client, si_cif: str, si_pseudo_metadata: dict, bundle_root: Path
) -> None:
    """POST /bundle publishes a bundle directory under the configured bundle root."""
    body = _recommend_body(
        si_cif, with_pseudo=True, si_pseudo_metadata=si_pseudo_metadata
    )
    body["output_dir"] = "run-001"

    response = client.post("/bundle", json=body)

    assert response.status_code == 200
    data = response.json()
    assert [stage["name"] for stage in data["stages"]] == [
        "load",
        "analyze",
        "advise",
        "kmesh",
        "select",
        "generate",
        "bundle",
    ]
    assert data["bundle"]["path"].endswith("run-001")
    assert (bundle_root / "run-001" / "manifest.json").exists()


def test_bundle_rejects_existing_output_dir(
    client, si_cif: str, si_pseudo_metadata: dict, bundle_root: Path
) -> None:
    """An existing bundle destination is refused with a stage_error (400)."""
    (bundle_root / "run-002").mkdir()
    body = _recommend_body(
        si_cif, with_pseudo=True, si_pseudo_metadata=si_pseudo_metadata
    )
    body["output_dir"] = "run-002"

    response = client.post("/bundle", json=body)

    assert response.status_code == 400
    assert response.json()["error"]["kind"] == "stage_error"


def test_bad_structure_content_returns_422(client) -> None:
    """Unparseable inline structure content maps to 422 invalid_request."""
    response = client.post(
        "/recommend",
        json={"structure": {"content": "not a structure", "format": "cif"}},
    )

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


def test_missing_structure_returns_422(client) -> None:
    """A body without a structure field maps to 422."""
    response = client.post("/recommend", json={"hints": {"k_grid": [3, 3, 3]}})

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


def test_empty_body_returns_422(client) -> None:
    """An empty request body maps to 422."""
    response = client.post("/recommend", data=b"")

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


def test_invalid_json_returns_422(client) -> None:
    """Malformed JSON maps to 422 invalid_request."""
    response = client.post(
        "/recommend",
        data=b"{not valid json",
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


def test_non_object_json_body_returns_422(client) -> None:
    """A JSON array body maps to 422."""
    response = client.post("/recommend", json=[1, 2, 3])

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


def test_unsupported_code_returns_422(client, si_cif: str) -> None:
    """An unsupported DFT code maps to 422."""
    response = client.post(
        "/recommend",
        json={
            "structure": {"content": si_cif, "format": "cif"},
            "intent": {"code": "vasp"},
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


def test_unsupported_task_returns_422(client, si_cif: str) -> None:
    """An unsupported calculation task maps to 422."""
    response = client.post(
        "/recommend",
        json={
            "structure": {"content": si_cif, "format": "cif"},
            "intent": {"task": "relax"},
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


def test_unknown_hint_key_returns_422(client, si_cif: str) -> None:
    """Unknown hint keys map to 422."""
    response = client.post(
        "/recommend",
        json={
            "structure": {"content": si_cif, "format": "cif"},
            "hints": {"bogus": 1},
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


def test_bad_hint_value_returns_422(client, si_cif: str) -> None:
    """A hint value that fails contract validation maps to 422."""
    response = client.post(
        "/recommend",
        json={
            "structure": {"content": si_cif, "format": "cif"},
            "hints": {"k_grid": [0, 0, 0]},
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


def test_bundle_without_output_dir_returns_422(client, si_cif: str) -> None:
    """Bundle mode without output_dir maps to 422."""
    response = client.post(
        "/bundle",
        json={
            "structure": {"content": si_cif, "format": "cif"},
            "hints": {"k_grid": [3, 3, 3]},
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


@pytest.mark.parametrize("output_dir", ["../../etc", "/etc", "a/../../b"])
def test_bundle_traversal_or_absolute_output_dir_returns_422(
    client, si_cif: str, output_dir: str
) -> None:
    """Traversal or absolute output_dir maps to 422."""
    response = client.post(
        "/bundle",
        json={
            "structure": {"content": si_cif, "format": "cif"},
            "output_dir": output_dir,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


@pytest.mark.parametrize("path", ["../escape", "/etc/passwd", "sub/../.."])
def test_structure_path_traversal_or_absolute_returns_422(
    client, si_cif: str, path: str
) -> None:
    """Traversal or absolute structure paths map to 422."""
    response = client.post(
        "/recommend",
        json={"structure": {"path": path}, "hints": {"k_grid": [3, 3, 3]}},
    )

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


def test_structure_path_missing_file_returns_404(client) -> None:
    """A server-side structure path that does not exist maps to 404."""
    response = client.post(
        "/recommend",
        json={"structure": {"path": "missing.cif"}, "hints": {"k_grid": [3, 3, 3]}},
    )

    assert response.status_code == 404
    assert response.json()["error"]["kind"] == "not_found"


def test_structure_path_without_configured_root_returns_422(si_cif: str) -> None:
    """A server-side path with no configured structure root maps to 422."""
    from fastapi.testclient import TestClient

    from goldilocks_core.jobs import CoreRuntime, Pipeline
    from goldilocks_core.kmesh import resolve_kpoints_from_advice
    from goldilocks_core.server.http import create_app

    app = create_app(
        runtime=CoreRuntime(pipeline=Pipeline(kmesh=resolve_kpoints_from_advice)),
        structure_root=None,
        bundle_root=Path("/tmp/bundles"),
    )
    with TestClient(app) as standalone:
        response = standalone.post(
            "/recommend",
            json={"structure": {"path": "Si.cif"}, "hints": {"k_grid": [3, 3, 3]}},
        )

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


def test_unknown_route_returns_404_error_schema(client) -> None:
    """An unknown route returns the deterministic 404 error schema."""
    response = client.get("/nope")

    assert response.status_code == 404
    assert response.json()["error"]["kind"] == "not_found"


def test_wrong_method_returns_405_error_schema(client) -> None:
    """A disallowed method returns the deterministic 405 error schema."""
    response = client.put("/health")

    assert response.status_code == 405
    assert response.json()["error"]["kind"] == "method_not_allowed"


def test_internal_error_is_redacted(si_cif: str) -> None:
    """Unexpected non-validation errors return 500 without leaking internals."""
    from fastapi.testclient import TestClient

    from goldilocks_core.jobs import CoreRuntime, Pipeline
    from goldilocks_core.kmesh import resolve_kpoints_from_advice
    from goldilocks_core.server.http import create_app

    runtime = CoreRuntime(pipeline=Pipeline(kmesh=resolve_kpoints_from_advice))

    def explode(_request: object) -> object:
        raise KeyError("secret-internal-token")

    runtime.run = explode  # type: ignore[method-assign]
    app = create_app(runtime=runtime, bundle_root=Path("/tmp/bundles"))
    with TestClient(app, raise_server_exceptions=False) as standalone:
        response = standalone.post(
            "/recommend",
            json={
                "structure": {"content": si_cif, "format": "cif"},
                "hints": {"k_grid": [3, 3, 3]},
            },
        )

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["kind"] == "internal_error"
    assert "secret-internal-token" not in response.text


def test_health_does_not_invoke_kmesh(si_cif: str) -> None:
    """GET /health does not run the pipeline or load the Kmesh backend."""
    from fastapi.testclient import TestClient

    from goldilocks_core.contracts import KPointAdvice, KPointSelection, Provenance
    from goldilocks_core.jobs import CoreRuntime, Pipeline
    from goldilocks_core.server.http import create_app

    calls = {"count": 0}

    def tracking_kmesh(structure, hints, advice: KPointAdvice) -> KPointSelection:  # noqa: ANN001
        calls["count"] += 1
        return KPointSelection(
            grid=hints.k_grid or (1, 1, 1),
            shift=(0, 0, 0),
            mesh_type=advice.mesh_type,
            provenance=Provenance(source="user_hint", reason="test"),
        )

    runtime = CoreRuntime(pipeline=Pipeline(kmesh=tracking_kmesh))
    app = create_app(runtime=runtime, bundle_root=Path("/tmp/bundles"))
    with TestClient(app) as standalone:
        assert standalone.get("/health").status_code == 200
        assert calls["count"] == 0
        standalone.post(
            "/recommend",
            json={
                "structure": {"content": si_cif, "format": "cif"},
                "hints": {"k_grid": [3, 3, 3]},
            },
        )
        assert calls["count"] == 1


def test_create_app_raises_clear_error_when_http_extra_missing() -> None:
    """create_app raises a clear install hint when the [http] extra is absent."""
    from goldilocks_core.server import http as server_http

    original = (server_http.FastAPI, server_http.Request, server_http.JSONResponse)
    try:
        server_http.FastAPI = None  # type: ignore[assignment]
        server_http.Request = None  # type: ignore[assignment]
        server_http.JSONResponse = None  # type: ignore[assignment]
        with pytest.raises(ImportError, match=r"\[http\]"):
            server_http.create_app()
    finally:
        server_http.FastAPI, server_http.Request, server_http.JSONResponse = original


# --- Reviewer probe regressions (issue #44) ------------------------------------


def test_structure_path_symlink_component_is_rejected(
    structure_root: Path, si_cif: str, tmp_path: Path
) -> None:
    """A symlink component inside the structure root is rejected with 422."""
    from fastapi.testclient import TestClient

    from goldilocks_core.jobs import CoreRuntime, Pipeline
    from goldilocks_core.kmesh import resolve_kpoints_from_advice
    from goldilocks_core.server.http import create_app

    outside = tmp_path / "outside.cif"
    outside.write_text(si_cif)
    (structure_root / "link.cif").symlink_to(outside)

    app = create_app(
        runtime=CoreRuntime(pipeline=Pipeline(kmesh=resolve_kpoints_from_advice)),
        structure_root=structure_root,
        bundle_root=tmp_path / "bundles",
    )
    with TestClient(app) as standalone:
        response = standalone.post(
            "/recommend",
            json={"structure": {"path": "link.cif"}, "hints": {"k_grid": [3, 3, 3]}},
        )

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"
    assert str(outside) not in response.text


def test_bundle_output_dir_symlink_component_is_rejected(
    bundle_root: Path, si_cif: str, si_pseudo_metadata: dict, tmp_path: Path
) -> None:
    """A symlink component in output_dir cannot publish outside the bundle root."""
    from fastapi.testclient import TestClient

    from goldilocks_core.jobs import CoreRuntime, Pipeline
    from goldilocks_core.kmesh import resolve_kpoints_from_advice
    from goldilocks_core.server.http import create_app

    outside_root = tmp_path / "outside-bundles"
    outside_root.mkdir()
    (bundle_root / "link").symlink_to(outside_root)

    app = create_app(
        runtime=CoreRuntime(pipeline=Pipeline(kmesh=resolve_kpoints_from_advice)),
        structure_root=tmp_path / "structures",
        bundle_root=bundle_root,
    )
    body = {
        "structure": {"content": si_cif, "format": "cif"},
        "hints": {"k_grid": [3, 3, 3]},
        "pseudo_metadata": [si_pseudo_metadata],
        "output_dir": "link/run-001",
    }
    with TestClient(app) as standalone:
        response = standalone.post("/bundle", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"
    # Nothing was published outside the configured bundle root.
    assert not any(outside_root.iterdir())


def test_bundle_existing_destination_redacts_absolute_path(
    client, si_cif: str, si_pseudo_metadata: dict, bundle_root: Path
) -> None:
    """An existing bundle destination is a stage_error without the absolute path."""
    (bundle_root / "run-002").mkdir()
    body = _recommend_body(
        si_cif, with_pseudo=True, si_pseudo_metadata=si_pseudo_metadata
    )
    body["output_dir"] = "run-002"

    response = client.post("/bundle", json=body)

    assert response.status_code == 400
    assert response.json()["error"]["kind"] == "stage_error"
    # The absolute host path must not leak into the response.
    assert str(bundle_root) not in response.text
    assert str(bundle_root / "run-002") not in response.text
    assert "run-002" in response.text


def test_internal_model_not_found_is_redacted_500(si_cif: str, tmp_path: Path) -> None:
    """A missing local model is an internal 500, never a 404 leaking the model path."""
    from fastapi.testclient import TestClient

    from goldilocks_core.server.http import create_app

    private_model = tmp_path / "private-model.joblib"
    app = create_app(
        model=str(private_model),
        bundle_root=tmp_path / "bundles",
    )
    with TestClient(app, raise_server_exceptions=False) as standalone:
        response = standalone.post(
            "/recommend",
            json={
                "structure": {"content": si_cif, "format": "cif"},
                # No k-grid hint forces the kmesh backend, which loads the model.
            },
        )

    assert response.status_code == 500
    assert response.json()["error"]["kind"] == "internal_error"
    assert str(private_model) not in response.text


def test_mode_in_body_is_rejected(client, si_cif: str) -> None:
    """A body carrying mode is rejected; the endpoint selects it."""
    response = client.post(
        "/recommend",
        json={
            "structure": {"content": si_cif, "format": "cif"},
            "hints": {"k_grid": [3, 3, 3]},
            "mode": "recommend",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"
    assert "mode" in response.json()["error"]["message"]


def test_output_dir_on_recommend_is_rejected(client, si_cif: str) -> None:
    """output_dir is rejected on non-bundle endpoints."""
    response = client.post(
        "/recommend",
        json={
            "structure": {"content": si_cif, "format": "cif"},
            "hints": {"k_grid": [3, 3, 3]},
            "output_dir": "run-001",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"
    assert "output_dir" in response.json()["error"]["message"]


def test_unknown_top_level_field_is_rejected(client, si_cif: str) -> None:
    """Unknown top-level fields are rejected rather than ignored."""
    response = client.post(
        "/recommend",
        json={
            "structure": {"content": si_cif, "format": "cif"},
            "hints": {"k_grid": [3, 3, 3]},
            "bogus": 1,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"
    assert "bogus" in response.json()["error"]["message"]


def test_malformed_nested_hints_value_returns_422(client, si_cif: str) -> None:
    """A malformed nested hints value is a deterministic 422, never a 500/TypeError."""
    response = client.post(
        "/recommend",
        json={
            "structure": {"content": si_cif, "format": "cif"},
            "hints": {"k_grid": 3},
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


def test_malformed_nested_pseudo_metadata_returns_422(
    client, si_cif: str, si_pseudo_metadata: dict
) -> None:
    """A malformed nested pseudo_metadata field is a deterministic 422."""
    payload = dict(si_pseudo_metadata)
    payload["is_sssp"] = "yes"
    response = client.post(
        "/recommend",
        json={
            "structure": {"content": si_cif, "format": "cif"},
            "hints": {"k_grid": [3, 3, 3]},
            "pseudo_metadata": [payload],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


def test_bundle_response_path_is_server_relative(
    client, si_cif: str, si_pseudo_metadata: dict, bundle_root: Path
) -> None:
    """The bundle response path is the server-relative output_dir, not absolute."""
    body = _recommend_body(
        si_cif, with_pseudo=True, si_pseudo_metadata=si_pseudo_metadata
    )
    body["output_dir"] = "run-001"

    response = client.post("/bundle", json=body)

    assert response.status_code == 200
    path = response.json()["bundle"]["path"]
    assert path == "run-001"
    assert str(bundle_root) not in response.text


# --- Reviewer probe regressions (issue #44 final): strict JSON parsing ----------


def test_json_nan_constant_returns_422(client) -> None:
    """A NaN literal in the body is rejected as 422, not silently parsed."""
    response = client.post(
        "/recommend",
        data=(
            b'{"structure": {"content": "x", "format": "cif"}, '
            b'"hints": {"k_grid": [3, 3, 3]}, "z": NaN}'
        ),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


def test_json_infinity_constant_returns_422(client) -> None:
    """Infinity/-Infinity literals are rejected as 422."""
    for token in (b"Infinity", b"-Infinity"):
        response = client.post(
            "/recommend",
            data=b'{"structure": {"content": "x", "format": "cif"}, "v": '
            + token
            + b"}",
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["kind"] == "invalid_request"


def test_json_float_overflow_returns_422(client) -> None:
    """Overflow to infinity (1e999) is rejected as 422."""
    response = client.post(
        "/recommend",
        data=(
            b'{"structure": {"content": "x", "format": "cif"}, '
            b'"hints": {"k_grid": [3, 3, 3]}, "v": 1e999}'
        ),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


def test_json_duplicate_top_level_key_returns_422(client) -> None:
    """A duplicate top-level key is rejected as 422, not last-wins."""
    response = client.post(
        "/recommend",
        data=(
            b'{"structure": {"content": "x", "format": "cif"}, '
            b'"hints": {"k_grid": [3, 3, 3]}, "hints": {"k_grid": [4, 4, 4]}}'
        ),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


def test_json_duplicate_nested_key_returns_422(client, si_cif: str) -> None:
    """A duplicate key at a nested level is rejected as 422."""
    response = client.post(
        "/recommend",
        data=(
            b'{"structure": {"content": "' + si_cif.encode() + b'", "format": "cif"}, '
            b'"hints": {"k_grid": [3, 3, 3], "k_grid": [4, 4, 4]}}'
        ),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


def test_malformed_utf8_body_returns_422(client) -> None:
    """A body with invalid UTF-8 is rejected as 422."""
    response = client.post(
        "/recommend",
        data=b'{"structure": {"content": "x", "format": "cif"}\xff}',
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


# --- Reviewer probe regressions (issue #44 final): strict structure sub-schema ---


def test_unknown_structure_key_returns_422(client, si_cif: str) -> None:
    """Unknown structure sub-keys map to 422."""
    response = client.post(
        "/recommend",
        json={"structure": {"content": si_cif, "format": "cif", "bogus": 1}},
    )
    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"
    assert "bogus" in response.json()["error"]["message"]


def test_both_content_and_path_returns_422(client, si_cif: str) -> None:
    """Specifying both content and path maps to 422."""
    response = client.post(
        "/recommend",
        json={"structure": {"content": si_cif, "path": "Si.cif"}},
    )
    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


def test_format_with_path_returns_422(client) -> None:
    """A non-null format alongside path maps to 422."""
    response = client.post(
        "/recommend",
        json={"structure": {"path": "Si.cif", "format": "cif"}},
    )
    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


# --- Reviewer probe regressions (issue #44 final): malformed path strings -------


def test_nul_in_structure_path_returns_422_not_400(client) -> None:
    """An embedded NUL in structure.path is a 422 invalid_request, not 400."""
    response = client.post(
        "/recommend",
        json={"structure": {"path": "Si\x00.cif"}, "hints": {"k_grid": [3, 3, 3]}},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["kind"] == "invalid_request"
    assert "stage_error" != body["error"]["kind"]


def test_nul_in_output_dir_returns_422(client, si_cif: str) -> None:
    """An embedded NUL in output_dir is a 422 invalid_request."""
    response = client.post(
        "/bundle",
        json={
            "structure": {"content": si_cif, "format": "cif"},
            "output_dir": "run\x00-001",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


# --- Reviewer probe regressions (issue #44 final): FIFO/special-file confinement --


def test_fifo_structure_file_returns_422_without_blocking(
    structure_root: Path, si_cif: str, tmp_path: Path
) -> None:
    """A FIFO as the final structure file returns 422 without blocking the worker."""
    import os
    import threading

    from fastapi.testclient import TestClient

    from goldilocks_core.jobs import CoreRuntime, Pipeline
    from goldilocks_core.kmesh import resolve_kpoints_from_advice
    from goldilocks_core.server.http import create_app

    os.mkfifo(structure_root / "fifo.cif")
    app = create_app(
        runtime=CoreRuntime(pipeline=Pipeline(kmesh=resolve_kpoints_from_advice)),
        structure_root=structure_root,
        bundle_root=tmp_path / "bundles",
    )

    result_box: dict[str, object] = {}

    def do_request() -> None:
        with TestClient(app) as standalone:
            response = standalone.post(
                "/recommend",
                json={
                    "structure": {"path": "fifo.cif"},
                    "hints": {"k_grid": [3, 3, 3]},
                },
            )
            result_box["status"] = response.status_code
            result_box["body"] = response.json()

    thread = threading.Thread(target=do_request, daemon=True)
    thread.start()
    thread.join(5.0)
    assert not thread.is_alive(), "FIFO structure request blocked the worker"
    assert result_box["status"] == 422
    assert result_box["body"]["error"]["kind"] == "invalid_request"


@pytest.mark.skipif(
    os.geteuid() == 0, reason="file permission denials are unreachable as root"
)
def test_unreadable_structure_file_returns_redacted_500(
    structure_root: Path, si_cif: str, tmp_path: Path
) -> None:
    """EACCES on a structure file is a redacted 500, never a 422 leaking the path."""

    from fastapi.testclient import TestClient

    from goldilocks_core.jobs import CoreRuntime, Pipeline
    from goldilocks_core.kmesh import resolve_kpoints_from_advice
    from goldilocks_core.server.http import create_app

    secret = structure_root / "secret.cif"
    secret.write_text(si_cif)
    secret.chmod(0o000)
    app = create_app(
        runtime=CoreRuntime(pipeline=Pipeline(kmesh=resolve_kpoints_from_advice)),
        structure_root=structure_root,
        bundle_root=tmp_path / "bundles",
    )
    try:
        with TestClient(app, raise_server_exceptions=False) as standalone:
            response = standalone.post(
                "/recommend",
                json={
                    "structure": {"path": "secret.cif"},
                    "hints": {"k_grid": [3, 3, 3]},
                },
            )
    finally:
        secret.chmod(0o600)
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["kind"] == "internal_error"
    # No host path leaks into the redacted 500 response.
    assert str(structure_root) not in response.text
    assert str(secret) not in response.text


# --- Reviewer probe regressions (issue #44 final-2): route-specific FileExists ---


@pytest.mark.parametrize("mode", ["recommend", "generate"])
def test_file_exists_error_in_non_bundle_mode_is_redacted_500(
    mode: str, si_cif: str
) -> None:
    """FileExistsError from a non-bundle stage is a redacted 500, not stage_error.

    Only the bundle publication boundary may surface FileExistsError as a
    stage_error; an internal FileExistsError in /recommend or /generate is an
    unexpected failure redacted to 500 without leaking the host path.
    """
    from fastapi.testclient import TestClient

    from goldilocks_core.jobs import CoreRuntime, Pipeline
    from goldilocks_core.kmesh import resolve_kpoints_from_advice
    from goldilocks_core.server.http import create_app

    runtime = CoreRuntime(pipeline=Pipeline(kmesh=resolve_kpoints_from_advice))

    def explode(_request: object) -> object:
        raise FileExistsError(17, "File exists", "/private/secret-dest")

    runtime.run = explode  # type: ignore[method-assign]
    app = create_app(runtime=runtime, bundle_root=Path("/tmp/bundles"))
    with TestClient(app, raise_server_exceptions=False) as standalone:
        response = standalone.post(
            f"/{mode}",
            json={
                "structure": {"content": si_cif, "format": "cif"},
                "hints": {"k_grid": [3, 3, 3]},
            },
        )

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["kind"] == "internal_error"
    assert "/private/secret-dest" not in response.text
    assert "File exists" not in response.text
    assert "stage_error" not in response.text


def test_file_exists_error_in_bundle_mode_is_stage_error_with_public_path(
    si_cif: str, tmp_path: Path
) -> None:
    """FileExistsError at the bundle publication boundary is a stage_error with
    the server-relative output_dir, never the absolute host path."""
    from fastapi.testclient import TestClient

    from goldilocks_core.jobs import CoreRuntime, Pipeline
    from goldilocks_core.kmesh import resolve_kpoints_from_advice
    from goldilocks_core.server.http import create_app

    runtime = CoreRuntime(pipeline=Pipeline(kmesh=resolve_kpoints_from_advice))

    def explode(_request: object) -> object:
        raise FileExistsError(17, "File exists", "/private/secret-dest")

    runtime.run = explode  # type: ignore[method-assign]
    bundle_root = tmp_path / "bundles"
    app = create_app(runtime=runtime, bundle_root=bundle_root)
    with TestClient(app, raise_server_exceptions=False) as standalone:
        response = standalone.post(
            "/bundle",
            json={
                "structure": {"content": si_cif, "format": "cif"},
                "output_dir": "run-001",
            },
        )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["kind"] == "stage_error"
    assert "run-001" in response.text
    assert "/private/secret-dest" not in response.text
    assert str(bundle_root) not in response.text


# --- Reviewer probe regressions (issue #44 final-2): Unicode path characters ---


def test_unicode_c1_control_in_structure_path_returns_422_not_404(client) -> None:
    """A C1 control (U+0085) in structure.path is 422, not a missing-file 404."""
    response = client.post(
        "/recommend",
        json={
            "structure": {"path": "Si\u0085.cif"},
            "hints": {"k_grid": [3, 3, 3]},
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


def test_unicode_c1_control_in_output_dir_returns_422(client, si_cif: str) -> None:
    """A C1 control (U+0085) in output_dir is 422 and nothing is created."""
    response = client.post(
        "/bundle",
        json={
            "structure": {"content": si_cif, "format": "cif"},
            "output_dir": "run\u0085x",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


def test_unicode_format_char_in_structure_path_returns_422(client) -> None:
    """A format character (U+200B ZERO WIDTH SPACE) in structure.path is 422."""
    response = client.post(
        "/recommend",
        json={
            "structure": {"path": "Si\u200b.cif"},
            "hints": {"k_grid": [3, 3, 3]},
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


# --- Reviewer probe regressions (issue #44 final-2): lone surrogates in JSON ---


@pytest.mark.parametrize(
    "body",
    [
        b'{"structure": {"path": "Si\\ud800.cif"}, "hints": {"k_grid": [3, 3, 3]}}',
        b'{"structure": {"content": "x\\ud800", "format": "cif"}}',
        b'{"structure": {"content": "x", "format": "cif"}, "\\ud800key": 1}',
    ],
)
def test_json_lone_surrogate_returns_422(client, body: bytes) -> None:
    """A JSON-escaped lone surrogate anywhere maps to a deterministic 422.

    A valid surrogate pair (``\\uD800\\uDC00``) decodes to a single supplementary
    code point and is accepted; only unpaired surrogates are rejected.
    """
    response = client.post(
        "/recommend", data=body, headers={"content-type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"
    assert "surrogate" in response.json()["error"]["message"]


def test_json_valid_surrogate_pair_is_accepted(client) -> None:
    """A valid surrogate pair decodes to one code point and is not a lone surrogate.

    ``\\uD800\\uDC00`` decodes to ``U+10000``; it passes the strict-JSON surrogate
    scan and then fails as unparseable CIF content (422 invalid_request) rather
    than being rejected as a surrogate.
    """
    body = b'{"structure": {"content": "x\\uD800\\uDC00", "format": "cif"}}'
    response = client.post(
        "/recommend", data=body, headers={"content-type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"
    assert "surrogate" not in response.json()["error"]["message"]
