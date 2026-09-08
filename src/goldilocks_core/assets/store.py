from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from goldilocks_core.assets.download import download
from goldilocks_core.assets.records import (
    AssetPreparer,
    AssetReference,
    AssetSpec,
    InstalledAsset,
    InstalledFile,
)
from goldilocks_core.failures import ExpectedFailure

ASSET_ROOT_ENV = "GOLDILOCKS_ASSET_ROOT"
_MANIFEST_SCHEMA_VERSION = 2
_MANIFEST = "manifest.json"


class AssetNotInstalled(ExpectedFailure, FileNotFoundError):
    kind = "asset_not_installed"
    category = "dependency"

    def __init__(
        self,
        reference: AssetReference,
        root: Path,
        *,
        reason: str = "is not installed",
    ) -> None:
        self.reference = reference
        self.root = root
        self.reason = reason
        super().__init__(
            f"runtime asset {reference.id}@{reference.version} {reason} in {root}; "
            f"run 'goldilocks assets install {reference.id}'"
        )

    def public_error(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "message": (
                f"Runtime asset {self.reference.id}@{self.reference.version} "
                f"{self.reason}."
            ),
            "asset_id": self.reference.id,
            "version": self.reference.version,
            "reason": self.reason,
        }


class AssetCorrupt(ExpectedFailure, ValueError):
    kind = "asset_corrupt"
    category = "dependency"

    def public_error(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "message": "A required runtime asset failed integrity verification.",
        }


class AssetStore:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = asset_root(root)

    def install(
        self,
        spec: AssetSpec,
        prepare: AssetPreparer | None = None,
    ) -> InstalledAsset:
        self.root.mkdir(parents=True, exist_ok=True)
        with self._lock(spec.id, spec.version):
            try:
                return self.verify_spec(spec)
            except (AssetNotInstalled, AssetCorrupt):
                pass

            asset_directory = self.root / spec.id
            if asset_directory.is_symlink() or (
                asset_directory.exists() and not asset_directory.is_dir()
            ):
                asset_directory.unlink()
            asset_directory.mkdir(parents=True, exist_ok=True)
            destination = self._asset_path(spec.id, spec.version)
            staging_prefix = f".{spec.id.replace('/', '_')}-{spec.version}-"
            staging_root = Path(tempfile.mkdtemp(prefix=staging_prefix, dir=self.root))
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
                _write_manifest(installed_dir, spec, files)
                _remove_corrupt_destination(destination)
                os.replace(installed_dir, destination)
            finally:
                shutil.rmtree(staging_root, ignore_errors=True)
            return self.verify_spec(spec)

    def resolve(self, asset_id: str, version: str) -> InstalledAsset:
        return self.verify(asset_id, version)

    def resolve_spec(self, spec: AssetSpec) -> InstalledAsset:
        """Resolve an asset and require its registered preparation identity."""
        return self.verify_spec(spec)

    def verify_spec(self, spec: AssetSpec) -> InstalledAsset:
        """Verify an asset against its registered sources and preparer revision."""
        return self.verify(
            spec.id,
            spec.version,
            preparation_fingerprint=spec.preparation_fingerprint,
        )

    def verify(
        self,
        asset_id: str,
        version: str,
        *,
        preparation_fingerprint: str | None = None,
    ) -> InstalledAsset:
        reference = AssetReference(asset_id, version)
        root = self._asset_path(asset_id, version)
        manifest_path = root / _MANIFEST
        for path, required_type, reason in (
            (root, Path.is_dir, "is not installed"),
            (manifest_path, Path.is_file, "has no complete manifest"),
        ):
            if path.is_symlink():
                raise AssetCorrupt(f"installed asset contains a symlink: {path}")
            if not path.exists():
                raise AssetNotInstalled(reference, self.root, reason=reason)
            if not required_type(path):
                raise AssetCorrupt(f"installed asset path has the wrong type: {path}")

        installed_fingerprint, files = _read_manifest(manifest_path, reference)
        if (
            preparation_fingerprint is not None
            and installed_fingerprint != preparation_fingerprint
        ):
            raise AssetCorrupt(
                f"installed preparation differs for {asset_id}@{version}"
            )
        expected_paths = {file.path for file in files}
        actual_paths = {
            path.relative_to(root).as_posix() for path in _asset_files(root)
        }
        actual_paths.discard(_MANIFEST)
        if actual_paths != expected_paths:
            raise AssetCorrupt(
                f"installed file set differs from manifest for {asset_id}@{version}"
            )

        for file in files:
            path = root / file.path
            try:
                if path.stat().st_size != file.size or _sha256(path) != file.sha256:
                    raise AssetCorrupt(f"installed file changed: {path}")
            except OSError as error:
                raise AssetCorrupt(f"cannot verify installed file: {path}") from error
        return InstalledAsset(
            id=asset_id,
            version=version,
            preparation_fingerprint=installed_fingerprint,
            root=root,
            files=files,
        )

    def status(self, asset_id: str, version: str) -> str:
        try:
            self.verify(asset_id, version)
        except AssetNotInstalled:
            return "missing"
        except AssetCorrupt:
            return "corrupt"
        return "installed"

    def status_spec(self, spec: AssetSpec) -> str:
        """Return status against a registered asset preparation identity."""
        try:
            self.verify_spec(spec)
        except AssetNotInstalled:
            return "missing"
        except AssetCorrupt:
            return "corrupt"
        return "installed"

    def _asset_path(self, asset_id: str, version: str) -> Path:
        reference = AssetReference(asset_id, version)
        asset_directory = self.root / reference.id
        if asset_directory.is_symlink() or (
            asset_directory.exists() and not asset_directory.is_dir()
        ):
            raise AssetCorrupt(
                f"asset id destination is not a directory: {asset_directory}"
            )
        return asset_directory / reference.version

    @contextmanager
    def _lock(self, asset_id: str, version: str) -> Iterator[None]:
        AssetReference(asset_id, version)
        locks = self.root / ".locks"
        locks.mkdir(parents=True, exist_ok=True)
        lock_name = f"{asset_id.replace('/', '_')}-{version}.lock"
        lock_path = locks / lock_name
        with lock_path.open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


