from __future__ import annotations

import contextlib
import ctypes
import errno
import hashlib
import io
import json
import os
import secrets
import shutil
import stat
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from goldilocks_core.assets.store import AssetStore
from goldilocks_core.types import JsonDict


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


@dataclass(frozen=True, slots=True)
class PublishedFile:
    path: str
    content: bytes
    role: str
    sha256: str


class Publisher:
    def __init__(self, asset_store: AssetStore | None = None) -> None:
        self._asset_store = asset_store

    def files(self, input_data: JsonDict) -> tuple[PublishedFile, ...]:
        files: dict[str, tuple[bytes, str]] = {}
        for artifact in input_data["artifacts"]:
            _validate_publication_path(artifact["path"])
            _add(files, artifact["path"], self._content(artifact), artifact["role"])

        _add(
            files,
            "CITATIONS.md",
            _citations(input_data).encode("utf-8"),
            "citations",
        )
        _add(files, "README.md", _readme(input_data).encode("utf-8"), "readme")
        manifest = {
            "schema_version": 1,
            **input_data["manifest"],
            "files": {
                path: {
                    "role": role,
                    "sha256": _sha256(content),
                    "size_bytes": len(content),
                }
                for path, (content, role) in sorted(files.items())
            },
        }
        _add(
            files,
            "goldilocks.json",
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            "manifest",
        )
        checksums = "".join(
            f"{_sha256(content)}  {path}\n"
            for path, (content, _) in sorted(files.items())
        )
        _add(
            files,
            "checksums.sha256",
            checksums.encode("utf-8"),
            "checksums",
        )
        return tuple(
            PublishedFile(
                path=path,
                content=content,
                role=role,
                sha256=_sha256(content),
            )
            for path, (content, role) in sorted(files.items())
        )

    def publish(self, input_data: JsonDict, output: OutputTarget) -> JsonDict:
        files = self.files(input_data)
        if isinstance(output, DirectoryOutput):
            if output.path is None:
                return self._publish_automatic_directory(files)
            return self._publish_directory(files, Path(output.path))
        return self._publish_archive(files, Path(output.path))

    def archive_bytes(self, input_data: JsonDict) -> bytes:
        return _archive_bytes(self.files(input_data))

    def _publish_automatic_directory(
        self, files: tuple[PublishedFile, ...]
    ) -> JsonDict:
        index = 0
        while True:
            suffix = "" if index == 0 else f"_{index}"
            try:
                return self._publish_directory(
                    files, Path.cwd() / f"goldilocks_out{suffix}"
                )
            except FileExistsError:
                index += 1

    def _publish_directory(
        self, files: tuple[PublishedFile, ...], destination: Path
    ) -> JsonDict:
        target = destination.expanduser().absolute()
        platform = _publication_platform()
        if platform == "unsupported_unix":
            raise OSError(
                errno.ENOTSUP,
                "Atomic no-replace directory publication is not supported",
                os.fspath(target),
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        if platform == "windows":
            _publish_directory_windows(files, target)
        else:
            _require_descriptor_directory_support(target)
            _publish_directory_posix(files, target)
        return _publication("directory", target, files)

    def _publish_archive(
        self,
        files: tuple[PublishedFile, ...],
        destination: Path,
    ) -> JsonDict:
        target = destination.expanduser().absolute()
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, staging_name = tempfile.mkstemp(
            prefix=f".{target.name}.", dir=target.parent
        )
        staging = Path(staging_name)
        staging_identity = _descriptor_identity(descriptor)
        try:
            payload = _archive_bytes(files)
            _write_descriptor(descriptor, payload)
            if _read_descriptor(descriptor) != payload:
                raise OSError(f"Completed archive write differs: {staging}")
            _require_identity(
                staging,
                staging_identity,
                f"Publication staging changed during publication: {staging}",
            )
            try:
                os.link(staging, target)
            except FileExistsError as error:
                raise FileExistsError(
                    f"Publication destination already exists: {target}"
                ) from error
            _require_public_identity(target, staging_identity)
            if _sha256(target.read_bytes()) != _sha256(payload):
                raise OSError(f"Published archive checksum differs: {target}")
        finally:
            try:
                _remove_owned_staging(staging, staging_identity, directory=False)
            finally:
                os.close(descriptor)
        return _publication("archive", target, files, _sha256(payload))

    def _content(self, artifact: JsonDict) -> bytes:
        source = artifact["source"]
        if source["kind"] == "generated":
            payload = source["content"]
        else:
            if self._asset_store is None:
                raise ValueError(
                    "An AssetStore is required to publish installed artifact references"
                )
            installed = self._asset_store.verify(
                source["asset_id"],
                source["asset_version"],
                preparation_fingerprint=source["preparation_fingerprint"],
            )
            payload = installed.path(source["path"]).read_bytes()
        if (
            len(payload) != artifact["size_bytes"]
            or _sha256(payload) != artifact["sha256"]
        ):
            raise ValueError(
                f"Artifact {artifact['path']!r} differs from its "
                "DFT Input Data descriptor"
            )
        return payload


def _publication_platform() -> str:
    if os.name == "nt":
        return "windows"
    if os.name == "posix" and sys.platform.startswith("linux"):
        return "linux"
    if os.name == "posix" and sys.platform == "darwin":
        return "darwin"
    return "unsupported_unix"


def _require_descriptor_directory_support(target: Path) -> None:
    supports_directory_descriptors = (
        os.open in os.supports_dir_fd
        and os.mkdir in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.listdir in os.supports_fd
    )
    if not supports_directory_descriptors:
        raise OSError(
            errno.ENOTSUP,
            "Descriptor-anchored directory publication is not supported",
            os.fspath(target),
        )


def _publish_directory_posix(files: tuple[PublishedFile, ...], target: Path) -> None:
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    staging_identity = _path_identity(staging)
    staging_descriptor: int | None = None
    installed = False
    try:
        staging_descriptor = os.open(
            staging,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0),
        )
        staging_identity = _descriptor_identity(staging_descriptor)
        _write_directory(staging_descriptor, files)
        _verify_directory_descriptor(staging_descriptor, files)
        _require_identity(
            staging,
            staging_identity,
            f"Publication staging changed during publication: {staging}",
        )
        _verify_directory(staging, files)
        _require_identity(
            staging,
            staging_identity,
            f"Publication staging changed during publication: {staging}",
        )
        try:
            _rename_no_replace(staging, target)
        except FileExistsError as error:
            raise FileExistsError(
                f"Publication destination already exists: {target}"
            ) from error
        _require_public_identity(
            target,
            staging_identity,
            preferred_quarantine=staging,
        )
        installed = True
        try:
            _verify_directory_descriptor(staging_descriptor, files)
        except OSError:
            _quarantine_owned_directory(target, staging_identity)
            raise
        _require_public_identity(target, staging_identity)
    finally:
        if staging_descriptor is not None:
            os.close(staging_descriptor)
        if not installed:
            _remove_owned_staging(staging, staging_identity, directory=True)


