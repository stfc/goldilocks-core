from __future__ import annotations

from typing import Annotated, TypedDict

from goldilocks_core.serialization import Portable


class FileReference(TypedDict):
    path: str
    role: str


class InputArtifact(FileReference):
    content: Annotated[bytes, Portable()]


class GeneratedFile(FileReference):
    content: str


type GeneratedFiles = tuple[GeneratedFile, ...]
