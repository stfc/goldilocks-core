from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from goldilocks_core.contracts.advice import ParameterAdvice
from goldilocks_core.contracts.analysis import StructureAnalysisRecord
from goldilocks_core.contracts.hints import CalculationIntent
from goldilocks_core.contracts.kpoints import KPointSelection
from goldilocks_core.contracts.selection import SelectionRecord
from goldilocks_core.contracts.serial import to_jsonable
from goldilocks_core.contracts.types import JsonDict


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
class Result:
    intent: CalculationIntent
    analysis: StructureAnalysisRecord
    advice: ParameterAdvice
    k_points: KPointSelection
    selection: SelectionRecord
    generated_files: GeneratedFiles = ()
    warnings: tuple[str, ...] = ()
    bundle: BundleRecord | None = None

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)
