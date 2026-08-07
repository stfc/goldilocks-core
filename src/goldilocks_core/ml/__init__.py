"""Machine-learning inference boundaries for goldilocks_core.

Public surface:
    * QRF k-distance prediction: :func:`predict_kdistance`, :class:`KDistancePrediction`
    * k-index prediction: :func:`predict_kindex`
    * shared model loading: :func:`load_model`, :func:`resolve_artifact`
    * QRF configuration: :func:`load_default_qrf_config`, :class:`QrfKpointsConfig`,
      :class:`QrfFeatureSettings`, :class:`ArtifactSpec`
"""

from __future__ import annotations

from goldilocks_core.ml.kindex import predict_kindex
from goldilocks_core.ml.model_registry import (
    ArtifactSpec,
    QrfFeatureSettings,
    QrfKpointsConfig,
    load_default_qrf_config,
)
from goldilocks_core.ml.models import load_model, resolve_artifact
from goldilocks_core.ml.qrf import (
    KDistancePrediction,
    QrfResources,
    load_qrf_resources,
    predict_kdistance,
    predict_kdistance_with_resources,
)

__all__ = [
    "ArtifactSpec",
    "KDistancePrediction",
    "QrfFeatureSettings",
    "QrfKpointsConfig",
    "QrfResources",
    "load_default_qrf_config",
    "load_model",
    "load_qrf_resources",
    "predict_kdistance",
    "predict_kdistance_with_resources",
    "predict_kindex",
    "resolve_artifact",
]
