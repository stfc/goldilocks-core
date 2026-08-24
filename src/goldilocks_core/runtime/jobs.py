from __future__ import annotations

from goldilocks_core.contracts import ComputationResult, ComputeRequest
from goldilocks_core.runtime.models import Runtime
from goldilocks_core.runtime.service import Service


def compute(
    request: ComputeRequest,
    *,
    runtime: Runtime | None = None,
    output: None = None,
) -> ComputationResult:
    if runtime is None:
        with Service() as service:
            return service.compute(request, output=output)
    return Service(runtime).compute(request, output=output)
