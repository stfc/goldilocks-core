from __future__ import annotations


def _recommend_body(si_cif_path, si_pseudo_metadata: dict) -> dict:
    """Return a /recommend-shaped body with an explicit k-grid hint."""
    return {
        "structure": str(si_cif_path),
        "hints": {"k_grid": [3, 3, 3]},
        "pseudo_metadata": [si_pseudo_metadata],
    }


def test_health_returns_ok_without_running_a_job(http_client) -> None:
    """GET /health reports liveness and does not load models."""
    response = http_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_recommend_returns_core_result_json(
    http_client, si_cif_path, si_pseudo_metadata: dict
) -> None:
    """POST /recommend returns a CoreResult JSON with k_points and selection."""
    response = http_client.post(
        "/recommend", json=_recommend_body(si_cif_path, si_pseudo_metadata)
    )

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
    assert data["k_points"]["grid"] == [3, 3, 3]
    assert data["k_points"]["provenance"]["source"] == "user_hint"
    assert data["analysis"]["reduced_formula"] == "Si"
    assert data["generated_files"] == []
    assert data["bundle"] is None


def test_generate_returns_generated_files(
    http_client, si_cif_path, si_pseudo_metadata: dict
) -> None:
    """POST /generate runs through Generate and returns generated input files."""
    body = _recommend_body(si_cif_path, si_pseudo_metadata)
    body["mode"] = "generate"

    response = http_client.post("/generate", json=body)

    assert response.status_code == 200
    data = response.json()
    assert [f["path"] for f in data["generated_files"]] == ["inputs/qe.in"]
    assert "CONTROL" in data["generated_files"][0]["content"]
    assert data["bundle"] is None


def test_generate_with_output_dir_includes_bundle(
    http_client, si_cif_path, si_pseudo_metadata: dict, tmp_path
) -> None:
    """POST /generate with output_dir in the body includes a bundle record."""
    body = _recommend_body(si_cif_path, si_pseudo_metadata)
    body["mode"] = "generate"
    output_dir = tmp_path / "bundle"
    body["output_dir"] = str(output_dir)

    response = http_client.post("/generate", json=body)

    assert response.status_code == 200
    data = response.json()
    assert data["bundle"] is not None
    assert (output_dir / "inputs" / "qe.in").exists()


def test_analyze_returns_analysis_record(http_client, si_cif_path) -> None:
    """POST /analyze returns the StructureAnalysisRecord JSON."""
    response = http_client.post(
        "/analyze",
        json={"structure": str(si_cif_path), "hints": {"k_grid": [3, 3, 3]}},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["reduced_formula"] == "Si"
    assert "Si" in data["elements"]


def test_kmesh_returns_kpoint_selection(http_client, si_cif_path) -> None:
    """POST /kmesh returns the KPointSelection JSON."""
    response = http_client.post(
        "/kmesh",
        json={"structure": str(si_cif_path), "hints": {"k_grid": [4, 4, 4]}},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["grid"] == [4, 4, 4]
    assert data["provenance"]["source"] == "user_hint"


def test_advise_returns_parameter_advice(
    http_client, si_cif_path, si_pseudo_metadata: dict
) -> None:
    """POST /advise returns the ParameterAdvice JSON."""
    response = http_client.post(
        "/advise",
        json=_recommend_body(si_cif_path, si_pseudo_metadata),
    )

    assert response.status_code == 200
    data = response.json()
    assert "smearing" in data
    assert "magnetism" in data
    assert "pseudopotentials" in data


def test_select_returns_selection_record(
    http_client, si_cif_path, si_pseudo_metadata: dict
) -> None:
    """POST /select returns the SelectionRecord JSON."""
    response = http_client.post(
        "/select",
        json=_recommend_body(si_cif_path, si_pseudo_metadata),
    )

    assert response.status_code == 200
    data = response.json()
    assert "pseudopotentials" in data
    assert data["pseudopotentials"][0]["element"] == "Si"


def test_missing_structure_returns_422(http_client) -> None:
    """A body without a structure field maps to 422."""
    response = http_client.post("/recommend", json={"hints": {"k_grid": [3, 3, 3]}})

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


def test_unknown_field_returns_422(http_client, si_cif_path) -> None:
    """An unknown top-level key maps to 422."""
    response = http_client.post(
        "/recommend",
        json={
            "structure": str(si_cif_path),
            "bogus": 1,
            "hints": {"k_grid": [3, 3, 3]},
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


def test_empty_body_returns_422(http_client) -> None:
    """An empty request body maps to 422."""
    response = http_client.post("/recommend", data=b"")

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


def test_invalid_json_returns_422(http_client) -> None:
    """Malformed JSON maps to 422 invalid_request."""
    response = http_client.post(
        "/recommend",
        data=b"{not valid json",
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


def test_non_object_json_body_returns_422(http_client) -> None:
    """A JSON array body maps to 422."""
    response = http_client.post("/recommend", json=[1, 2, 3])

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


def test_missing_structure_file_returns_404(http_client) -> None:
    """A path to a nonexistent structure file maps to 404."""
    response = http_client.post(
        "/recommend",
        json={"structure": "/nonexistent/structure.cif"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["kind"] == "not_found"


def test_unparseable_inline_content_returns_422(http_client) -> None:
    """Garbage inline structure content maps to 422."""
    response = http_client.post(
        "/recommend",
        json={"structure": {"content": "not a structure", "format": "cif"}},
    )

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_request"


def test_stage_error_returns_4xx_with_reason(
    http_client, si_cif_path, si_pseudo_metadata: dict
) -> None:
    """A stage ValueError (unsupported task) maps to 400 with the reason preserved."""
    body = _recommend_body(si_cif_path, si_pseudo_metadata)
    body["mode"] = "generate"
    body["intent"] = {"code": "quantum_espresso", "task": "nonexistent_task"}

    response = http_client.post("/generate", json=body)

    assert response.status_code == 400
    data = response.json()
    assert data["error"]["kind"] == "stage_error"
    assert "No input writer" in data["error"]["message"]
