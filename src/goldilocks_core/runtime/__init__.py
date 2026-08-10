"""Runtime package: model lifecycle, the stage graph, and job entrypoints."""

from goldilocks_core.contracts import PresetRequest, QueryRequest
from goldilocks_core.runtime.core import CoreRuntime
from goldilocks_core.runtime.dispatch import TaskDispatcher
from goldilocks_core.runtime.graph import Preset, StageSpec, TaskSpec, execute
from goldilocks_core.runtime.jobs import query_records, run_core_job
from goldilocks_core.runtime.scf import SCF_TASK, ScfContext, assemble_core_result
from goldilocks_core.runtime.task import TaskHandler

__all__ = [
    "CoreRuntime",
    "Preset",
    "PresetRequest",
    "QueryRequest",
    "SCF_TASK",
    "ScfContext",
    "StageSpec",
    "TaskDispatcher",
    "TaskHandler",
    "TaskSpec",
    "assemble_core_result",
    "execute",
    "query_records",
    "run_core_job",
]