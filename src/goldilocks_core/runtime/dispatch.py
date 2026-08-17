"""Task dispatch: run registered task graphs by intent.task.

The dispatcher holds no model state; it borrows a
:class:`~goldilocks_core.runtime.core.CoreRuntime` for services (kmesh,
metallicity) and an open-state guard, and owns the task registry. Tasks
register a :class:`~goldilocks_core.runtime.task.TaskHandler` (graph +
context builder + result assembler). The SCF task is the shipped default,
registered lazily on first dispatch so importing this module does not pull
in the stage implementations (and their ``ml.*`` dependencies); the dispatch
path itself is task-agnostic, so a new task (nscf, phonons) registers without
the runtime or the executor changing.
"""

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
    """A request names no registered Core task."""
    pass


    """Dispatch Core task graphs through registered :class:`TaskHandler`s.

    Borrows a :class:`CoreRuntime` for owned services and an open-state guard;
    owns the task registry. Register a custom task and dispatch by
    ``intent.task`` without the runtime or the executor changing.
    """

class Dispatcher:
    def __init__(self, runtime: Runtime) -> None:
        self._runtime = runtime
        self._tasks: dict[str, GraphHandler] = {}
        self._default_pending = True

    def register(self, handler: GraphHandler) -> None:
        """Register a task for dispatch by ``intent.task``."""
        self._tasks[handler.spec.task] = handler

    def _ensure_default(self) -> None:
        """Register the shipped SCF default once, on first dispatch.

        Deferred so ``import goldilocks_core.runtime`` does not eagerly load
        the stage implementations or their ``ml.*`` dependencies. An explicitly
        registered handler for the SCF task name is left in place — explicit
        registration wins over the default, matching eager registration order.
        """
        if not self._default_pending:
            return
        self._default_pending = False
        from goldilocks_core.runtime.scf import SCF_HANDLER

        if SCF_HANDLER.spec.task not in self._tasks:
            self.register(SCF_HANDLER)

    def recommend(self, request: PresetRequest) -> Result:
        """Execute the task's recommend preset and assemble a full result."""
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
        """Execute the task's generate preset and optionally publish a bundle."""
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
        """Execute the minimal subgraph for ``request.outputs`` on the task."""
        self._ensure_open()
        self._ensure_default()
        handler = self._handler_for(request)
        return execute(
            handler.spec,
            request.outputs,
            handler.build_context(request, self._runtime),
        )

    def describe_tasks(self) -> tuple[GraphInfo, ...]:
        """Return transport-safe descriptions of every registered task."""
        self._ensure_default()
        return tuple(describe_task(handler.spec) for handler in self._tasks.values())

    def run_preset(self, request: PresetRequest) -> Result:
        """Dispatch the preset selected by ``request.mode``."""
        if request.mode == "recommend":
            return self.recommend(request)
        return self.generate(request, output_dir=request.output_dir)

    def _handler_for(self, request: PresetRequest | QueryRequest) -> GraphHandler:
        """Return the registered handler for ``request.intent.task``."""
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
