from __future__ import annotations

import threading
from dataclasses import replace

from goldilocks_core.contracts import (
    ArchiveOutput,
    Capabilities,
    ComputationResult,
    ComputeRequest,
    DftInputData,
    DirectoryOutput,
    OutputTarget,
    StructureInspection,
    StructureSource,
)
from goldilocks_core.io.structures import normalize_structure
from goldilocks_core.publication import Publisher
from goldilocks_core.runtime.capabilities import build_capabilities
from goldilocks_core.runtime.dispatch import Dispatcher
from goldilocks_core.runtime.models import Runtime
from goldilocks_core.runtime.task import GraphHandler

__all__ = ["Service"]


class Service:
    __slots__ = (
        "_runtime",
        "_dispatcher",
        "_computation_lock",
        "_owns_runtime",
        "_closed",
    )

    def __init__(
        self,
        runtime: Runtime | None = None,
        *,
        task_handlers: tuple[GraphHandler, ...] = (),
    ) -> None:
        self._owns_runtime = runtime is None
        self._runtime = runtime if runtime is not None else Runtime()
        self._dispatcher = Dispatcher(self._runtime)
        for handler in task_handlers:
            self._dispatcher.register(handler)
        self._computation_lock = threading.RLock()
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
        output: OutputTarget | None = None,
    ) -> ComputationResult:
        if output is not None and not isinstance(
            output, DirectoryOutput | ArchiveOutput
        ):
            raise ValueError("output must be a DirectoryOutput, ArchiveOutput, or None")
        self._ensure_open()
        with self._computation_lock:
            result = self._dispatcher.compute(request)
        if output is None:
            return result
        input_data = result.records.get(DftInputData)
        if input_data is None:
            if isinstance(output, DirectoryOutput) and output.path is None:
                return result
            raise ValueError(
                "The Computation Result does not contain DFT Input Data to publish"
            )
        publication = Publisher(self._runtime.asset_store).publish(input_data, output)
        return replace(result, publication=publication)

    def capabilities(self) -> Capabilities:
        self._ensure_open()
        return build_capabilities(self._dispatcher, self._runtime)

    def inspect_structure(self, source: StructureSource) -> StructureInspection:
        self._ensure_open()
        return normalize_structure(source).inspection

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