def _publish_directory_windows(files: tuple[PublishedFile, ...], target: Path) -> None:
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    staging_identity = _path_identity(staging)
    installed = False
    try:
        _write_directory_path(staging, files)
        _verify_directory_path(staging, files)
        _require_identity(
            staging,
            staging_identity,
            f"Publication staging changed during publication: {staging}",
        )
        try:
            _rename_no_replace(staging, target)
        except FileExistsError as error:
            raise FileExistsError(
                f"Publication destination already exists: {target}"
            ) from error
        _require_public_identity(
            target,
            staging_identity,
            preferred_quarantine=staging,
        )
        installed = True
        try:
            _verify_directory_path(target, files)
        except OSError:
            _quarantine_owned_directory(target, staging_identity)
            raise
        _require_public_identity(target, staging_identity)
    finally:
        if not installed:
            _remove_owned_staging(staging, staging_identity, directory=True)


def _write_directory_path(root: Path, files: tuple[PublishedFile, ...]) -> None:
    for file in files:
        output = root.joinpath(*PurePosixPath(file.path).parts)
        output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with output.open("xb") as stream:
            stream.write(file.content)


def _verify_directory_path(root: Path, files: tuple[PublishedFile, ...]) -> None:
    expected = {file.path: (file.sha256, len(file.content)) for file in files}
    actual = _path_inventory(root)
    if actual != expected:
        raise OSError("Completed directory path write differs")


_POSIX_ROOT = PurePosixPath()


def _path_inventory(
    root: Path, prefix: PurePosixPath = _POSIX_ROOT
) -> dict[str, tuple[str, int]]:
    inventory: dict[str, tuple[str, int]] = {}
    for child in root.iterdir():
        path = prefix / child.name
        status = child.stat(follow_symlinks=False)
        if getattr(status, "st_file_attributes", 0) & 0x400:
            raise OSError(f"Completed directory contains reparse path: {path}")
        if stat.S_ISDIR(status.st_mode):
            inventory.update(_path_inventory(child, path))
        elif stat.S_ISREG(status.st_mode):
            content = child.read_bytes()
            inventory[path.as_posix()] = (_sha256(content), len(content))
        else:
            raise OSError(f"Completed directory contains non-regular path: {path}")
    return inventory


def _write_directory(descriptor: int, files: tuple[PublishedFile, ...]) -> None:
    for file in files:
        parts = PurePosixPath(file.path).parts
        parent = os.dup(descriptor)
        try:
            for part in parts[:-1]:
                with contextlib.suppress(FileExistsError):
                    os.mkdir(part, mode=0o700, dir_fd=parent)
                child = os.open(
                    part,
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=parent,
                )
                os.close(parent)
                parent = child
            output = os.open(
                parts[-1],
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=parent,
            )
            try:
                _write_all(output, file.content)
            finally:
                os.close(output)
        finally:
            os.close(parent)


