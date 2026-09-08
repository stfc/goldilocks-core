from __future__ import annotations

import ctypes
import errno
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unicodedata
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from goldilocks_core.contracts import (
    DftInputData,
    DirectoryOutput,
    InputArtifact,
    OutputTarget,
    Publication,
)


class Publisher:
    """Publish assembled input files through staging and atomic installation.

    The destination parent is operator-controlled; private staging is trusted.
    Existing destinations, including concurrent publications, are never replaced.
    """

    def files(self, input_data: DftInputData) -> tuple[InputArtifact, ...]:
        files: dict[str, tuple[bytes, str]] = {}
        for artifact in input_data.artifacts:
            _add(files, artifact.path, artifact.content, artifact.role)

        _add(
            files,
            "CITATIONS.md",
            _citations(input_data).encode("utf-8"),
            "citations",
        )
        _add(files, "README.md", _readme(input_data).encode("utf-8"), "readme")
        manifest = {
            "schema_version": 1,
            **input_data.manifest,
            "files": {
                path: {
                    "role": role,
                    "sha256": hashlib.sha256(content).hexdigest(),
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
        return tuple(
            InputArtifact(path=path, role=role, content=content)
            for path, (content, role) in sorted(files.items())
        )

    def publish(self, input_data: DftInputData, output: OutputTarget) -> Publication:
        files = self.files(input_data)
        if isinstance(output, DirectoryOutput):
            if output.path is None:
                return self._publish_automatic_directory(files)
            return self._publish_directory(files, Path(output.path))
        return self._publish_archive(files, Path(output.path))

    def archive_bytes(self, input_data: DftInputData) -> bytes:
        return _archive_bytes(self.files(input_data))

    def _publish_automatic_directory(
        self, files: tuple[InputArtifact, ...]
    ) -> Publication:
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
        self, files: tuple[InputArtifact, ...], destination: Path
    ) -> Publication:
        target = destination.expanduser().absolute()
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
        installed = False
        try:
            _write_directory_path(staging, files)
            _rename_no_replace(staging, target)
            installed = True
        finally:
            if not installed:
                shutil.rmtree(staging)
        return _publication("directory", target, files)

    def _publish_archive(
        self,
        files: tuple[InputArtifact, ...],
        destination: Path,
    ) -> Publication:
        target = destination.expanduser().absolute()
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, staging_name = tempfile.mkstemp(
            prefix=f".{target.name}.", dir=target.parent
        )
        staging = Path(staging_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(_archive_bytes(files))
            _rename_no_replace(staging, target)
        finally:
            staging.unlink(missing_ok=True)
        return _publication("archive", target, files)


def _write_directory_path(root: Path, files: tuple[InputArtifact, ...]) -> None:
    for file in files:
        output = root.joinpath(*PurePosixPath(file.path).parts)
        output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with output.open("xb") as stream:
            stream.write(file.content)


def _rename_no_replace(source: Path, destination: Path) -> None:
    if os.name == "nt":
        os.rename(source, destination)
        return
    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes, destination_bytes = os.fsencode(source), os.fsencode(destination)
    try:
        if sys.platform.startswith("linux"):
            rename = libc.renameat2
            rename.argtypes = (
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            )
            arguments = (-100, source_bytes, -100, destination_bytes, 1)
        elif sys.platform == "darwin":
            rename = libc.renamex_np
            rename.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
            arguments = (source_bytes, destination_bytes, 0x00000004)
        else:
            raise OSError(
                errno.ENOTSUP, "Atomic no-replace publication is not supported"
            )
    except AttributeError as error:
        raise OSError(
            errno.ENOTSUP, "Atomic no-replace publication is not supported"
        ) from error
    rename.restype = ctypes.c_int
    if rename(*arguments) != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), os.fspath(destination))


def _archive_bytes(files: tuple[InputArtifact, ...]) -> bytes:
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
    files: tuple[InputArtifact, ...],
) -> Publication:
    return Publication(
        kind=kind,
        path=str(target.resolve()),
        files=tuple(file.path for file in files),
    )


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
        or ":" in path
        or any(unicodedata.category(character) == "Cc" for character in path)
        or candidate.is_absolute()
        or any(part in {"", ".", ".."} for part in path.split("/"))
        or candidate.as_posix() != path
    ):
        raise ValueError(f"Unsafe publication path: {path!r}")


def _citations(input_data: DftInputData) -> str:
    entries = "".join(f"- {citation}\n" for citation in input_data.citations)
    return (
        "# Citations\n\n"
        "Goldilocks records complete provenance in `goldilocks.json`. Cite the "
        "selected pseudopotential and model sources when publishing results.\n\n"
        f"{entries}"
    )


def _readme(input_data: DftInputData) -> str:
    source_path = next(
        artifact.path
        for artifact in input_data.artifacts
        if artifact.role == "structure_source"
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
    )
