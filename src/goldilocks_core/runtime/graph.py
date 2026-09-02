from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from goldilocks_core.result import Records
from goldilocks_core.runtime.registry import record_type_id


class UnknownPreset(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Stage:
    output: type
    inputs: tuple[type, ...]
    call: Callable[..., Any]
    id: str = ""
    name: str = ""
    description: str = ""


@dataclass(frozen=True, slots=True)
class Preset:
    name: str
    outputs: tuple[type, ...]


@dataclass(frozen=True, slots=True)
class TaskGraph:
    task: str
    stages: tuple[Stage, ...]
    presets: tuple[Preset, ...]
    name: str = ""
    description: str = ""
    revision: str = "1"
    selectable_outputs: tuple[type, ...] = ()
    record_ids: tuple[tuple[type, str], ...] = ()

    def __post_init__(self) -> None:
        produced: set[type] = set()
        for stage in self.stages:
            if stage.output in produced:
                raise ValueError(
                    "TaskGraph must define exactly one producer for each Record type; "
                    f"multiple stages produce {stage.output.__name__}"
                )
            produced.add(stage.output)

        ids = tuple(record_id for _, record_id in self.record_ids)
        if any(
            not isinstance(record_id, str) or not record_id.strip() for record_id in ids
        ):
            raise ValueError("TaskGraph record ids must be non-empty strings")
        if len(ids) != len(set(ids)):
            raise ValueError("TaskGraph record ids must be unique")

    def record_id(self, record_type: type) -> str:
        local_ids = dict(self.record_ids)
        return (
            local_ids[record_type]
            if record_type in local_ids
            else record_type_id(record_type)
        )

    def preset(self, name: str) -> Preset:
        for preset in self.presets:
            if preset.name == name:
                return preset
        available = ", ".join(sorted(item.name for item in self.presets)) or "none"
        raise UnknownPreset(
            f"Unknown preset {name!r} for task {self.task!r}. Available: {available}"
        )


def describe_task(task: TaskGraph) -> dict[str, Any]:
    """Serializes a TaskGraph to string-keyed IDs. Same input as execute()."""
    return {
        "id": task.task,
        "revision": task.revision,
        "name": task.name,
        "description": task.description,
        "stages": [
            {
                "id": stage.id,
                "name": stage.name,
                "description": stage.description,
                "input_record_ids": [task.record_id(item) for item in stage.inputs],
                "output_record_id": task.record_id(stage.output),
            }
            for stage in task.stages
        ],
        "presets": [
            {
                "id": preset.name,
                "name": preset.name,
                "output_record_ids": [
                    task.record_id(output) for output in preset.outputs
                ],
            }
            for preset in task.presets
        ],
        "selectable_record_ids": [
            task.record_id(output) for output in task.selectable_outputs
        ],
    }


@dataclass(frozen=True, slots=True)
class GraphExecution:
    records: Records
    produced: Records


def execute_graph(
    task: TaskGraph,
    outputs: tuple[type, ...],
    context: Any,
) -> GraphExecution:
    producers = {stage.output: stage for stage in task.stages}
    ordered: list[Stage] = []
    visiting: set[type] = set()
    resolved: set[type] = set()

    def visit(record_type: type) -> None:
        if record_type in resolved:
            return
        if record_type in visiting:
            raise ValueError(f"Cycle detected while resolving {record_type.__name__}")

        stage = producers.get(record_type)
        if stage is None:
            raise ValueError(
                f"No stage produces required record type {record_type.__name__}"
            )

        visiting.add(record_type)
        for input_type in stage.inputs:
            visit(input_type)
        visiting.remove(record_type)
        resolved.add(record_type)
        ordered.append(stage)

    for output_type in outputs:
        visit(output_type)

    memo: dict[type, Any] = {}
    for stage in ordered:
        arguments = tuple(memo[input_type] for input_type in stage.inputs)
        memo[stage.output] = stage.call(*arguments, ctx=context)

    return GraphExecution(
        records=Records({output_type: memo[output_type] for output_type in outputs}),
        produced=Records(memo),
    )


def execute(
    task: TaskGraph,
    outputs: tuple[type, ...],
    context: Any,
) -> Records:
    return execute_graph(task, outputs, context).records
