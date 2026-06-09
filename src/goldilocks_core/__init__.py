"""Public API for goldilocks_core."""

from __future__ import annotations

from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    CoreJobRequest,
    CoreJobResult,
    CoreRecommendation,
)
from goldilocks_core.jobs import run_core_job
from goldilocks_core.pipeline import (
    bundle_recommendation,
    generate,
    recommend,
    write_bundle,
)

__all__ = [
    "CalculationHints",
    "CalculationIntent",
    "CoreJobRequest",
    "CoreJobResult",
    "CoreRecommendation",
    "bundle_recommendation",
    "generate",
    "recommend",
    "run_core_job",
    "write_bundle",
]
