"""Public API for goldilocks_core."""

from __future__ import annotations

from goldilocks_core.contracts import (
    BundleRecord,
    CalculationHints,
    CalculationIntent,
    CoreJobRequest,
    CoreResult,
)
from goldilocks_core.jobs import (
    Pipeline,
    generate,
    recommend,
    run_core_job,
    write_bundle,
)

__all__ = [
    "BundleRecord",
    "CalculationHints",
    "CalculationIntent",
    "CoreJobRequest",
    "CoreResult",
    "Pipeline",
    "generate",
    "recommend",
    "run_core_job",
    "write_bundle",
]
