"""Transactional external store for immutable runtime assets."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

from goldilocks_core.assets.download import download
from goldilocks_core.assets.records import (
    AssetSpec,
    InstalledAsset,
    InstalledFile,
)

ASSET_ROOT_ENV = "GOLDILOCKS_ASSET_ROOT"
_MANIFEST = "manifest.json"


class AssetNotInstalled(FileNotFoundError):
    """The requested asset is absent or incomplete."""


class AssetCorrupt(ValueError):
    """An installed asset does not match its manifest."""


class AssetPreparer(Protocol):
    """Convert verified source files into a normalized installed asset."""

    def __call__(self, sources: Mapping[str, Path], destination: Path) -> None: ...


class AssetStore:
    """Install, resolve, and verify complete immutable runtime assets."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = asset_root(root)

    def install(
        self,
        spec: AssetSpec,
        prepare: AssetPreparer | None = None,
    ) -> InstalledAsset:
        """Acquire, prepare, and atomically publish one asset version."""
        self.root.mkdir(parents=True, exist_ok=True)
        with self._lock(spec.id, spec.version):
            try:
                return self.verify(spec.id, spec.version)
            except (AssetNotInstalled, AssetCorrupt):
                pass
            destination = self._asset_path(spec.id, spec.version)
            destination.parent.mkdir(parents=True, exist_ok=True)
            staging_root = Path(
                tempfile.mkdtemp(prefix=f".{spec.id}-{spec.version}-", dir=self.root)
            )
            try:
                sources_dir = staging_root / "sources"
                installed_dir = staging_root / "installed"
                sources_dir.mkdir()
                installed_dir.mkdir()
                sources: dict[str, Path] = {}
                for index, file in enumerate(spec.files):
                    source = sources_dir / f"{index:04d}"
                    download(file, source)
                    sources[file.role] = source
                (prepare or _copy_sources(spec))(sources, installed_dir)
                files = _inventory(installed_dir)
                if not files:
                    raise ValueError("asset preparation produced no files")
                _write_manifest(installed_dir, spec.id, spec.version, files)
                if destination.exists():
                    shutil.rmtree(destination)
                os.replace(installed_dir, destination)
            finally:
                shutil.rmtree(staging_root, ignore_errors=True)
            return self.verify(spec.id, spec.version)

    def resolve(self, asset_id: str, version: str) -> InstalledAsset:
        """Return one installed asset after verifying its manifest."""
        try:
            return self.verify(asset_id, version)
        except AssetNotInstalled as error:
            raise AssetNotInstalled(
                f"runtime asset {asset_id}@{version} is not installed in {self.root}; "
                f"run 'goldilocks assets install {asset_id}'"
            ) from error

    def verify(self, asset_id: str, version: str) -> InstalledAsset:
        """Verify every installed file against the immutable manifest."""
        root = self._asset_path(asset_id, version)
        manifest_path = root / _MANIFEST
        if not manifest_path.is_file():
            raise AssetNotInstalled(
                f"runtime asset {asset_id}@{version} is not installed"
            )
        try:
            data = json.loads(manifest_path.read_text())
            if data["id"] != asset_id or data["version"] != version:
                raise AssetCorrupt(
                    "installed manifest identity does not match its path"
                )
            files = tuple(InstalledFile(**entry) for entry in data["files"])
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise AssetCorrupt(
                f"invalid installed manifest: {manifest_path}"
            ) from error
        expected_paths = {file.path for file in files}
        actual_paths = {
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and path.name != _MANIFEST
        }
        if actual_paths != expected_paths:
            raise AssetCorrupt(
                f"installed file set differs from manifest for {asset_id}@{version}"
            )
        for file in files:
            path = root / file.path
            if path.stat().st_size != file.size or _sha256(path) != file.sha256:
                raise AssetCorrupt(f"installed file changed: {path}")
        return InstalledAsset(asset_id, version, root, files)

    def status(self, asset_id: str, version: str) -> str:
        """Return installed, missing, or corrupt without hiding error details."""
        try:
            self.verify(asset_id, version)
        except AssetNotInstalled:
            return "missing"
        except AssetCorrupt:
            return "corrupt"
        return "installed"

    def _asset_path(self, asset_id: str, version: str) -> Path:
        for value, label in ((asset_id, "asset id"), (version, "asset version")):
            if not value or value in {".", ".."} or "/" in value or "\\" in value:
                raise ValueError(f"{label} must be one path component: {value!r}")
        return self.root / asset_id / version

    @contextmanager
    def _lock(self, asset_id: str, version: str):
        locks = self.root / ".locks"
        locks.mkdir(parents=True, exist_ok=True)
        lock_path = locks / f"{asset_id}-{version}.lock"
        with lock_path.open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


def asset_root(root: str | Path | None = None) -> Path:
    """Resolve the explicit, environment, or XDG runtime-asset root."""
    if root is not None:
        return Path(root).expanduser().resolve()
    override = os.environ.get(ASSET_ROOT_ENV)
    if override:
        return Path(override).expanduser().resolve()
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return (base / "goldilocks" / "assets").resolve()


def _copy_sources(spec: AssetSpec) -> AssetPreparer:
    by_role = {file.role: file for file in spec.files}

    def prepare(sources: Mapping[str, Path], destination: Path) -> None:
        for role, source in sources.items():
            target = destination / by_role[role].path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)

    return prepare


def _inventory(root: Path) -> tuple[InstalledFile, ...]:
    return tuple(
        InstalledFile(
            path=path.relative_to(root).as_posix(),
            sha256=_sha256(path),
            size=path.stat().st_size,
        )
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != _MANIFEST
    )


def _write_manifest(
    root: Path,
    asset_id: str,
    version: str,
    files: tuple[InstalledFile, ...],
) -> None:
    data = {
        "schema_version": 1,
        "id": asset_id,
        "version": version,
        "files": [
            {"path": file.path, "sha256": file.sha256, "size": file.size}
            for file in files
        ],
    }
    (root / _MANIFEST).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
