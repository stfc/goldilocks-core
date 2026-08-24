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
    licence: str | None = None
    licence_text: str | None = None
    citation: str | None = None

    def to_dict(self) -> JsonDict:
        return {
            "name": self.name,
            "version": self.version,
            "model_type": self.model_type,
            "target": self.target,
            "feature_set": self.feature_set,
            "source": self.source,
            "revision": self.revision,
            "licence": self.licence,
            "citation": self.citation,
        }
