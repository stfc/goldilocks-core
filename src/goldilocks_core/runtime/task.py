"""Task handler: bundle a task graph with its context builder and result assembler.

The runtime dispatches through a ``TaskHandler`` polymorphically: each task
owns its graph (``TaskSpec``), its context builder (``build_context``), and
its result assembler (``assemble_result``). The runtime imports no
task-specific code -- it hands a request and itself to ``build_context`` and
the resulting records to ``assemble_result``, so new tasks (nscf, phonons)
register without editing the runtime.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from goldilocks_core.contracts import PresetRequest, QueryRequest, Records
from goldilocks_core.runtime.graph import TaskGraph
from goldilocks_core.runtime.models import Runtime


@dataclass(frozen=True, slots=True)
class GraphHandler:
    """A task's graph plus the hooks to run it under the runtime.

    Attributes:
        spec: the task's stage graph and named presets.
        build_context: ``(request, runtime) -> context`` for the task's stages.
        assemble_result: ``(request, records) -> result`` for a full preset.
    """

    spec: TaskGraph
    build_context: Callable[[PresetRequest | QueryRequest, Runtime], Any]
    assemble_result: Callable[[PresetRequest, Records], Any]
