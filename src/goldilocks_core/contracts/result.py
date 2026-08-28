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

        return {
            record_type_id(record_type): (
                record.to_dict() if hasattr(record, "to_dict") else to_jsonable(record)
            )
            for record_type, record in self._records.items()
        }


@dataclass(frozen=True, slots=True)
class Publication:
    """A published output bundle and its integrity facts.

    ``path`` is the published location; ``files`` lists every published
    path relative to it. ``manifest_sha256`` pins the archive manifest and
    ``output_sha256`` pins the archive bytes; it is ``None`` for directory
    publications.
    """

    kind: Literal["directory", "archive"]
    path: str
    files: tuple[str, ...]
    manifest_sha256: str
    output_sha256: str | None = None

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)


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
