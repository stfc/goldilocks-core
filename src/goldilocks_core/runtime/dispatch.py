from __future__ import annotations

from dataclasses import replace

from goldilocks_core.bundle import write_bundle_directory
from goldilocks_core.contracts import (
    PresetRequest,
    QueryRequest,
    Records,
    Result,
)
from goldilocks_core.runtime.graph import GraphInfo, describe_task, execute
from goldilocks_core.runtime.models import Runtime
from goldilocks_core.runtime.task import GraphHandler


class UnknownTask(ValueError):
    pass


class Dispatcher:
    def __init__(self, runtime: Runtime) -> None:
        self._runtime = runtime
        self._tasks: dict[str, GraphHandler] = {}
        self._default_pending = True

    def register(self, handler: GraphHandler) -> None:
        self._tasks[handler.spec.task] = handler

    def _ensure_default(self) -> None:
        if not self._default_pending:
            return
        self._default_pending = False
        from goldilocks_core.runtime.scf import SCF_HANDLER

        if SCF_HANDLER.spec.task not in self._tasks:
            self.register(SCF_HANDLER)

    def recommend(self, request: PresetRequest) -> Result:
        self._ensure_open()
        self._ensure_default()
        handler = self._handler_for(request)
        task = handler.spec
        records = execute(
            task,
            task.preset("recommend").outputs,
            handler.build_context(request, self._runtime),
        )
        return handler.assemble_result(request, records)

    def generate(
        self,
        request: PresetRequest,
        *,
        output_dir: str | None = None,
    ) -> Result:
        self._ensure_open()
        self._ensure_default()
        handler = self._handler_for(request)
        task = handler.spec
        records = execute(
            task,
            task.preset("generate").outputs,
            handler.build_context(request, self._runtime),
        )
        result = handler.assemble_result(request, records)
        if output_dir is None:
            return result
        return replace(result, bundle=write_bundle_directory(result, output_dir))

    def compute(self, request: QueryRequest) -> Records:
        self._ensure_open()
        self._ensure_default()
        handler = self._handler_for(request)
        return execute(
            handler.spec,
            request.outputs,
            handler.build_context(request, self._runtime),
        )

    def describe_tasks(self) -> tuple[GraphInfo, ...]:
        self._ensure_default()
        return tuple(describe_task(handler.spec) for handler in self._tasks.values())

    def run_preset(self, request: PresetRequest) -> Result:
        if request.mode == "recommend":
            return self.recommend(request)
        return self.generate(request, output_dir=request.output_dir)

    def _handler_for(self, request: PresetRequest | QueryRequest) -> GraphHandler:
        handler = self._tasks.get(request.intent.task)
        if handler is None:
            available = ", ".join(sorted(self._tasks)) or "none"
            raise UnknownTask(
                f"No Core task registered for task={request.intent.task!r}. "
                f"Available: {available}"
            )
        return handler

    def _ensure_open(self) -> None:
        if self._runtime.is_closed:
            raise RuntimeError("Runtime is closed.")
