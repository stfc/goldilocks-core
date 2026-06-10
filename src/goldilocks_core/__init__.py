"""Public API for goldilocks_core."""

from __future__ import annotations

from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    CoreJobRequest,
    CoreJobResult,
    CoreRecommendation,
    Pipeline,
)
from goldilocks_core.jobs import default_pipeline, run_core_job
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
    "Pipeline",
    "bundle_recommendation",
    "default_pipeline",
    "generate",
    "recommend",
    "run_core_job",
    "write_bundle",
]
