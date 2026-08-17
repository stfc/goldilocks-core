from __future__ import annotations

from dataclasses import dataclass

from goldilocks_core.contracts.serial import to_jsonable
from goldilocks_core.contracts.types import JsonDict, ProvenanceSource


@dataclass(frozen=True, slots=True)
class Provenance:
    """Reason and source for a scientific recommendation or selection.

    Every advice and selection record carries provenance so callers can
    understand why a value was chosen and whether to trust or override it.

    Attributes:
        source: why this value was chosen. One of ``analysis``,
            ``user_hint``, ``default``, ``model``, ``lookup``, or
            ``fallback``.
        reason: human-readable explanation of the choice.
        data_source: origin of supporting data (e.g. model name,
            pseudo library, SSSP version).
        confidence: optional confidence score in [0, 1].
        details: optional structured, JSON-safe decision metadata. Model-backed
            decisions use this for reproducible inference configuration.
        warnings: caveats the caller should be aware of.
    """

    source: ProvenanceSource
    reason: str
    data_source: str | None = None
    confidence: float | None = None
    details: JsonDict | None = None
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)
