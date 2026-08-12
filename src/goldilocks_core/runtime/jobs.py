"""Convenience entrypoints for Core jobs.

Both route through a short-lived :class:`~goldilocks_core.runtime.service.CoreService`
so the per-call library path and the long-lived server path share one backend
surface. A caller-owned runtime is reused and left open; an owned runtime is
created and closed per call.
"""

from __future__ import annotations

from goldilocks_core.contracts import (
    CoreRecords,
    CoreResult,
    PresetRequest,
    QueryRequest,
)
from goldilocks_core.runtime.core import CoreRuntime
from goldilocks_core.runtime.service import CoreService


def run_core_job(
    request: PresetRequest,
    *,
    runtime: CoreRuntime | None = None,
) -> CoreResult:
    """Run the preset named by ``request.mode`` and return a full result.

    Use :func:`query_records` for an explicit record subset.
    """
    if runtime is None:
        with CoreService() as service:
            return service.run_preset(request)
    return CoreService(runtime).run_preset(request)


def query_records(
    request: QueryRequest,
    *,
    runtime: CoreRuntime | None = None,
) -> CoreRecords:
    """Compute the explicit record types in ``request.outputs``.

    Use :func:`run_core_job` to run a named preset instead.
    """
    if runtime is None:
        with CoreService() as service:
            return service.compute(request)
    return CoreService(runtime).compute(request)
