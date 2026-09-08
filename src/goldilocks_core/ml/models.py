from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import joblib
import numpy as np

from goldilocks_core.serialization import Portable, portable_record, to_portable
from goldilocks_core.types import JsonDict, ModelSource, ModelType

type StructureFeatureVector = tuple[np.ndarray, list[str]]
"""Feature values and their names, in matching order."""


@dataclass(slots=True)
class ModelSpec:
    name: str
    version: str
    model_type: ModelType
    target: str
    feature_set: str
    source: ModelSource
    location: Annotated[str, Portable()]
    revision: str | None = None
    licence: str | None = None
    licence_text: Annotated[str | None, Portable()] = None
    citation: str | None = None


@to_portable.register(ModelSpec)
def _model_spec_portable(spec: ModelSpec) -> JsonDict:
    return portable_record(spec, ModelSpec)


def load_model(spec: ModelSpec) -> object:
    if spec.source != "local":
        raise ValueError(
            "model loaders do not fetch remote files; install the runtime asset first"
        )
    model_path = Path(spec.location)
    if not model_path.is_file():
        raise FileNotFoundError(f"Model file not found: {model_path}")
    return joblib.load(model_path)
