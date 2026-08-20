"""Unified backend runtime for Core entrypoints (CLI, HTTP, MCP).

Composes a :class:`~goldilocks_core.runtime.core.CoreRuntime` (model lifecycle)
with a :class:`~goldilocks_core.runtime.dispatch.TaskDispatcher` (task dispatch
and the task registry) and exposes the full surface the entrypoints need: the
recommend/generate presets, the compute query, and the task/code/model
discovery. One process-owned service is reused across requests; a re-entrant
lock serializes dispatch so shared model lazy initialization and inference
never overlap across concurrent requests. The per-call convenience entrypoints
(:func:`~goldilocks_core.runtime.jobs.run_core_job` and
:func:`~goldilocks_core.runtime.jobs.query_records`) also route through a
short-lived service, so every entrypoint shares one backend surface.

The deep modules stay deep: the service owns no scientific logic and holds no
task graph -- it delegates dispatch to the dispatcher and model state to the
runtime, and aggregates the three discovery owners (tasks on the dispatcher,
codes on the generation registry, models on the runtime) into one surface
without collapsing them.
"""

from __future__ import annotations

import threading

from goldilocks_core.contracts import (
    CodeName,
    PresetRequest,
    QueryRequest,
    Records,
    Result,
)
from goldilocks_core.generation.registry import available_codes
from goldilocks_core.runtime.dispatch import Dispatcher
from goldilocks_core.runtime.graph import GraphInfo
from goldilocks_core.runtime.models import Runtime

__all__ = ["Service"]


class Service:
    """Unified backend runtime for Core entrypoints (CLI, HTTP, MCP).

    Owns a :class:`CoreRuntime` for model lifecycle (closing it when owned) and
    a :class:`TaskDispatcher` for task dispatch and the task registry, and
    exposes the preset/query dispatch plus the task/code/model discovery. One
    process-owned service is reused across requests; dispatch is serialized so
    shared model lazy initialization and inference never overlap across
    concurrent requests.
    """

    __slots__ = ("_runtime", "_dispatcher", "_lock", "_owns_runtime", "_closed")

    def __init__(self, runtime: Runtime | None = None) -> None:
        self._owns_runtime = runtime is None
        self._runtime = runtime if runtime is not None else Runtime()
        self._dispatcher = Dispatcher(self._runtime)
        self._lock = threading.RLock()
        self._closed = False

    @property
    def runtime(self) -> Runtime:
        """The model-lifecycle backend this service dispatches through."""
        return self._runtime

    @property
    def is_closed(self) -> bool:
        """Return whether this service has been closed."""
        return self._closed

    def recommend(self, request: PresetRequest) -> Result:
        """Execute the task's recommend preset and assemble a full result."""
        with self._lock:
            self._ensure_open()
            return self._dispatcher.recommend(request)

    def generate(
        self,
        request: PresetRequest,
        *,
        output_dir: str | None = None,
    ) -> Result:
        """Execute the task's generate preset and optionally publish a bundle."""
        with self._lock:
            self._ensure_open()
            return self._dispatcher.generate(request, output_dir=output_dir)

    def compute(self, request: QueryRequest) -> Records:
        """Execute the minimal subgraph for ``request.outputs`` on the task."""
        with self._lock:
            self._ensure_open()
            return self._dispatcher.compute(request)

    def run_preset(self, request: PresetRequest) -> Result:
        """Dispatch the preset selected by ``request.mode``."""
        with self._lock:
            self._ensure_open()
            return self._dispatcher.run_preset(request)

    def describe_tasks(self) -> tuple[GraphInfo, ...]:
        """Return transport-safe descriptions of every registered task."""
        with self._lock:
            self._ensure_open()
            return self._dispatcher.describe_tasks()

    def describe_codes(self) -> tuple[CodeName, ...]:
        """Return target DFT codes with registered input writers."""
        self._ensure_open()
        return available_codes()

    def describe_models(self) -> list[dict[str, str | None]]:
        """Return transport-safe descriptions of all registered ML models."""
        self._ensure_open()
        return self._runtime.describe_models()

    def close(self) -> None:
        """Close the owned runtime; repeated calls are harmless."""
        if self._closed:
            return
        if self._owns_runtime:
            self._runtime.close()
        self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Service is closed.")

    def __enter__(self) -> Service:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
