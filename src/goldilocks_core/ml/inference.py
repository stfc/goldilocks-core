"""Inference utilities for machine-learning models."""

from __future__ import annotations

import numpy as np

from goldilocks_core.contracts import StructureFeatureVector


def predict(model: object, features: StructureFeatureVector) -> float:
    """Run model inference on a structure feature vector.

    Parameters
    ----------
    model
        Loaded model object.
    features
        Structure-derived feature vector used for prediction.

    Returns
    -------
    float
        Predicted scalar output from the model.

    Raises
    ------
    AttributeError
        If the model does not provide a ``predict`` method.
    ValueError
        If the model prediction does not return at least one value.
    """
    if not hasattr(model, "predict"):
        raise AttributeError("Loaded model does not provide a 'predict' method.")

    predictions = model.predict(features.values.reshape(1, -1))
    predictions = np.asarray(predictions, dtype=float)

    if predictions.size == 0:
        raise ValueError("Model prediction returned no values.")

    return float(predictions[0])
