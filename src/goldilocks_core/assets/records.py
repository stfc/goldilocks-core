"""Immutable records shared by runtime-asset domains."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True, slots=True)
class AssetFile:
    """One source file required to install an asset."""

    role: str
    path: str
    url: str
    checksum: str | None = None
    size: int | None = None

    def __post_init__(self) -> None:
        _validate_component(self.role, "asset file role")
        path = PurePosixPath(self.path)
        if path.is_absolute() or not path.parts or ".." in path.parts:
            raise ValueError(
                f"asset file path must be relative and contained: {self.path!r}"
            )
        if not self.url:
            raise ValueError("asset file URL cannot be empty")
        if self.size is not None and self.size < 0:
            raise ValueError("asset file size cannot be negative")


@dataclass(frozen=True, slots=True)
class AssetSpec:
    """Complete acquisition description for one immutable asset version."""

    id: str
    version: str
    files: tuple[AssetFile, ...]

    def __post_init__(self) -> None:
        _validate_component(self.id, "asset id")
        _validate_component(self.version, "asset version")
        if not self.files:
            raise ValueError("asset must declare at least one source file")
        roles = [file.role for file in self.files]
        paths = [file.path for file in self.files]
        if len(roles) != len(set(roles)):
            raise ValueError("asset file roles must be unique")
        if len(paths) != len(set(paths)):
            raise ValueError("asset file paths must be unique")


@dataclass(frozen=True, slots=True)
class InstalledFile:
    """One verified file in an installed asset."""

    path: str
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class InstalledAsset:
    """A complete verified asset published in an asset store."""

    id: str
    version: str
    root: Path
    files: tuple[InstalledFile, ...]

    def path(self, relative_path: str) -> Path:
        """Resolve a manifested file beneath the installed asset root."""
        matches = [file for file in self.files if file.path == relative_path]
        if not matches:
            raise KeyError(
                f"asset {self.id}@{self.version} has no file {relative_path!r}"
            )
        return self.root / relative_path


@dataclass(frozen=True, slots=True)
class AssetReference:
    """Exact asset identity included in a runtime profile."""

    id: str
    version: str


@dataclass(frozen=True, slots=True)
class RuntimeProfile:
    """Exact asset versions required by a supported deployment."""

    name: str
    assets: tuple[AssetReference, ...]


def _validate_component(value: str, label: str) -> None:
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError(f"{label} must be one non-empty path component: {value!r}")
