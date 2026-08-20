"""Public API for goldilocks_core."""

from __future__ import annotations

from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    PresetRequest,
    QueryRequest,
    Records,
    Result,
)
from goldilocks_core.runtime import (
    Dispatcher,
    Runtime,
    Service,
    query_records,
    run_core_job,
)

__all__ = [
    "CalculationHints",
    "CalculationIntent",
    "Dispatcher",
    "PresetRequest",
    "QueryRequest",
    "Records",
    "Result",
    "Runtime",
    "Service",
    "query_records",
    "run_core_job",
]