def _write_descriptor(descriptor: int, content: bytes) -> None:
    os.ftruncate(descriptor, 0)
    os.lseek(descriptor, 0, os.SEEK_SET)
    _write_all(descriptor, content)


def _write_all(descriptor: int, content: bytes) -> None:
    view = memoryview(content)
    while view:
        written = os.write(descriptor, view)
        if written == 0:
            raise OSError("Descriptor write made no progress")
        view = view[written:]


def _read_descriptor(descriptor: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while chunk := os.read(descriptor, 1024 * 1024):
        chunks.append(chunk)
    return b"".join(chunks)


def _verify_directory_descriptor(
    descriptor: int, files: tuple[PublishedFile, ...]
) -> None:
    expected = {file.path: (file.sha256, len(file.content)) for file in files}
    actual = _descriptor_inventory(descriptor)
    if actual != expected:
        raise OSError("Completed directory descriptor write differs")


def _descriptor_inventory(
    descriptor: int, prefix: PurePosixPath = _POSIX_ROOT
) -> dict[str, tuple[str, int]]:
    inventory: dict[str, tuple[str, int]] = {}
    for name in os.listdir(descriptor):
        path = prefix / name
        status = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if stat.S_ISDIR(status.st_mode):
            child = os.open(
                name,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=descriptor,
            )
            try:
                inventory.update(_descriptor_inventory(child, path))
            finally:
                os.close(child)
        elif stat.S_ISREG(status.st_mode):
            source = os.open(
                name,
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=descriptor,
            )
            try:
                content = _read_descriptor(source)
            finally:
                os.close(source)
            inventory[path.as_posix()] = (_sha256(content), len(content))
        else:
            raise OSError(f"Completed directory contains non-regular path: {path}")
    return inventory


def _path_identity(path: Path) -> tuple[int, int]:
    status = path.stat(follow_symlinks=False)
    return status.st_dev, status.st_ino


def _descriptor_identity(descriptor: int) -> tuple[int, int]:
    status = os.fstat(descriptor)
    return status.st_dev, status.st_ino


def _has_identity(path: Path, identity: tuple[int, int]) -> bool:
    try:
        return _path_identity(path) == identity
    except FileNotFoundError:
        return False


def _require_identity(path: Path, identity: tuple[int, int], message: str) -> None:
    if not _has_identity(path, identity):
        raise OSError(message)


def _require_public_identity(
    target: Path,
    identity: tuple[int, int],
    *,
    preferred_quarantine: Path | None = None,
) -> None:
    if _has_identity(target, identity):
        return
    _preserve_public_replacement(target, preferred=preferred_quarantine)
    raise OSError(f"Publication destination changed during publication: {target}")


def _preserve_public_replacement(
    target: Path, *, preferred: Path | None = None
) -> Path | None:
    destinations = []
    if preferred is not None:
        destinations.append(preferred)
    destinations.append(
        target.with_name(f".{target.name}.quarantine-{secrets.token_hex(16)}")
    )
    for destination in destinations:
        try:
            _native_rename_no_replace(target, destination)
        except FileNotFoundError:
            return None
        except FileExistsError:
            continue
        return destination
    return None


def _quarantine_owned_directory(target: Path, identity: tuple[int, int]) -> Path | None:
    quarantine = target.with_name(f".{target.name}.quarantine-{secrets.token_hex(16)}")
    try:
        _native_rename_no_replace(target, quarantine)
    except FileNotFoundError:
        return None
    if _has_identity(quarantine, identity):
        return quarantine
    with contextlib.suppress(FileExistsError):
        _native_rename_no_replace(quarantine, target)
    return None


def _remove_owned_staging(
    staging: Path,
    identity: tuple[int, int],
    *,
    directory: bool,
) -> None:
    quarantine = staging.with_name(f".{staging.name}.cleanup-{secrets.token_hex(16)}")
    try:
        _native_rename_no_replace(staging, quarantine)
    except FileNotFoundError:
        return
    if not _has_identity(quarantine, identity):
        _native_rename_no_replace(quarantine, staging)
        return
    if directory:
        shutil.rmtree(quarantine)
    else:
        quarantine.unlink()


def _rename_no_replace(source: Path, destination: Path) -> None:
    _native_rename_no_replace(source, destination)


def _native_rename_no_replace(source: Path, destination: Path) -> None:
    platform = _publication_platform()
    if platform == "windows":
        _windows_rename_no_replace(source, destination)
        return
    if platform == "linux":
        _linux_rename_no_replace(source, destination)
        return
    if platform == "darwin":
        _darwin_rename_no_replace(source, destination)
        return
    raise OSError(
        errno.ENOTSUP,
        "Atomic no-replace directory publication is not supported",
        os.fspath(destination),
    )


def _windows_rename_no_replace(source: Path, destination: Path) -> None:
    win_dll = ctypes.WinDLL
    kernel32 = win_dll("kernel32", use_last_error=True)
    move_file = kernel32.MoveFileExW
    move_file.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint)
    move_file.restype = ctypes.c_int
    if move_file(os.fspath(source), os.fspath(destination), 0):
        return
    error_number = ctypes.get_last_error()
    if error_number in {80, 183} or destination.exists(follow_symlinks=False):
        raise FileExistsError(
            error_number,
            "Publication destination already exists",
            os.fspath(destination),
        )
    raise OSError(
        error_number,
        "Windows no-replace rename failed",
        os.fspath(destination),
    )


