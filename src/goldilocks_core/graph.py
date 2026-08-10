"""Type-keyed dependency graph execution for Core pipeline stages."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pymatgen.core import Structure

from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    CoreRecords,
    ElectronicCharacter,
    KMeshAdvisor,
    KPointSelection,
)
from goldilocks_core.pseudo.pp_metadata import PseudoMetadata


@dataclass(frozen=True, slots=True)
class StageSpec:
    """Describe one record-producing stage and its record dependencies."""

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
    """Describe the stages and named output sets for one task."""

    task: str
    stages: tuple[StageSpec, ...]
    presets: tuple[Preset, ...]

    def preset(self, name: str) -> Preset:
        """Return the preset with the given name."""
        for preset in self.presets:
            if preset.name == name:
                return preset
        raise KeyError(name)


def _missing_kmesh_backend(structure: Structure) -> KPointSelection:
    raise ValueError(
        "RunContext.kmesh_backend is required for stages that resolve k-points"
    )


def _heuristic_metallicity(
    structure: Structure,
) -> tuple[ElectronicCharacter, str, float | None]:
    return "unknown", "heuristic", None


@dataclass(frozen=True, slots=True)
class RunContext:
    """Carry request data and runtime services alongside graph records."""

    intent: CalculationIntent = field(default_factory=CalculationIntent)
    hints: CalculationHints = field(default_factory=CalculationHints)
    pseudo_metadata: tuple[PseudoMetadata, ...] = ()
    kmesh_backend: KMeshAdvisor = _missing_kmesh_backend
    metallicity_classifier: Callable[
        [Structure], tuple[ElectronicCharacter, str, float | None]
    ] = _heuristic_metallicity


def execute(
    task: TaskSpec,
    outputs: tuple[type, ...],
    context: RunContext,
) -> CoreRecords:
    """Resolve and execute the minimal subgraph for the requested outputs."""
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
