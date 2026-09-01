from __future__ import annotations

from pathlib import Path

import joblib

from goldilocks_core.contracts import ModelSpec


def load_model(spec: ModelSpec) -> object:
    if spec.source != "local":
        raise ValueError(
            "model loaders do not fetch remote files; install the runtime asset first"
        )
    model_path = Path(spec.location)
    if not model_path.is_file():
        raise FileNotFoundError(f"Model file not found: {model_path}")
    return joblib.load(model_path)
