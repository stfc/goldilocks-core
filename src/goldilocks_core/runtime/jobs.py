from __future__ import annotations

from goldilocks_core.contracts import (
    PresetRequest,
    QueryRequest,
    Records,
    Result,
)
from goldilocks_core.runtime.models import Runtime
from goldilocks_core.runtime.service import Service


def run_core_job(
    request: PresetRequest,
    *,
    runtime: Runtime | None = None,
) -> Result:
    if runtime is None:
        with Service() as service:
            return service.run_preset(request)
    return Service(runtime).run_preset(request)


def query_records(
    request: QueryRequest,
    *,
    runtime: Runtime | None = None,
) -> Records:
    if runtime is None:
        with Service() as service:
            return service.compute(request)
    return Service(runtime).compute(request)
