from __future__ import annotations

from dataclasses import replace

from goldilocks_core.bundle import write_bundle_directory
from goldilocks_core.contracts import (
    Capabilities,
    ComputationResult,
    ComputeRequest,
    DirectoryOutput,
    GeneratedFiles,
    KPointSelection,
    ParameterAdvice,
    SelectionRecord,
    StructureAnalysisRecord,
    StructureInspection,
    StructureSource,
)
from goldilocks_core.io.structures import normalize_structure
from goldilocks_core.runtime.capabilities import build_capabilities
from goldilocks_core.runtime.dispatch import Dispatcher
from goldilocks_core.runtime.models import Runtime
from goldilocks_core.runtime.task import GraphHandler

__all__ = ["Service"]


class Service:
    __slots__ = ("_runtime", "_dispatcher", "_owns_runtime", "_closed")

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
        output: DirectoryOutput | None = None,
    ) -> ComputationResult:
        if output is not None and not isinstance(output, DirectoryOutput):
            raise ValueError("output must be a DirectoryOutput or None")
        self._ensure_open()
        result = self._dispatcher.compute(request)
        if output is None:
            return result
        required = {
            StructureAnalysisRecord,
            ParameterAdvice,
            KPointSelection,
            SelectionRecord,
            GeneratedFiles,
        }
        if not required.issubset(result.records):
            raise ValueError(
                "Directory output requires the complete generate record set"
            )
        return replace(result, bundle=write_bundle_directory(result, output.path))

    def capabilities(self) -> Capabilities:
        self._ensure_open()
        return build_capabilities(self._dispatcher, self._runtime)

    def inspect_structure(self, source: StructureSource) -> StructureInspection:
        self._ensure_open()
        return normalize_structure(source).inspection

    def close(self) -> None:
        if not self._closed and self._owns_runtime:
            self._runtime.close()
        self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Service is closed.")

    def __enter__(self) -> Service:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
