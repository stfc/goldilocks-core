from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from goldilocks_core.contracts.serial import to_jsonable
from goldilocks_core.contracts.types import JsonDict

if TYPE_CHECKING:
    from goldilocks_core.contracts.requests import (
        CalculationDraft,
        ComputationSelection,
    )


@dataclass(frozen=True, slots=True)
class GeneratedFile:
    path: str
    content: str
    role: str = "input"

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)


type GeneratedFiles = tuple[GeneratedFile, ...]


@dataclass(frozen=True, slots=True)
class BundleRecord:
    path: str
    manifest: JsonDict

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)


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

    def to_dict(self) -> JsonDict:
        from goldilocks_core.contracts.registry import record_type_id

        return to_jsonable(
            {
                record_type_id(record_type): record
                for record_type, record in self._records.items()
            }
        )


@dataclass(frozen=True, slots=True)
class Publication:
    kind: Literal["directory", "archive"]
    path: str | None = None

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class ComputationResult:
    draft: CalculationDraft
    task: str
    task_revision: str
    selection: ComputationSelection
    records: Records
    warnings: tuple[str, ...] = ()
    publication: Publication | None = None
    schema_version: int = field(default=1, init=False)

    def to_dict(self) -> JsonDict:
        return {
            "schema_version": self.schema_version,
            "draft": self.draft.to_dict(),
            "task": self.task,
            "task_revision": self.task_revision,
            "selection": self.selection.to_dict(),
            "records": self.records.to_dict(),
            "warnings": list(self.warnings),
            "publication": to_jsonable(self.publication),
        }
