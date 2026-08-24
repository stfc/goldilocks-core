from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from goldilocks_core.contracts import ComputeRequest, Records
from goldilocks_core.runtime.graph import TaskGraph
from goldilocks_core.runtime.models import Runtime


def _no_warnings(records: Records) -> tuple[str, ...]:
    del records
    return ()


@dataclass(frozen=True, slots=True)
class GraphHandler:
    spec: TaskGraph
    build_context: Callable[[ComputeRequest, Runtime], Any]
    collect_warnings: Callable[[Records], tuple[str, ...]] = _no_warnings
