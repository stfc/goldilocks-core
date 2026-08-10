"""Convenience entrypoints for Core jobs."""

from __future__ import annotations

from goldilocks_core.contracts import (
    CoreRecords,
    CoreResult,
    PresetRequest,
    QueryRequest,
)
from goldilocks_core.runtime.core import CoreRuntime
from goldilocks_core.runtime.dispatch import TaskDispatcher


def run_core_job(
    request: PresetRequest,
    *,
    runtime: CoreRuntime | None = None,
) -> CoreResult:
    """Run the preset named by ``request.mode`` and return a full result.

    Use :func:`query_records` for an explicit record subset.
    """
    if runtime is None:
        with CoreRuntime() as owned:
            return TaskDispatcher(owned).run_preset(request)
    return TaskDispatcher(runtime).run_preset(request)


def query_records(
    request: QueryRequest,
    *,
    runtime: CoreRuntime | None = None,
) -> CoreRecords:
    """Compute the explicit record types in ``request.outputs``.

    Use :func:`run_core_job` to run a named preset instead.
    """
    if runtime is None:
        with CoreRuntime() as owned:
            return TaskDispatcher(owned).compute(request)
    return TaskDispatcher(runtime).compute(request)