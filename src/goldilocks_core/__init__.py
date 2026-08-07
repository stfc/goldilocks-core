"""Public API for goldilocks_core."""

from __future__ import annotations

from goldilocks_core.contracts import (
    BundleRecord,
    CalculationHints,
    CalculationIntent,
    CoreJobRequest,
    CoreResult,
    ModelRuntime,
)
from goldilocks_core.jobs import (
    generate,
    recommend,
    run_core_job,
)
from goldilocks_core.runtime import CoreRuntime

__all__ = [
    "BundleRecord",
    "CalculationHints",
    "CalculationIntent",
    "CoreJobRequest",
    "CoreResult",
    "CoreRuntime",
    "ModelRuntime",
    "generate",
    "recommend",
    "run_core_job",
]
