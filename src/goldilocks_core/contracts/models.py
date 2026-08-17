from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from goldilocks_core.contracts.serial import to_jsonable
from goldilocks_core.contracts.types import JsonDict, ModelSource, ModelType


@dataclass(slots=True)
class StructureFeatureVector:
    """Named numerical feature vector extracted from a structure.

    Used by ML advisors for k-index prediction.

    Attributes:
        values: feature values in the same order as ``feature_names``.
        feature_names: human-readable names for each feature dimension.
    """

    values: np.ndarray
    feature_names: list[str]

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(slots=True)
class ModelSpec:
    """Metadata describing a trained model used by the package.

    Attributes:
        name: human-readable model identifier.
        version: model version string.
        model_type: architecture type (e.g. ``random_forest``).
        target: prediction target (e.g. ``k_index``).
        feature_set: feature set name (e.g. ``cslr``).
        source: where the model is loaded from (``local`` or ``huggingface``).
        location: file path or source-specific artifact identifier.
        revision: optional immutable source revision.
    """

    name: str
    version: str
    model_type: ModelType
    target: str
    feature_set: str
    source: ModelSource
    location: str
    revision: str | None = None
