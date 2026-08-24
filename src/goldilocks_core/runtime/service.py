from __future__ import annotations

import threading

from goldilocks_core.contracts import (
    CodeName,
    ComputationResult,
    ComputeRequest,
    StructureInspection,
    StructureSource,
)
from goldilocks_core.generation.registry import available_codes
from goldilocks_core.io.structures import normalize_structure
from goldilocks_core.runtime.dispatch import Dispatcher
from goldilocks_core.runtime.graph import GraphInfo
from goldilocks_core.runtime.models import Runtime

__all__ = ["Service"]


class Service:
    __slots__ = ("_runtime", "_dispatcher", "_lock", "_owns_runtime", "_closed")

    def __init__(self, runtime: Runtime | None = None) -> None:
        self._owns_runtime = runtime is None
        self._runtime = runtime if runtime is not None else Runtime()
        self._dispatcher = Dispatcher(self._runtime)
        self._lock = threading.RLock()
        self._closed = False

    @property
    def runtime(self) -> Runtime:
        return self._runtime

    @property
    def is_closed(self) -> bool:
        return self._closed

    def compute(
        self,
        request: ComputeRequest,
        *,
        output: None = None,
    ) -> ComputationResult:
        if output is not None:
            raise ValueError("P1 supports memory output only")
        with self._lock:
            self._ensure_open()
            return self._dispatcher.compute(request)

    def inspect_structure(self, source: StructureSource) -> StructureInspection:
        with self._lock:
            self._ensure_open()
            return normalize_structure(source).inspection

    def describe_tasks(self) -> tuple[GraphInfo, ...]:
        with self._lock:
            self._ensure_open()
            return self._dispatcher.describe_tasks()

    def describe_codes(self) -> tuple[CodeName, ...]:
        self._ensure_open()
        return available_codes()

    def describe_models(self) -> list[dict[str, str | None]]:
        self._ensure_open()
        return self._runtime.describe_models()

    def close(self) -> None:
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
