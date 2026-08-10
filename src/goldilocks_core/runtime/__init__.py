"""Runtime package: model lifecycle, the stage graph, and job entrypoints."""

from goldilocks_core.runtime.core import CoreRuntime
from goldilocks_core.runtime.graph import Preset, StageSpec, TaskSpec, execute
from goldilocks_core.runtime.jobs import (
    generate,
    query_records,
    recommend,
    run_core_job,
)
from goldilocks_core.runtime.scf import SCF_TASK, ScfContext, assemble_core_result

__all__ = [
    "CoreRuntime",
    "Preset",
    "SCF_TASK",
    "ScfContext",
    "StageSpec",
    "TaskSpec",
    "assemble_core_result",
    "execute",
    "generate",
    "query_records",
    "recommend",
    "run_core_job",
]
