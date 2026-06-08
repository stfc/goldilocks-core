"""Public API for goldilocks_core."""

from __future__ import annotations

from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    CoreRecommendation,
)
from goldilocks_core.pipeline import bundle_recommendation, recommend

__all__ = [
    "CalculationHints",
    "CalculationIntent",
    "CoreRecommendation",
    "bundle_recommendation",
    "recommend",
]
