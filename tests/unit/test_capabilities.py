from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import pytest

from goldilocks_core import Service
from goldilocks_core.contracts.registry import RECORD_TYPE_IDS
from goldilocks_core.runtime import GraphHandler, Preset, Runtime, Stage, TaskGraph


@pytest.fixture
def isolated_record_registry():
    registered = dict(RECORD_TYPE_IDS)
    yield
    RECORD_TYPE_IDS.clear()
    RECORD_TYPE_IDS.update(registered)


def test_service_capabilities_discovers_portable_scientific_choices() -> None:
    with Service() as service:
        document = service.capabilities().to_dict()

    task = next(task for task in document["tasks"] if task["id"] == "scf_single_point")
    assert {preset["id"] for preset in task["presets"]} == {"recommend", "generate"}
    assert set(task["selectable_record_ids"]) == {
        "analysis",
        "advice",
        "k_points",
        "selection",
        "generated_files",
    }
    assert {model["role"] for model in document["models"]} == {
        "k_point_advisor",
        "metallicity_classifier",
    }
    for catalog in (document["models"], document["pseudopotential_sets"]):
        assert all(
            not {"location", "path", "root", "installed"}.intersection(item)
            for item in catalog
        )


def test_custom_model_registry_rejects_path_like_source_labels(tmp_path: Path) -> None:
    registry = tmp_path / "models.toml"
    packaged = (
        resources.files("goldilocks_core.ml")
        .joinpath("registry.toml")
        .read_text(encoding="utf-8")
    )
    registry.write_text(
        packaged.replace(
            'model_type = "random_forest"',
            'model_type = "random_forest"\nsource = "/home/operator/model"',
            1,
        ),
        encoding="utf-8",
    )
    with Runtime(registry_path=registry) as runtime, pytest.raises(ValueError):
        Service(runtime).capabilities()


def test_duplicate_record_producers_are_rejected_at_task_declaration() -> None:
    class DuplicateRecord:
        pass

    with pytest.raises(ValueError):
        TaskGraph(
            task="duplicate_producers",
            stages=(
                Stage(DuplicateRecord, (), lambda *, ctx: "first", id="first"),
                Stage(DuplicateRecord, (), lambda *, ctx: "second", id="second"),
            ),
            presets=(),
        )


def test_registered_future_task_appears_without_a_new_service_method(
    isolated_record_registry,
) -> None:
    @dataclass(frozen=True, slots=True)
    class FutureRecord:
        value: str

    handler = GraphHandler(
        spec=TaskGraph(
            task="future_task",
            revision="7",
            stages=(
                Stage(
                    FutureRecord,
                    (),
                    lambda *, ctx: FutureRecord("future"),
                    id="produce_future",
                ),
            ),
            presets=(Preset("review", (FutureRecord,)),),
            selectable_outputs=(FutureRecord,),
            record_ids=((FutureRecord, "future_record"),),
        ),
        build_context=lambda request, normalized, runtime: object(),
    )
    with Service(task_handlers=(handler,)) as service:
        capabilities = service.capabilities()

    tasks = {task.id: task for task in capabilities.tasks}
    assert tuple(tasks) == ("future_task", "scf_single_point")
    assert tasks["future_task"].revision == "7"
    assert tasks["future_task"].presets[0].output_record_ids == ("future_record",)
    assert tasks["future_task"].selectable_record_ids == ("future_record",)
    for catalog in (capabilities.models, capabilities.pseudopotential_sets):
        ids = [item.id for item in catalog]
        assert ids == sorted(ids)


def test_capabilities_only_advertise_elements_allowed_by_selection_policy() -> None:
    with Service() as service:
        tables = {
            table.id: set(table.supported_elements)
            for table in service.capabilities().pseudopotential_sets
        }

    assert tables["pseudodojo-pbe-lanthanides-sr"] == set()
    assert "Ce" in tables["sssp-pbe-efficiency-sr"]
    assert "Si" in tables["pseudodojo-pbe-efficiency-fr"]
