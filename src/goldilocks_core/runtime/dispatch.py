from __future__ import annotations

from dataclasses import replace
from threading import Lock
from typing import Any

from goldilocks_core.io.structures import normalize_structure
from goldilocks_core.request import ComputeRequest, PresetSelection
from goldilocks_core.result import ComputationResult
from goldilocks_core.runtime.graph import (
    describe_task,
    execute_graph,
)
from goldilocks_core.runtime.models import Runtime
from goldilocks_core.runtime.registry import register_record_types
from goldilocks_core.runtime.task import GraphHandler


class UnknownTask(ValueError):
    pass


class UnavailableRecord(ValueError):
    pass


class Dispatcher:
    def __init__(self, runtime: Runtime) -> None:
        self._runtime = runtime
        self._tasks: dict[str, GraphHandler] = {}
        self._default_pending = True
        self._default_lock = Lock()

    def register(self, handler: GraphHandler) -> None:
        task = handler.spec
        for field, value in (("task", task.task), ("revision", task.revision)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"TaskGraph {field} must be a non-empty string; got {value!r}"
                )

        stage_ids = tuple(stage.id for stage in task.stages)
        if any(
            not isinstance(stage_id, str) or not stage_id.strip()
            for stage_id in stage_ids
        ):
            raise ValueError("TaskGraph stage ids must be non-empty strings")
        if len(stage_ids) != len(set(stage_ids)):
            raise ValueError("TaskGraph stage ids must be unique")

        preset_names = tuple(preset.name for preset in task.presets)
        if any(
            not isinstance(preset_name, str) or not preset_name.strip()
            for preset_name in preset_names
        ):
            raise ValueError("TaskGraph preset names must be non-empty strings")
        if len(preset_names) != len(set(preset_names)):
            raise ValueError("TaskGraph preset names must be unique")

        record_types = dict.fromkeys(
            record_type
            for stage in task.stages
            for record_type in (*stage.inputs, stage.output)
        )
        record_types.update(
            {
                record_type: None
                for preset in task.presets
                for record_type in preset.outputs
            }
        )
        record_types.update(dict.fromkeys(task.selectable_outputs))
        for record_type in record_types:
            try:
                task.record_id(record_type)
            except ValueError as error:
                raise ValueError(
                    f"Task {task.task!r} requires a stable record id for "
                    f"{record_type.__name__}"
                ) from error
        register_record_types(task.record_ids)
        self._tasks[task.task] = handler

    def _ensure_default(self) -> None:
        if not self._default_pending:
            return
        with self._default_lock:
            if not self._default_pending:
                return
            from goldilocks_core.runtime.scf import SCF_HANDLER

            if SCF_HANDLER.spec.task not in self._tasks:
                self.register(SCF_HANDLER)
            self._default_pending = False

    def compute(self, request: ComputeRequest) -> ComputationResult:
        self._ensure_open()
        self._ensure_default()
        handler = self._handler_for(request)
        task = handler.spec
        if isinstance(request.selection, PresetSelection):
            outputs = task.preset(request.selection.preset).outputs
        else:
            outputs = request.selection.records
            unavailable = tuple(
                record_type
                for record_type in outputs
                if record_type not in task.selectable_outputs
            )
            if unavailable:
                names = ", ".join(item.__name__ for item in unavailable)
                raise UnavailableRecord(
                    f"Record(s) {names} are not selectable for task {task.task!r}."
                )
        normalized_structure = normalize_structure(request.draft.structure)
        normalized_draft = replace(
            request.draft,
            structure=normalized_structure.inspection,
        )
        execution = execute_graph(
            task,
            outputs,
            handler.build_context(request, normalized_structure, self._runtime),
        )
        return ComputationResult(
            draft=normalized_draft,
            task=task.task,
            task_revision=task.revision,
            selection=request.selection,
            records=execution.records,
            warnings=handler.collect_warnings(execution.produced),
        )

    def describe_tasks(self) -> tuple[dict[str, Any], ...]:
        self._ensure_default()
        return tuple(describe_task(handler.spec) for handler in self._tasks.values())

    def _handler_for(self, request: ComputeRequest) -> GraphHandler:
        handler = self._tasks.get(request.draft.intent.task)
        if handler is None:
            available = ", ".join(sorted(self._tasks)) or "none"
            raise UnknownTask(
                f"No Core task registered for task={request.draft.intent.task!r}. "
                f"Available: {available}"
            )
        return handler

    def _ensure_open(self) -> None:
        if self._runtime.is_closed:
            raise RuntimeError("Runtime is closed.")
