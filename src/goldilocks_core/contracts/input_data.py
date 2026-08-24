from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from goldilocks_core.contracts.provenance import Provenance
from goldilocks_core.contracts.serial import to_jsonable
from goldilocks_core.contracts.types import JsonDict


@dataclass(frozen=True, slots=True)
class GeneratedContent:
    content: bytes
    identity: str

    def to_dict(self) -> JsonDict:
        return {"kind": "generated", "identity": self.identity}


@dataclass(frozen=True, slots=True)
class InstalledArtifactReference:
    asset_id: str
    asset_version: str
    path: str

    def to_dict(self) -> JsonDict:
        return {
            "kind": "installed",
            "asset_id": self.asset_id,
            "asset_version": self.asset_version,
            "path": self.path,
        }


type ArtifactSource = GeneratedContent | InstalledArtifactReference


@dataclass(frozen=True, slots=True)
class InputArtifact:
    path: str
    role: str
    sha256: str
    size_bytes: int
    source: ArtifactSource
    media_type: str | None = None
    provenance: Provenance | None = None

    def to_dict(self) -> JsonDict:
        return {
            "path": self.path,
            "role": self.role,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "media_type": self.media_type,
            "provenance": to_jsonable(self.provenance),
            "source": self.source.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class PseudopotentialSetIdentity:
    id: str
    version: str | None
    provider: str
    functional: str
    accuracy: str
    relativistic: str
    licence: str
    citation: str
    policy: JsonDict

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class RuntimeAssetIdentity:
    id: str
    version: str
    role: str

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class RuntimeIdentity:
    core_version: str
    models: tuple[JsonDict, ...] = ()
    assets: tuple[RuntimeAssetIdentity, ...] = ()

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class DftInputData:
    artifacts: tuple[InputArtifact, ...]
    pseudopotential_set: PseudopotentialSetIdentity
    runtime: RuntimeIdentity
    citations: tuple[str, ...]
    manifest: JsonDict
    schema_version: Literal[1] = 1

    def to_dict(self) -> JsonDict:
        return {
            "schema_version": self.schema_version,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "pseudopotential_set": self.pseudopotential_set.to_dict(),
            "runtime": self.runtime.to_dict(),
            "citations": list(self.citations),
            "manifest": to_jsonable(self.manifest),
        }
