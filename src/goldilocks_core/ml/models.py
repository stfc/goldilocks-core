"""Model loading utilities for machine-learning inference."""

from __future__ import annotations

from pathlib import Path

import joblib

from goldilocks_core.contracts import ModelSpec


def load_model(spec: ModelSpec) -> object:
    """Load a trained model from a model specification.

    Parameters
    ----------
    spec
        Metadata describing the model source, type, target, and feature set.

    Returns
    -------
    object
        Loaded model object. The concrete type depends on the model backend.

    Raises
    ------
    FileNotFoundError
        If a local model path does not exist.
    NotImplementedError
        If the requested model source or model type is not yet supported.
    """
    if spec.source != "local":
        raise NotImplementedError(
            f"Model source '{spec.source}' is not implemented yet."
        )

    if spec.model_type != "random_forest":
        raise NotImplementedError(
            f"Model type '{spec.model_type}' is not implemented yet."
        )

    model_path = Path(spec.location)
    if not model_path.exists():
        raise FileNotFoundError(f"Model file not found: {model_path}")

    return joblib.load(model_path)
