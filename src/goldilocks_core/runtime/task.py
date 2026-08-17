from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from goldilocks_core.contracts import PresetRequest, QueryRequest, Records
from goldilocks_core.runtime.graph import TaskGraph
from goldilocks_core.runtime.models import Runtime


@dataclass(frozen=True, slots=True)
class GraphHandler:
    spec: TaskGraph
    build_context: Callable[[PresetRequest | QueryRequest, Runtime], Any]
    assemble_result: Callable[[PresetRequest, Records], Any]