def asset_root(root: str | Path | None = None) -> Path:
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


def _asset_files(root: Path) -> Iterator[Path]:
    """Walk regular asset files, rejecting links and special filesystem entries."""
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise AssetCorrupt(f"installed asset contains a symlink: {path}")
        if path.is_file():
            yield path
        elif not path.is_dir():
            raise AssetCorrupt(f"installed asset contains a non-regular path: {path}")


def _inventory(root: Path) -> tuple[InstalledFile, ...]:
    return tuple(
        InstalledFile(
            path=path.relative_to(root).as_posix(),
            sha256=_sha256(path),
            size=path.stat().st_size,
        )
        for path in _asset_files(root)
        if path.name != _MANIFEST
    )


def _write_manifest(
    root: Path,
    spec: AssetSpec,
    files: tuple[InstalledFile, ...],
) -> None:
    data = {
        "schema_version": _MANIFEST_SCHEMA_VERSION,
        "id": spec.id,
        "version": spec.version,
        "preparation_fingerprint": spec.preparation_fingerprint,
        "files": [
            {"path": file.path, "sha256": file.sha256, "size": file.size}
            for file in files
        ],
    }
    (root / _MANIFEST).write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _read_manifest(
    path: Path,
    reference: AssetReference,
) -> tuple[str, tuple[InstalledFile, ...]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) != {
            "schema_version",
            "id",
            "version",
            "files",
            "preparation_fingerprint",
        }:
            raise ValueError("manifest fields are invalid")
        if (
            isinstance(data["schema_version"], bool)
            or data["schema_version"] != _MANIFEST_SCHEMA_VERSION
        ):
            raise ValueError(
                f"unsupported manifest schema_version {data['schema_version']!r}"
            )
        if data["id"] != reference.id or data["version"] != reference.version:
            raise ValueError("installed manifest identity does not match its path")
        fingerprint = data["preparation_fingerprint"]
        if (
            not isinstance(fingerprint, str)
            or re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None
        ):
            raise ValueError("installed preparation fingerprint is invalid")
        raw_files = data["files"]
        if not isinstance(raw_files, list) or not raw_files:
            raise ValueError("installed manifest file inventory must be non-empty")
        files: list[InstalledFile] = []
        for entry in raw_files:
            if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "size"}:
                raise ValueError("installed manifest file entry is invalid")
            files.append(InstalledFile(**entry))
        paths = [file.path for file in files]
        if len(paths) != len(set(paths)):
            raise ValueError("installed manifest paths must be unique")
        return fingerprint, tuple(files)
    except (
        KeyError,
        TypeError,
        UnicodeError,
        json.JSONDecodeError,
        ValueError,
    ) as error:
        raise AssetCorrupt(f"invalid installed manifest: {path}: {error}") from error


def _remove_corrupt_destination(path: Path) -> None:
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
