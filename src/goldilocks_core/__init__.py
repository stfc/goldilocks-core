"""Public API for goldilocks_core."""

from __future__ import annotations

from goldilocks_core.contracts import (
    BundleRecord,
    CalculationHints,
    CalculationIntent,
    CoreJobRequest,
    CoreResult,
)
from goldilocks_core.runtime import (
    CoreRuntime,
    generate,
    query_records,
    recommend,
    run_core_job,
)

__all__ = [
    "BundleRecord",
    "CalculationHints",
    "CalculationIntent",
    "CoreJobRequest",
    "CoreResult",
    "CoreRuntime",
    "generate",
    "query_records",
    "recommend",
    "run_core_job",
]
