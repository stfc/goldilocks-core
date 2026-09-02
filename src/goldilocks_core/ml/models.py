from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np

from goldilocks_core.serialization import to_portable
from goldilocks_core.types import JsonDict, ModelSource, ModelType


@dataclass(slots=True)
class StructureFeatureVector:
    values: np.ndarray
    feature_names: list[str]


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


@to_portable.register(ModelSpec)
def _model_spec_portable(spec: ModelSpec) -> JsonDict:
    return {
        "name": spec.name,
        "version": spec.version,
        "model_type": spec.model_type,
        "target": spec.target,
        "feature_set": spec.feature_set,
        "source": spec.source,
        "revision": spec.revision,
        "licence": spec.licence,
        "citation": spec.citation,
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
