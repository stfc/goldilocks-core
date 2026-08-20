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

    def recommend(self, request: PresetRequest) -> Result:
        with self._lock:
            self._ensure_open()
            return self._dispatcher.recommend(request)

    def generate(
        self,
        request: PresetRequest,
        *,
        output_dir: str | None = None,
    ) -> Result:
        with self._lock:
            self._ensure_open()
            return self._dispatcher.generate(request, output_dir=output_dir)

    def compute(self, request: QueryRequest) -> Records:
        with self._lock:
            self._ensure_open()
            return self._dispatcher.compute(request)

    def run_preset(self, request: PresetRequest) -> Result:
        with self._lock:
            self._ensure_open()
            return self._dispatcher.run_preset(request)

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
