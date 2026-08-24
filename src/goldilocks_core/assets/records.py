from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AssetFile:
    role: str
    path: str
    url: str
    checksum: str | None = None
    size: int | None = None

    def __post_init__(self) -> None:
        _validate_component(self.role, "asset file role")
        _validate_relative_path(self.path, "asset file path")
        if not isinstance(self.url, str) or not self.url:
            raise ValueError("asset file URL cannot be empty")
        if self.checksum is not None:
            _validate_checksum(self.checksum)
        if self.size is not None and (
            isinstance(self.size, bool)
            or not isinstance(self.size, int)
            or self.size < 0
        ):
            raise ValueError("asset file size must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class AssetSpec:
    id: str
    version: str
    files: tuple[AssetFile, ...]
    preparation_revision: str = "1"

    def __post_init__(self) -> None:
        _validate_asset_id(self.id, "asset id")
        _validate_component(self.version, "asset version")
        _validate_component(self.preparation_revision, "asset preparation revision")
        if not isinstance(self.files, tuple):
            object.__setattr__(self, "files", tuple(self.files))
        if not self.files:
            raise ValueError("asset must declare at least one source file")
        roles = [file.role for file in self.files]
        paths = [file.path for file in self.files]
        if len(roles) != len(set(roles)):
            raise ValueError("asset file roles must be unique")
        if len(paths) != len(set(paths)):
            raise ValueError("asset file paths must be unique")

    @property
    def preparation_fingerprint(self) -> str:
        """Return the deterministic source and preparation identity."""
        payload = {
            "id": self.id,
            "version": self.version,
            "preparation_revision": self.preparation_revision,
            "files": [
                {
                    "role": file.role,
                    "path": file.path,
                    "url": file.url,
                    "checksum": file.checksum,
                    "size": file.size,
                }
                for file in self.files
            ],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


class AssetPreparer(Protocol):
    def __call__(self, sources: Mapping[str, Path], destination: Path) -> None: ...


@dataclass(frozen=True, slots=True)
class AssetInstallation:
    spec: AssetSpec
    prepare: AssetPreparer | None = None


@dataclass(frozen=True, slots=True)
class InstalledFile:
    path: str
    sha256: str
    size: int

    def __post_init__(self) -> None:
        _validate_relative_path(self.path, "installed file path")
        if re.fullmatch(r"[0-9a-fA-F]{64}", self.sha256) is None:
            raise ValueError("installed file sha256 must contain 64 hexadecimal digits")
        object.__setattr__(self, "sha256", self.sha256.lower())
        if (
            isinstance(self.size, bool)
            or not isinstance(self.size, int)
            or self.size < 0
        ):
            raise ValueError("installed file size must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class InstalledAsset:
    id: str
    version: str
    preparation_fingerprint: str
    root: Path
    files: tuple[InstalledFile, ...]

    def path(self, relative_path: str) -> Path:
        matches = [file for file in self.files if file.path == relative_path]
        if not matches:
            raise KeyError(
                f"asset {self.id}@{self.version} has no file {relative_path!r}"
            )
        return self.root / relative_path


@dataclass(frozen=True, slots=True)
class AssetReference:
    id: str
    version: str

    def __post_init__(self) -> None:
        _validate_asset_id(self.id, "asset id")
        _validate_component(self.version, "asset version")


@dataclass(frozen=True, slots=True)
class RuntimeProfile:
    name: str
    assets: tuple[AssetReference, ...]

    def __post_init__(self) -> None:
        _validate_component(self.name, "runtime profile name")
        if not isinstance(self.assets, tuple):
            object.__setattr__(self, "assets", tuple(self.assets))
        identities = [(asset.id, asset.version) for asset in self.assets]
        if len(identities) != len(set(identities)):
            raise ValueError("runtime profile asset references must be unique")


def _validate_component(value: str, label: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
    ):
        raise ValueError(f"{label} must be one non-empty path component: {value!r}")


def _validate_asset_id(value: str, label: str) -> None:
    """Require a domain-namespaced id such as 'models/qrf-kpoints'."""
    domain, separator, name = (value or "").partition("/")
    if not separator or not domain or not name:
        raise ValueError(
            f"{label} must be namespaced as '<domain>/<name>', for example "
            f"'models/qrf-kpoints': {value!r}"
        )
    _validate_component(domain, f"{label} domain")
    _validate_component(name, f"{label} name")


def _validate_relative_path(value: str, label: str) -> None:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"{label} must be relative and contained: {value!r}")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or path.as_posix() != value
    ):
        raise ValueError(f"{label} must be relative and contained: {value!r}")


def _validate_checksum(value: str) -> None:
    algorithm, separator, digest = value.partition(":")
    if not separator or not algorithm or not digest:
        raise ValueError(f"checksum must be '<algorithm>:<digest>': {value!r}")
    try:
        expected_length = hashlib.new(algorithm).digest_size * 2
    except ValueError as error:
        raise ValueError(f"unsupported checksum algorithm: {algorithm}") from error
    if (
        expected_length == 0
        or len(digest) != expected_length
        or re.fullmatch(r"[0-9a-fA-F]+", digest) is None
    ):
        raise ValueError(f"checksum digest is invalid for {algorithm}: {digest!r}")
