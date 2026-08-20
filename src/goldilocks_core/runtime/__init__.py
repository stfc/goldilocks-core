"""Runtime package: model lifecycle, the stage graph, and job entrypoints.

The generic runtime surface — executor, dispatcher, task handler, model
runtime, and job entrypoints — is re-exported here. The SCF task's own types
(``SCF_TASK``, ``ScfContext``, ``assemble_core_result``) live in
:mod:`goldilocks_core.runtime.scf` and are imported from there, not from this
facade, so the facade stays task-agnostic and importing it does not pull in
the stage implementations.
"""

from goldilocks_core.contracts import PresetRequest, QueryRequest
from goldilocks_core.runtime.dispatch import Dispatcher, UnknownTask
from goldilocks_core.runtime.graph import (
    GraphInfo,
    Preset,
    Stage,
    TaskGraph,
    describe_task,
    execute,
)
from goldilocks_core.runtime.jobs import query_records, run_core_job
from goldilocks_core.runtime.models import Runtime
from goldilocks_core.runtime.service import Service
from goldilocks_core.runtime.task import GraphHandler

__all__ = [
    "Runtime",
    "Service",
    "Preset",
    "PresetRequest",
    "QueryRequest",
    "Stage",
    "Dispatcher",
    "UnknownTask",
    "GraphInfo",
    "GraphHandler",
    "TaskGraph",
    "describe_task",
    "execute",
    "query_records",
    "run_core_job",
]
