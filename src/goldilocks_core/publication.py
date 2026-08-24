from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from goldilocks_core.assets import AssetStore
from goldilocks_core.contracts import (
    DftInputData,
    DirectoryOutput,
    GeneratedContent,
    InputArtifact,
    OutputTarget,
    Publication,
)


@dataclass(frozen=True, slots=True)
class PublishedFile:
    path: str
    content: bytes
    role: str
    sha256: str


class Publisher:
    def __init__(self, asset_store: AssetStore | None = None) -> None:
        self._asset_store = asset_store

    def files(self, input_data: DftInputData) -> tuple[PublishedFile, ...]:
        files: dict[str, tuple[bytes, str]] = {}
        for artifact in input_data.artifacts:
            _validate_publication_path(artifact.path)
            _add(files, artifact.path, self._content(artifact), artifact.role)

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
        self, files: tuple[PublishedFile, ...]
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
        self, files: tuple[PublishedFile, ...], destination: Path
    ) -> Publication:
        target = destination.expanduser().absolute()
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.mkdir()
        except FileExistsError as error:
            raise FileExistsError(
                f"Publication destination already exists: {target}"
            ) from error

        staging: Path | None = None
        try:
            staging = Path(
                tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent)
            )
            for file in files:
                path = staging.joinpath(*PurePosixPath(file.path).parts)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(file.content)
            _verify_directory(staging, files)
            os.replace(staging, target)
            _verify_directory(target, files)
        except BaseException:
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)
            shutil.rmtree(target, ignore_errors=True)
            raise
        return _publication("directory", target, files)

    def _publish_archive(
        self,
        files: tuple[PublishedFile, ...],
        destination: Path,
    ) -> Publication:
        target = destination.expanduser().absolute()
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.open("xb").close()
        except FileExistsError as error:
            raise FileExistsError(
                f"Publication destination already exists: {target}"
            ) from error
        staging: Path | None = None
        try:
            descriptor, staging_name = tempfile.mkstemp(
                prefix=f".{target.name}.", dir=target.parent
            )
            os.close(descriptor)
            staging = Path(staging_name)
            payload = _archive_bytes(files)
            staging.write_bytes(payload)
            if staging.read_bytes() != payload:
                raise OSError(f"Completed archive write differs: {staging}")
            os.replace(staging, target)
            if _sha256(target.read_bytes()) != _sha256(payload):
                raise OSError(f"Published archive checksum differs: {target}")
        except BaseException:
            if staging is not None:
                staging.unlink(missing_ok=True)
            try:
                target.unlink()
            except OSError:
                pass
            raise
        return _publication("archive", target, files, _sha256(payload))

    def _content(self, artifact: InputArtifact) -> bytes:
        source = artifact.source
        if isinstance(source, GeneratedContent):
            payload = source.content
        else:
            if self._asset_store is None:
                raise ValueError(
                    "An AssetStore is required to publish installed artifact references"
                )
            installed = self._asset_store.verify(
                source.asset_id,
                source.asset_version,
                preparation_fingerprint=source.preparation_fingerprint,
            )
            payload = installed.path(source.path).read_bytes()
        if len(payload) != artifact.size_bytes or _sha256(payload) != artifact.sha256:
            raise ValueError(
                f"Artifact {artifact.path!r} differs from its DFT Input Data descriptor"
            )
        return payload


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
) -> Publication:
    manifest = next(file for file in files if file.path == "goldilocks.json")
    return Publication(
        kind=kind,
        path=str(target.resolve()),
        files=tuple(file.path for file in files),
        manifest_sha256=manifest.sha256,
        output_sha256=output_sha256,
    )


def _verify_directory(root: Path, files: tuple[PublishedFile, ...]) -> None:
    actual = {
        path.relative_to(root).as_posix(): (
            _sha256(path.read_bytes()),
            path.stat().st_size,
        )
        for path in root.rglob("*")
        if path.is_file()
    }
    expected = {file.path: (file.sha256, len(file.content)) for file in files}
    if actual != expected:
        raise OSError(f"Completed directory write differs: {root}")


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
        "- Independent file hashes: `checksums.sha256`\n"
    )
