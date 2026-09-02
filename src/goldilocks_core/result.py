from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from goldilocks_core.selection import SelectionRecord, selection_portable
from goldilocks_core.serialization import to_jsonable, to_portable
from goldilocks_core.types import JsonDict

if TYPE_CHECKING:
    from goldilocks_core.request import (
        CalculationDraft,
        ComputationSelection,
    )


class Records(Mapping[type, Any]):
    __slots__ = ("_records",)

    def __init__(self, records: Mapping[type, Any] | None = None) -> None:
        self._records = dict(records or {})

    def __getitem__(self, record_type: type) -> Any:
        return self._records[record_type]

    def __iter__(self) -> Iterator[type]:
        return iter(self._records)

    def __len__(self) -> int:
        return len(self._records)


@to_portable.register(Records)
def _records_portable(records: Records) -> JsonDict:
    from goldilocks_core.runtime.registry import record_type_id

    return {
        record_type_id(record_type): to_portable(record)
        for record_type, record in records.items()
    }


@dataclass(frozen=True, slots=True)
class ComputationResult:
    """Complete record set from one Compute call.

    ``records`` holds every computed record for the requested selection;
    ``warnings`` aggregates every stage's warnings and is the authoritative
    place to check for incomplete or degraded results. ``publication`` is
    set only when the request named an output target.
    """

    draft: CalculationDraft
    task: str
    task_revision: str
    selection: ComputationSelection
    records: Records
    warnings: tuple[str, ...] = ()
    publication: JsonDict | None = None
    schema_version: int = field(default=1, init=False)


@to_portable.register(ComputationResult)
def _computation_result_portable(result: ComputationResult) -> JsonDict:
    from goldilocks_core.runtime.registry import record_type_id

    records = {}
    for record_type, value in result.records.items():
        record_id = record_type_id(record_type)
        if record_type is SelectionRecord:
            records[record_id] = selection_portable(value)
        else:
            records[record_id] = to_portable(value)
    return {
        "schema_version": result.schema_version,
        "draft": to_portable(result.draft),
        "task": result.task,
        "task_revision": result.task_revision,
        "selection": to_portable(result.selection),
        "records": records,
        "warnings": list(result.warnings),
        "publication": to_jsonable(result.publication),
    }
