"""Tests that OpenAPI carries concrete request and response bodies."""

import pytest

from goldilocks_core.server.http import create_app

TestClient = pytest.importorskip("fastapi.testclient").TestClient


def _openapi(runtime):
    """Return the generated OpenAPI document for an app over ``runtime``."""
    return create_app(runtime).openapi()


def test_openapi_has_typed_request_bodies(test_runtime) -> None:
    """Request bodies reference concrete schemas, not generic dictionaries."""
    spec = _openapi(test_runtime)

    for path, method in (
        ("/recommend", "post"),
        ("/generate", "post"),
        ("/compute", "post"),
    ):
        request_body = spec["paths"][path][method]["requestBody"]
        schema = request_body["content"]["application/json"]["schema"]
        assert "$ref" in schema, f"{path} request body must be a typed schema"


def test_openapi_has_typed_response_bodies(test_runtime) -> None:
    """Documented 200 responses reference concrete schemas."""
    spec = _openapi(test_runtime)

    for path, method in (
        ("/recommend", "post"),
        ("/generate", "post"),
        ("/compute", "post"),
        ("/structure/load", "post"),
        ("/tasks", "get"),
    ):
        response = spec["paths"][path][method]["responses"]["200"]
        assert "content" in response, f"{path} must document a response body"


def test_openapi_exposes_structure_and_task_operations(test_runtime) -> None:
    """List the new resource-oriented operations alongside presets."""
    spec = _openapi(test_runtime)

    assert "/structure/load" in spec["paths"]
    assert "/tasks" in spec["paths"]


def test_openapi_structure_source_has_no_server_path_fields(test_runtime) -> None:
    """The structure-load body accepts inline content and format only."""
    spec = _openapi(test_runtime)
    schema_name = spec["paths"]["/structure/load"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]["$ref"].split("/")[-1]
    properties = spec["components"]["schemas"][schema_name]["properties"]

    assert set(properties) == {"content", "format"}


def test_openapi_workbench_requests_are_inline_structure_only(test_runtime) -> None:
    """Recommend/generate/compute accept inline StructureSource, never a path."""
    spec = _openapi(test_runtime)
    components = spec["components"]["schemas"]

    for path, method in (
        ("/recommend", "post"),
        ("/generate", "post"),
        ("/compute", "post"),
    ):
        request_body = spec["paths"][path][method]["requestBody"]
        content = request_body["content"]["application/json"]
        name = content["schema"]["$ref"].split("/")[-1]
        properties = components[name]["properties"]
        assert properties["structure"]["$ref"].endswith("/StructureSource"), path
        assert "output_dir" not in properties, path
        assert "pseudo_root" not in properties, path


def test_openapi_request_schemas_advertise_no_server_paths(test_runtime) -> None:
    """No HTTP request schema declares a client-controlled server path field."""
    spec = _openapi(test_runtime)

    for name, schema in spec["components"]["schemas"].items():
        for prop in schema.get("properties", {}):
            assert prop not in {"output_dir", "pseudo_root"}, (
                f"schema {name} exposes server-path field {prop!r}"
            )

    pseudo_props = spec["components"]["schemas"]["PseudoMetadata"]["properties"]
    assert "filepath" not in pseudo_props
    assert "filename" in pseudo_props


def test_openapi_response_selection_has_no_server_path(test_runtime) -> None:
    """The Workbench selection response never exposes a server filesystem path."""
    spec = _openapi(test_runtime)
    selection = spec["components"]["schemas"]["PseudopotentialSelectionModel"][
        "properties"
    ]
    assert "filepath" not in selection
    assert "filename" in selection
