"""K-index inference boundary.

Advisors call :func:`predict_kindex` and nothing else here. CSLR feature
extraction, model loading, and inference are encapsulated behind that one
entry point; the kmesh-entry selection that turns the scalar k-index into a
grid stays in the advisor.
"""

from __future__ import annotations

from pymatgen.core import Structure

from goldilocks_core.contracts import ModelSpec

__all__ = ["predict_kindex"]


def predict_kindex(structure: Structure, spec: ModelSpec) -> float:
    """Predict a scalar k-index for ``structure`` using the model at ``spec``."""
    from goldilocks_core.ml.kindex.features import extract_cslr_features
    from goldilocks_core.ml.kindex.inference import predict
    from goldilocks_core.ml.models import load_model

    features = extract_cslr_features(structure)
    model = load_model(spec)
    return predict(model, features)
