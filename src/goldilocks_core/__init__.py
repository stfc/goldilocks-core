"""Public API for goldilocks_core."""

from __future__ import annotations

from goldilocks_core.contracts import (
    BundleRecord,
    CalculationHints,
    CalculationIntent,
    CoreJobRequest,
    CoreResult,
    RuntimeResource,
)
from goldilocks_core.jobs import (
    CoreRuntime,
    Pipeline,
    generate,
    get_default_runtime,
    recommend,
    reset_default_runtime,
    run_core_job,
    write_bundle,
)

__all__ = [
    "BundleRecord",
    "CalculationHints",
    "CalculationIntent",
    "CoreJobRequest",
    "CoreResult",
    "CoreRuntime",
    "RuntimeResource",
    "Pipeline",
    "generate",
    "get_default_runtime",
    "recommend",
    "reset_default_runtime",
    "run_core_job",
    "write_bundle",
]
