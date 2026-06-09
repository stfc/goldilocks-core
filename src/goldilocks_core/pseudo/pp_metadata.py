"""Structured pseudopotential metadata definitions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class PseudoMetadata:
    filepath: str
    filename: str
    header_format: str
    library: str | None = None
    source_set: str | None = None
    element: str | None = None
    pseudo_type: str | None = None
    functional: str | None = None
    relativistic: str | None = None
    z_valence: float | None = None
    pseudo_info: dict[str, Any] = field(default_factory=dict)
    is_sssp: bool = False
    source_pseudopotential: str | None = None
    sssp_recommended_cutoff: dict[str, Any] | None = None

    def to_dict(self) -> dict:
        return asdict(self)