def _linux_rename_no_replace(source: Path, destination: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        renameat2 = libc.renameat2
    except AttributeError as error:
        raise OSError(
            errno.ENOTSUP,
            "Atomic no-replace directory publication is not supported",
            os.fspath(destination),
        ) from error
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    result = renameat2(
        -100,
        os.fsencode(source),
        -100,
        os.fsencode(destination),
        1,
    )
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(
            error_number,
            os.strerror(error_number),
            os.fspath(destination),
        )


def _darwin_rename_no_replace(source: Path, destination: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        rename_exclusive = libc.renamex_np
    except AttributeError as error:
        raise OSError(
            errno.ENOTSUP,
            "Atomic no-replace directory publication is not supported",
            os.fspath(destination),
        ) from error
    rename_exclusive.argtypes = (
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    rename_exclusive.restype = ctypes.c_int
    result = rename_exclusive(
        os.fsencode(source),
        os.fsencode(destination),
        0x00000004,
    )
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(
            error_number,
            os.strerror(error_number),
            os.fspath(destination),
        )


def _archive_bytes(files: tuple[PublishedFile, ...]) -> bytes:
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        for file in files:
            info = ZipInfo(file.path, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, file.content, compresslevel=9)
    return output.getvalue()


def _publication(
    kind: str,
    target: Path,
    files: tuple[PublishedFile, ...],
    output_sha256: str | None = None,
) -> JsonDict:
    manifest = next(file for file in files if file.path == "goldilocks.json")
    return {
        "kind": kind,
        "path": str(target.resolve()),
        "files": [file.path for file in files],
        "manifest_sha256": manifest.sha256,
        "output_sha256": output_sha256,
    }


def _verify_directory(root: Path, files: tuple[PublishedFile, ...]) -> None:
    descriptor = os.open(
        root,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        _verify_directory_descriptor(descriptor, files)
    finally:
        os.close(descriptor)


def _add(
    files: dict[str, tuple[bytes, str]], path: str, content: bytes, role: str
) -> None:
    _validate_publication_path(path)
    if path in files:
        raise ValueError(f"Duplicate publication path: {path!r}")
    files[path] = (content, role)


def _validate_publication_path(path: str) -> None:
    if not isinstance(path, str) or not path:
        raise ValueError(f"Unsafe publication path: {path!r}")
    candidate = PurePosixPath(path)
    if (
        "\\" in path
        or any(unicodedata.category(character) == "Cc" for character in path)
        or candidate.is_absolute()
        or any(part in {"", ".", ".."} for part in path.split("/"))
        or candidate.as_posix() != path
    ):
        raise ValueError(f"Unsafe publication path: {path!r}")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _citations(input_data: JsonDict) -> str:
    entries = "".join(f"- {citation}\n" for citation in input_data["citations"])
    return (
        "# Citations\n\n"
        "Goldilocks records complete provenance in `goldilocks.json`. Cite the "
        "selected pseudopotential and model sources when publishing results.\n\n"
        f"{entries}"
    )


def _readme(input_data: JsonDict) -> str:
    source_path = next(
        artifact["path"]
        for artifact in input_data["artifacts"]
        if artifact["role"] == "structure_source"
    )
    return (
        "# Goldilocks DFT Input Data\n\n"
        "Run Quantum ESPRESSO from this output root, for example "
        "`pw.x -in inputs/qe.in`, so `pseudo_dir = './pseudo'` resolves to the "
        "published UPFs.\n\n"
        f"- Structure Source: `{source_path}`\n"
        "- Canonical Structure: `structure/canonical.cif`\n"
        "- Generated inputs: `inputs/`\n"
        "- Exact selected pseudopotentials: `pseudo/`\n"
        "- Licence material: `licences/`\n"
        "- Machine-readable provenance: `goldilocks.json`\n"
        "- Independent file hashes: `checksums.sha256`\n"
    )
