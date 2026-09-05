from __future__ import annotations

from dataclasses import dataclass

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
    # Which rung a model's k_index calls the Gamma-only mesh. This ladder
    # numbers it 1, and records published before that convention number it 0;
    # the base belongs to the model, not to the ladder, so a record trained
    # either way maps onto the same table.
    k_index_base: int = 1
