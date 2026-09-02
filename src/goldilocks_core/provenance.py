from __future__ import annotations

from dataclasses import dataclass

from goldilocks_core.types import JsonDict, ProvenanceSource


@dataclass(frozen=True, slots=True)
class Provenance:
    source: ProvenanceSource
    reason: str
    data_source: str | None = None
    confidence: float | None = None
    details: JsonDict | None = None
    warnings: tuple[str, ...] = ()
