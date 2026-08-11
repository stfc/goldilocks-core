"""QRF k-distance inference boundary.

Re-exports the QRF k-distance inference entry point, its result type, and the
resource loading helpers used by stateful backends.
"""

from __future__ import annotations

from .inference import (
    KDistancePrediction,
    QrfResources,
    load_qrf_resources,
    predict_kdistance,
    predict_kdistance_with_resources,
)

__all__ = [
    "KDistancePrediction",
    "QrfResources",
    "load_qrf_resources",
    "predict_kdistance",
    "predict_kdistance_with_resources",
]
