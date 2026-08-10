"""Tests for the canonical structure-load HTTP operation."""

import pytest

from goldilocks_core.server.http import create_app

TestClient = pytest.importorskip("fastapi.testclient").TestClient


def _load(client: TestClient, body: dict) -> object:
    """POST a structure source and return the parsed response."""
    return client.post("/structure/load", json=body)


def test_structure_load_returns_canonical_document(
    test_runtime, sample_structure_text: str
) -> None:
    """Validate inline CIF content into a canonical StructureDocument."""
    with TestClient(create_app(test_runtime)) as client:
        response = _load(client, {"content": sample_structure_text, "format": "cif"})

    assert response.status_code == 200
    document = response.json()
    assert document["reduced_formula"] == "Si"
    assert document["lattice"]["pbc"] == [True, True, True]
    assert document["source"]["format"] == "cif"
    assert document["sites"][0]["species"][0]["element"] == "Si"
    assert "@module" not in document


def _si_poscar() -> str:
    """Return a minimal valid silicon POSCAR."""
    return "Si\n1.0\n3.5 0 0\n0 3.5 0\n0 0 3.5\nSi\n1\nDirect\n0 0 0\n"


def test_structure_load_accepts_poscar(test_runtime) -> None:
    """Validate inline POSCAR content into a canonical StructureDocument."""
    with TestClient(create_app(test_runtime)) as client:
        response = _load(client, {"content": _si_poscar(), "format": "poscar"})

    assert response.status_code == 200
    assert response.json()["reduced_formula"] == "Si"


def test_structure_load_accepts_content_without_format(
    test_runtime, sample_structure_text: str
) -> None:
    """Detect the format when none is supplied."""
    with TestClient(create_app(test_runtime)) as client:
        response = _load(client, {"content": sample_structure_text})

    assert response.status_code == 200
    assert response.json()["reduced_formula"] == "Si"


def test_structure_load_rejects_malformed_content(test_runtime, request_body) -> None:
    """Surface a parse failure as a structured invalid_request error."""
    with TestClient(create_app(test_runtime)) as client:
        response = _load(client, {"content": "not a structure", "format": "cif"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["kind"] == "invalid_request"
    assert "Could not parse" in error["message"]


def test_structure_load_rejects_path_shaped_and_unknown_fields(test_runtime) -> None:
    """Reject path-shaped or unknown fields; only inline content is accepted."""
    with TestClient(create_app(test_runtime)) as client:
        path_field = _load(
            client, {"content": "anything", "format": "cif", "filepath": "/etc/passwd"}
        )
        unknown_field = _load(client, {"path": "/pseudo/Si.cif", "format": "cif"})

    for response in (path_field, unknown_field):
        assert response.status_code == 422
