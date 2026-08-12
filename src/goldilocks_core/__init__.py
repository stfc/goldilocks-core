"""Public API for goldilocks_core."""

from __future__ import annotations

from goldilocks_core.contracts import (
    BundleRecord,
    CalculationHints,
    CalculationIntent,
    CoreResult,
    PresetRequest,
    QueryRequest,
)
from goldilocks_core.runtime import (
    CoreRuntime,
    CoreService,
    TaskDispatcher,
    query_records,
    run_core_job,
)

__all__ = [
    "BundleRecord",
    "CalculationHints",
    "CalculationIntent",
    "CoreResult",
    "CoreRuntime",
    "CoreService",
    "PresetRequest",
    "QueryRequest",
    "TaskDispatcher",
    "query_records",
    "run_core_job",
]
