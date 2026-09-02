from __future__ import annotations

from dataclasses import dataclass

from goldilocks_core.serialization import to_jsonable
from goldilocks_core.types import JsonDict


@dataclass(frozen=True, slots=True)
class GeneratedFile:
    path: str
    content: str
    role: str = "input"

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)


type GeneratedFiles = tuple[GeneratedFile, ...]
