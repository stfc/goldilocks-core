"""Runtime package: model lifecycle, the stage graph, and job entrypoints.

The generic runtime surface — executor, dispatcher, task handler, model
runtime, and job entrypoints — is re-exported here. The SCF task's own types
(``SCF_TASK``, ``ScfContext``, ``assemble_core_result``) live in
:mod:`goldilocks_core.runtime.scf` and are imported from there, not from this
facade, so the facade stays task-agnostic and importing it does not pull in
the stage implementations.
"""

from goldilocks_core.contracts import PresetRequest, QueryRequest
from goldilocks_core.runtime.core import CoreRuntime
from goldilocks_core.runtime.dispatch import TaskDispatcher
from goldilocks_core.runtime.graph import (
    Preset,
    StageSpec,
    TaskGraphDescription,
    TaskSpec,
    describe_task,
    execute,
)
from goldilocks_core.runtime.jobs import query_records, run_core_job
from goldilocks_core.runtime.service import CoreService
from goldilocks_core.runtime.task import TaskHandler

__all__ = [
    "CoreRuntime",
    "CoreService",
    "Preset",
    "PresetRequest",
    "QueryRequest",
    "StageSpec",
    "TaskDispatcher",
    "TaskGraphDescription",
    "TaskHandler",
    "TaskSpec",
    "describe_task",
    "execute",
    "query_records",
    "run_core_job",
]
