"""Tests for the backend-owned task description HTTP operation."""

import pytest

from goldilocks_core.server.http import create_app

TestClient = pytest.importorskip("fastapi.testclient").TestClient


def test_tasks_returns_stable_task_description(test_runtime) -> None:
    """Expose one task with stable ids and no Python implementation details."""
    with TestClient(create_app(test_runtime)) as client:
        response = client.get("/tasks")

    assert response.status_code == 200
    tasks = response.json()["tasks"]
    assert len(tasks) == 1
    task = tasks[0]
    assert task["id"] == "scf_single_point"
    assert task["revision"] == "1"
    assert task["name"] == "Single-point SCF"


def test_tasks_describes_stages_with_dependencies(test_runtime) -> None:
    """Report stage ids, record dependencies, and output records."""
    with TestClient(create_app(test_runtime)) as client:
        task = client.get("/tasks").json()["tasks"][0]

    stage_ids = [stage["id"] for stage in task["stages"]]
    assert "analyze" in stage_ids
    analyze = next(s for s in task["stages"] if s["id"] == "analyze")
    assert analyze["input_record_ids"] == ["structure"]
    assert analyze["output_record_id"] == "analysis"
    assert all(" " not in s["id"] for s in task["stages"])


def test_tasks_exposes_presets_and_selectable_records(test_runtime) -> None:
    """Report preset output sets and the queryable record identifiers."""
    with TestClient(create_app(test_runtime)) as client:
        task = client.get("/tasks").json()["tasks"][0]

    preset_ids = {preset["id"] for preset in task["presets"]}
    assert preset_ids == {"recommend", "generate"}
    generate = next(p for p in task["presets"] if p["id"] == "generate")
    assert "generated_files" in generate["output_record_ids"]
    assert "analysis" in task["selectable_record_ids"]


def test_tasks_serialization_has_no_python_implementation_details(
    test_runtime,
) -> None:
    """Never leak callables or class names into the serialized description."""
    with TestClient(create_app(test_runtime)) as client:
        raw = client.get("/tasks").content.decode("utf-8")

    assert "callable" not in raw
    assert "lambda" not in raw
    assert "<class" not in raw
    assert "TaskSpec" not in raw
