from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DirectoryOutput:
    path: str | Path

    def __post_init__(self) -> None:
        _validate_destination(self.path)


def _validate_destination(path: str | Path) -> None:
    if not isinstance(path, str | Path) or not str(path).strip():
        raise ValueError("output destination must be a non-empty path")
