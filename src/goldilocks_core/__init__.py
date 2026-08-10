"""Public API for goldilocks_core."""

from __future__ import annotations

from goldilocks_core.contracts import (
    BundleRecord,
    CalculationHints,
    CalculationIntent,
    CoreJobRequest,
    CoreResult,
)
from goldilocks_core.jobs import generate, recommend, run_core_job

__all__ = [
    "BundleRecord",
    "CalculationHints",
    "CalculationIntent",
    "CoreJobRequest",
    "CoreResult",
    "generate",
    "recommend",
    "run_core_job",
]
