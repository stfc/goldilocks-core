from __future__ import annotations

import numpy as np
from pymatgen.core import Structure

from goldilocks_core.contracts import ModelSpec, StructureFeatureVector


def predict(model: object, features: StructureFeatureVector) -> float:
    if not hasattr(model, "predict"):
        raise AttributeError("Loaded model does not provide a 'predict' method.")

    feature_values = np.asarray(features.values, dtype=float)
    if not np.isfinite(feature_values).all():
        raise ValueError("Model features must contain only finite values.")

    predictions = model.predict(feature_values.reshape(1, -1))
    predictions = np.asarray(predictions, dtype=float)

    if predictions.size == 0:
        raise ValueError("Model prediction returned no values.")

    return float(predictions[0])


def predict_kindex(structure: Structure, spec: ModelSpec) -> float:
    from goldilocks_core.ml.kindex.features import extract_cslr_features
    from goldilocks_core.ml.models import load_model

    features = extract_cslr_features(structure)
    model = load_model(spec)
    return predict(model, features)
