from __future__ import annotations

from typing import TypedDict


class FileReference(TypedDict):
    path: str
    role: str


class GeneratedFile(FileReference):
    content: str


type GeneratedFiles = tuple[GeneratedFile, ...]
