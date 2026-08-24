from __future__ import annotations

from dataclasses import dataclass

from goldilocks_core.contracts.hints import CalculationHints, CalculationIntent
from goldilocks_core.contracts.serial import to_jsonable
from goldilocks_core.contracts.types import JsonDict


@dataclass(frozen=True, slots=True)
class StageCapability:
    id: str
    name: str
    description: str
    input_record_ids: tuple[str, ...]
    output_record_id: str

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class PresetCapability:
    id: str
    name: str
    output_record_ids: tuple[str, ...]

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class CalculationTaskCapability:
    id: str
    revision: str
    name: str
    description: str
    stages: tuple[StageCapability, ...]
    presets: tuple[PresetCapability, ...]
    selectable_record_ids: tuple[str, ...]

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class ModelCapability:
    id: str
    name: str
    version: str
    role: str
    model_type: str
    target: str
    feature_set: str
    source: str
    revision: str | None

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class PseudopotentialSetCapability:
    id: str
    version: str
    provider: str
    upstream_name: str
    functional: str
    accuracy: str
    relativistic_treatment: str
    supported_elements: tuple[str, ...]
    licence: str
    citation: str
    default: bool

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class Capabilities:
    core_version: str
    tasks: tuple[CalculationTaskCapability, ...]
    target_codes: tuple[str, ...]
    models: tuple[ModelCapability, ...]
    pseudopotential_sets: tuple[PseudopotentialSetCapability, ...]
    default_intent: CalculationIntent
    default_hints: CalculationHints

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)
