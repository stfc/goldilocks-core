from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from goldilocks_core.contracts.serial import to_jsonable
from goldilocks_core.contracts.types import JsonDict, ModelSource, ModelType


@dataclass(slots=True)
class StructureFeatureVector:
    values: np.ndarray
    feature_names: list[str]

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)


@dataclass(slots=True)
class ModelSpec:
    name: str
    version: str
    model_type: ModelType
    target: str
    feature_set: str
    source: ModelSource
    location: str
    revision: str | None = None


@dataclass(frozen=True, slots=True)
class ModelPrediction:
    """A model's output, addressed to one advised parameter.

    ``parameter`` names an advised parameter (a ``ParameterAdvice`` field, or
    ``"k_points"``), so a prediction is routed to its resolver by lookup
    rather than by branching per model. ``details`` and ``warnings`` are
    copied verbatim into ``Provenance`` by the resolver; Core does not
    interpret them.
    """

    parameter: str
    quantity: str
    value: float | int | bool | str | tuple[Any, ...]
    target_contract: str
    model_id: str
    confidence: float | None = None
    details: JsonDict | None = None
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)
