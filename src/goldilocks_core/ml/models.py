from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np

from goldilocks_core.serialization import to_jsonable
from goldilocks_core.types import JsonDict, ModelSource, ModelType


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


def load_model(spec: ModelSpec) -> object:
    if spec.source != "local":
        raise ValueError(
            "model loaders do not fetch remote files; install the runtime asset first"
        )
    model_path = Path(spec.location)
    if not model_path.is_file():
        raise FileNotFoundError(f"Model file not found: {model_path}")
    return joblib.load(model_path)
