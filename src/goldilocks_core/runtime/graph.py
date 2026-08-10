"""Type-keyed dependency graph execution for pipeline stages.

The executor is deliberately stage-agnostic: it resolves a task's graph from
each stage's declared input and output record types, runs the minimal
subgraph for the requested outputs, and passes one opaque context object to
every stage as ``ctx``. It knows nothing about what stages do or what services
they need -- those belong to the task definition and the runtime that builds
the context.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from goldilocks_core.contracts import CoreRecords


@dataclass(frozen=True, slots=True)
class StageSpec:
    """One record-producing stage and its record dependencies.

    ``call`` receives the matched upstream records positionally plus the run
    context as the keyword ``ctx`` and returns its output record.
    """

    output: type
    inputs: tuple[type, ...]
    call: Callable[..., Any]


@dataclass(frozen=True, slots=True)
class Preset:
    """Name a complete output set for a task."""

    name: str
    outputs: tuple[type, ...]


@dataclass(frozen=True, slots=True)
class TaskSpec:
    """The stages and named output sets for one task."""

    task: str
    stages: tuple[StageSpec, ...]
    presets: tuple[Preset, ...]

    def preset(self, name: str) -> Preset:
        """Return the preset with the given name."""
        for preset in self.presets:
            if preset.name == name:
                return preset
        raise KeyError(name)


def execute(
    task: TaskSpec,
    outputs: tuple[type, ...],
    context: Any,
) -> CoreRecords:
    """Resolve and execute the minimal subgraph for the requested outputs.

    Stages are ordered by a topological walk over their record dependencies,
    run once each, and memoized by output type within this call. ``context`` is
    handed to every stage as ``ctx`` without inspection.
    """
    producers = {stage.output: stage for stage in task.stages}
    ordered: list[StageSpec] = []
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
        missing = tuple(
            input_type for input_type in stage.inputs if input_type not in memo
        )
        if missing:
            names = ", ".join(input_type.__name__ for input_type in missing)
            raise ValueError(
                f"Stage producing {stage.output.__name__} has unresolved inputs: "
                f"{names}"
            )
        arguments = tuple(memo[input_type] for input_type in stage.inputs)
        memo[stage.output] = stage.call(*arguments, ctx=context)

    return CoreRecords({output_type: memo[output_type] for output_type in outputs})
