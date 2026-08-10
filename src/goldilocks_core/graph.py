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
    GeneratedFiles,
    KMeshAdvisor,
    KPointSelection,
    ParameterAdvice,
    SelectionRecord,
    StructureAnalysisRecord,
    StructureInput,
    record_type_id,
)
from goldilocks_core.contracts.outputs import OUTPUT_RECORD_TYPES
from goldilocks_core.contracts.serial import to_jsonable
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
    """Describe the stages and named output sets for one task.

    ``task`` is the stable task identifier; ``name``, ``description``, and
    ``revision`` are semantic metadata surfaced by the transport description.
    They live on the task so descriptions cannot drift from the registered
    task that owns them.
    """

    task: str
    stages: tuple[StageSpec, ...]
    presets: tuple[Preset, ...]
    name: str = ""
    description: str = ""
    revision: str = "1"

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

    structure_input: StructureInput
    intent: CalculationIntent = field(default_factory=CalculationIntent)
    hints: CalculationHints = field(default_factory=CalculationHints)
    pseudo_metadata: tuple[PseudoMetadata, ...] = ()
    kmesh_backend: KMeshAdvisor = _missing_kmesh_backend
    metallicity_classifier: Callable[
        [Structure], tuple[ElectronicCharacter, str, float | None]
    ] = _heuristic_metallicity


_STAGE_META: dict[type, tuple[str, str, str]] = {
    Structure: (
        "load_structure",
        "Load structure",
        "Parse and validate the source into a canonical Structure Document.",
    ),
    StructureAnalysisRecord: (
        "analyze",
        "Analyze",
        "Report structure facts without parameter decisions.",
    ),
    KPointSelection: (
        "resolve_k_points",
        "Resolve k-points",
        "Choose the k-point grid from operator hints or a model.",
    ),
    ParameterAdvice: (
        "advise",
        "Advise",
        "Recommend provenance-backed calculation parameters.",
    ),
    SelectionRecord: (
        "select_pseudopotentials",
        "Select pseudopotentials",
        "Select a concrete pseudopotential for each element.",
    ),
    GeneratedFiles: (
        "generate_inputs",
        "Generate inputs",
        "Produce target-code input files.",
    ),
}
"""Stable transport-safe stage metadata keyed by output record type."""


@dataclass(frozen=True, slots=True)
class StageDescription:
    """Transport-safe description of one graph stage."""

    id: str
    name: str
    description: str
    input_record_ids: tuple[str, ...]
    output_record_id: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class PresetDescription:
    """Transport-safe description of one named output preset."""

    id: str
    name: str
    output_record_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class TaskGraphDescription:
    """Backend-owned, transport-safe description of one task.

    Carries stable task, stage, and record identifiers plus semantic names
    and descriptions. It never exposes Python callables or class names, and it
    contains no frontend or layout metadata.
    """

    id: str
    revision: str
    name: str
    description: str
    stages: tuple[StageDescription, ...]
    presets: tuple[PresetDescription, ...]
    selectable_record_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class TaskCatalogue:
    """Transport-safe catalogue of every registered task description."""

    tasks: tuple[TaskGraphDescription, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


def _stage_meta(record_type: type) -> tuple[str, str, str]:
    """Return stable stage metadata, falling back to the record id."""
    record_id = record_type_id(record_type)
    return _STAGE_META.get(
        record_type,
        (record_id, record_id, "Produce this record from its graph dependencies."),
    )


def describe_task(task: TaskSpec) -> TaskGraphDescription:
    """Serialize a TaskSpec into a transport-safe TaskGraphDescription.

    Stage and record identifiers are stable backend-owned strings; no Python
    callables or class names are serialized.
    """
    stages = tuple(
        StageDescription(
            id=_stage_meta(stage.output)[0],
            name=_stage_meta(stage.output)[1],
            description=_stage_meta(stage.output)[2],
            input_record_ids=tuple(record_type_id(item) for item in stage.inputs),
            output_record_id=record_type_id(stage.output),
        )
        for stage in task.stages
    )
    presets = tuple(
        PresetDescription(
            id=preset.name,
            name=preset.name,
            output_record_ids=tuple(
                record_type_id(output) for output in preset.outputs
            ),
        )
        for preset in task.presets
    )
    return TaskGraphDescription(
        id=task.task,
        revision=task.revision,
        name=task.name,
        description=task.description,
        stages=stages,
        presets=presets,
        selectable_record_ids=tuple(
            record_type_id(record_type) for record_type in OUTPUT_RECORD_TYPES
        ),
    )


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
