"""Type-keyed dependency graph execution for pipeline stages.

The executor is deliberately stage-agnostic: it resolves a task's graph from
each stage's declared input and output record types, runs the minimal
subgraph for the requested outputs, and passes one opaque context object to
every stage as ``ctx``. It knows nothing about what stages do or what services
they need -- those belong to the task definition and the runtime that builds
the context.

Transport-safe task descriptions (:func:`describe_task`) read the same specs
the executor runs, so a task's published description cannot drift from the
graph that actually executes. Stage and record identifiers are backend-owned
stable strings (see :func:`goldilocks_core.contracts.record_type_id`); no
Python class names or callables cross the transport boundary.
"""

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
    """One record-producing stage and its record dependencies.

    ``call`` receives the matched upstream records positionally plus the run
    context as the keyword ``ctx`` and returns its output record. ``id``,
    ``name``, and ``description`` are stable transport metadata read by
    :func:`describe_task`; they live on the stage so the published description
    cannot drift from the stage that executes.
    """

    output: type
    inputs: tuple[type, ...]
    call: Callable[..., Any]
    id: str = ""
    name: str = ""
    description: str = ""


@dataclass(frozen=True, slots=True)
class Preset:
    """Name a complete output set for a task."""

    name: str
    outputs: tuple[type, ...]


@dataclass(frozen=True, slots=True)
class TaskGraph:
    """The stages and named output sets for one task.

    ``task`` is the stable task identifier; ``name``, ``description``, and
    ``revision`` are semantic metadata surfaced by :func:`describe_task`.
    ``selectable_outputs`` is the set of record types a query caller may
    request from this task's graph -- the task owns it because what is
    selectable is a task decision, not an executor one.
    """

    task: str
    stages: tuple[Stage, ...]
    presets: tuple[Preset, ...]
    name: str = ""
    description: str = ""
    revision: str = "1"
    selectable_outputs: tuple[type, ...] = ()

    def preset(self, name: str) -> Preset:
        """Return the preset with the given name."""
        for preset in self.presets:
            if preset.name == name:
                return preset
        raise KeyError(name)


@dataclass(frozen=True, slots=True)
class StageInfo:
    """Transport-safe description of one graph stage."""

    id: str
    name: str
    description: str
    input_record_ids: tuple[str, ...]
    output_record_id: str

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class PresetInfo:
    """Transport-safe description of one named output preset."""

    id: str
    name: str
    output_record_ids: tuple[str, ...]

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class GraphInfo:
    """Backend-owned, transport-safe description of one task.

    Carries stable task, stage, and record identifiers plus semantic names and
    descriptions. It never exposes Python callables or class names and carries
    no frontend or layout metadata.
    """

    id: str
    revision: str
    name: str
    description: str
    stages: tuple[StageInfo, ...]
    presets: tuple[PresetInfo, ...]
    selectable_record_ids: tuple[str, ...]

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


def describe_task(task: TaskGraph) -> GraphInfo:
    """Serialize a :class:`TaskSpec` into a transport-safe description.

    Stage and record identifiers are stable backend-owned strings read from the
    spec itself; no Python callables or class names are serialized.
    """
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
    """Resolve and execute the minimal subgraph for the requested outputs.

    Stages are ordered by a topological walk over their record dependencies,
    run once each, and memoized by output type within this call. ``context`` is
    handed to every stage as ``ctx`` without inspection.
    """
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
