from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from goldilocks_core.contracts import (
    JsonDict,
    Records,
    record_type_id,
    to_jsonable,
)


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

    def preset(self, name: str) -> Preset:
        for preset in self.presets:
            if preset.name == name:
                return preset
        raise KeyError(name)


@dataclass(frozen=True, slots=True)
class StageInfo:
    id: str
    name: str
    description: str
    input_record_ids: tuple[str, ...]
    output_record_id: str

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class PresetInfo:
    id: str
    name: str
    output_record_ids: tuple[str, ...]

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class GraphInfo:
    id: str
    revision: str
    name: str
    description: str
    stages: tuple[StageInfo, ...]
    presets: tuple[PresetInfo, ...]
    selectable_record_ids: tuple[str, ...]

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)


def describe_task(task: TaskGraph) -> GraphInfo:
    """Serializes a TaskGraph to string-keyed IDs. Same input as execute()."""
    stages = tuple(
        StageInfo(
            id=stage.id,
            name=stage.name,
            description=stage.description,
            input_record_ids=tuple(record_type_id(item) for item in stage.inputs),
            output_record_id=record_type_id(stage.output),
        )
        for stage in task.stages
    )
    presets = tuple(
        PresetInfo(
            id=preset.name,
            name=preset.name,
            output_record_ids=tuple(
                record_type_id(output) for output in preset.outputs
            ),
        )
        for preset in task.presets
    )
    return GraphInfo(
        id=task.task,
        revision=task.revision,
        name=task.name,
        description=task.description,
        stages=stages,
        presets=presets,
        selectable_record_ids=tuple(
            record_type_id(output) for output in task.selectable_outputs
        ),
    )


def execute(
    task: TaskGraph,
    outputs: tuple[type, ...],
    context: Any,
) -> Records:
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

    return Records({output_type: memo[output_type] for output_type in outputs})
