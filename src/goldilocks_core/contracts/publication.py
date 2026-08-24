from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DirectoryOutput:
    path: str | Path | None = None

    def __post_init__(self) -> None:
        if self.path is not None:
            _validate_destination(self.path)


@dataclass(frozen=True, slots=True)
class ArchiveOutput:
    path: str | Path

    def __post_init__(self) -> None:
        _validate_destination(self.path)


type OutputTarget = DirectoryOutput | ArchiveOutput


def _validate_destination(path: str | Path) -> None:
    if not isinstance(path, str | Path) or not str(path).strip():
        raise ValueError("output destination must be a non-empty path")
