from __future__ import annotations

from dataclasses import dataclass

from goldilocks_core.contracts.serial import to_jsonable
from goldilocks_core.contracts.types import JsonDict, ProvenanceSource


@dataclass(frozen=True, slots=True)
class Provenance:
    source: ProvenanceSource
    reason: str
    data_source: str | None = None
    confidence: float | None = None
    details: JsonDict | None = None
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)
