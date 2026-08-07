"""QRF k-distance inference boundary.

Re-exports the QRF k-distance inference entry point and its result type.
"""

from __future__ import annotations

from .inference import KDistancePrediction, predict_kdistance

__all__ = ["KDistancePrediction", "predict_kdistance"]
