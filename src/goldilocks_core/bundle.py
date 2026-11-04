"""bundle: assemble and publish a self-contained result directory/archive.

New in v2 (v2 epic 7, #7). Per goldilocks-core-design.md S8's own port
table ("`input_data.py` / `publication.py` / `result.py` overlap three
ways -> merge into `generation/bundle.py`"), this module absorbs both
v1 roles: assembling the manifest (`input_data.py`) and writing it out
(`publication.py`). Lives top-level, not under `generation/`, matching
the design doc's own tree (S4.4: "`bundle.py` also moves to the top
level" -- it packages output for any code/task, not one code's input
files) -- ``pipeline.py``'s own sketch has exactly three top-level
calls, ``generation/`` -> ``submission/`` -> ``bundle.py``, one per
top-level package.

**Tri-state-aware manifest, replacing v1's all-or-nothing
``ManifestRecords``.** ``input_data.py``'s ``ManifestRecords``
(``analysis``/``advice``/``k_points``/``selection``/``generated_files``)
are all required ``TypedDict`` fields -- there is no way to represent
"most of this resolved, one field genuinely ``Unavailable``" (the tri
-state model epic 2 introduced). ``BundleInput.records`` is instead
``dict[str, FieldState[Any]]``: each named record is independently
``Resolved``/``Unavailable``/``Blocked``, projected into the manifest
through ``resolution.records_document`` -- the same projection every
transport's response uses. No real end-to-end pipeline produces a
partially-resolved set of records yet (epic 8's job); this is exercised
here with hand-built ``FieldState`` fixtures, the same standalone-testing
pattern every prior epic in this rewrite uses.

**Completion-marker protocol, replacing v1's ctypes atomic rename**
(goldilocks-core-design.md:4231-4274, "the three publish guarantees").
v1's ``_rename_no_replace`` (``publication.py:163-196``) used
``renameat2``/``renamex_np`` via raw ``ctypes`` to move a fully-written
staging directory into place without ever clobbering an existing
destination -- Linux/macOS only, ``OSError(ENOTSUP)`` everywhere else.
Replaced with:

1. **No overwrite**: ``target.mkdir()`` (directories) / exclusive
   ``open(path, "xb")`` (archives) -- both are atomic "claim the name"
   operations on POSIX with no check-then-act race window, raising
   ``FileExistsError`` outright if the destination already exists. No
   ``ctypes`` needed for this guarantee at all.
2. **No partial output survives a catchable failure**: any exception
   raised while writing is caught, the partially-written target is
   removed, then the exception is re-raised -- same behaviour v1's
   staging-directory approach gave for this case.
   **What changed, and was explicitly accepted (2026-09-14)**: a
   ``SIGKILL``/OOM-kill runs no exception handler at all, so a killed
   publish can leave real files behind at the final path with no
   ``.complete`` marker. v1's staging+rename made that scenario
   physically impossible (the destination simply would not exist yet);
   this protocol instead makes it a **consumer-side contract**:
   ``is_complete`` is the one function anything that reads a bundle
   must call before trusting it, and any directory/archive without the
   marker is exactly as untrustworthy as one that does not exist. The
   marker is written strictly last, after every byte is on disk.
3. **Exact validated bytes**: unchanged in spirit from v1 -- every
   artifact is hashed while assembling the manifest, and the same
   in-memory bytes (never re-read from their original source path) are
   what gets written and what the hash describes.

v1's three publication tests (``tests/integration/
test_input_data_publication.py``) are ported as this module's own
acceptance tests, adjusted for guarantee 2's new shape (checking for
the marker, not directory non-existence) -- the tests protect the
guarantees, not the mechanism underneath them.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, TypedDict
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from goldilocks_core.generation.files import InputArtifact
from goldilocks_core.resolution import (
    FieldState,
    collect_citations,
    records_document,
)
from goldilocks_core.serialization import to_portable

_COMPLETE_MARKER = ".complete"
_SCHEMA_VERSION = 3
_MANIFEST_KEYS = {
    "citations": "every citation the records carry, as `CITATIONS.md` lists them",
    "files": "the role, sha256 and size of every file in the bundle but "
    "`goldilocks.json` itself",
    "records": "every decision behind the input files, with its source and provenance",
    "request": "the request the bundle answers: code, task, HPC profile, the "
    "overrides as submitted, the input structure's name, format, sha256 and "
    "size, and the goldilocks-core version that answered it",
    "schema_version": "the layout version of `goldilocks.json`",
    "steps": "the task's steps in the order they run, each with the input files "
    "it reads",
    "warnings": "every warning raised while deciding the records, each naming "
    "the record it concerns",
}
"""What each top-level ``goldilocks.json`` key holds: ``README.md`` and
``CITATIONS.md`` describe the manifest from the keys it is written with,
through this table, so neither claims a key the manifest lacks (#176)."""
_CITATION_KEYS = ("citations", "records")


class Publication(TypedDict):
    kind: Literal["directory", "archive"]
    path: str
    files: list[str]


class StructureIdentity(TypedDict):
    """The input structure as submitted: ``inputs.structure``'s source
    document without its content. ``sha256``/``size_bytes`` are those of
    the submitted text, and ``None`` for a structure built in memory."""

    name: str
    format: str
    sha256: str | None
    size_bytes: int | None


@dataclass(frozen=True, slots=True)
class RequestIdentity:
    """The request a bundle answers, the manifest's ``request`` (#176):
    ``code``/``task``, the HPC profile its submission script was written
    for, the goldilocks-core version that answered it, the overrides as
    submitted (the assignments ``set_overrides.build_overrides`` received,
    ``steps.<step>.`` prefixes kept) and the input structure."""

    code: str
    task: str
    hpc: str
    core_version: str
    overrides: dict[str, object]
    structure: StructureIdentity


@dataclass(frozen=True, slots=True)
class BundleStep:
    """One step of the task, in run order: its name and the input files it
    reads, as the rendered ``steps.Step`` names them (#222)."""

    name: str
    files: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BundleInput:
    """Everything one calculation's published output needs -- content
    (``artifacts``), the facts/decisions behind it (``records``, tri
    -state), the warnings about them and the request it answers. Code and
    task are values of ``request``, not types: a QE bundle and a future
    VASP bundle both build one of these the same way.

    ``warnings`` is the list the transports return for the same advice
    (``advice.warnings()``, each tagged with its ``record``); the
    manifest carries it unchanged rather than collecting its own (#152).
    What to cite is read off the records themselves
    (``resolution.collect_citations``): the selected pseudopotential table
    and every model that decided a record (#156). ``request`` has no
    default, so no bundle is built without the request it answers (#176).
    ``steps`` are the task's steps in run order, from the same rendered steps
    as the input artifacts, so the manifest and ``README.md`` list the inputs
    in the order they run (#222). ``run_instructions`` is the ``README.md``
    section on running the bundle, which the submission script's renderer
    writes for the same job and steps (#227).
    """

    artifacts: tuple[InputArtifact, ...]
    steps: tuple[BundleStep, ...]
    run_instructions: str
    records: dict[str, FieldState[Any]]
    warnings: tuple[dict[str, object], ...]
    request: RequestIdentity


@dataclass(frozen=True, slots=True)
class DirectoryOutput:
    path: str | Path

    def __post_init__(self) -> None:
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


def bundle_files(bundle_input: BundleInput) -> tuple[InputArtifact, ...]:
    """Assemble every artifact, plus ``CITATIONS.md``/``README.md``/
    ``goldilocks.json``, hashing as it goes -- the exact bytes returned
    here are the exact bytes ``publish``/``archive_bytes`` write.

    ``goldilocks.json`` is strict JSON: a non-finite float in a record
    raises ``ValueError`` instead of being written as ``Infinity``/``NaN``,
    which strict parsers reject (#137)."""
    document = {
        "schema_version": _SCHEMA_VERSION,
        "request": to_portable(bundle_input.request),
        "records": records_document(bundle_input.records),
        "warnings": list(bundle_input.warnings),
        "citations": collect_citations(bundle_input.records),
        "steps": [
            {"name": step.name, "files": list(step.files)}
            for step in bundle_input.steps
        ],
    }
    keys = sorted((*document, "files"))
    files: dict[str, tuple[bytes, str]] = {}
    for artifact in bundle_input.artifacts:
        _add(files, artifact["path"], artifact["content"], artifact["role"])
    citations = _citations(bundle_input, keys)
    _add(files, "CITATIONS.md", citations.encode("utf-8"), "citations")
    _add(files, "README.md", _readme(bundle_input, keys).encode("utf-8"), "readme")

    manifest = {
        **document,
        "files": {
            path: {
                "role": role,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
            }
            for path, (content, role) in sorted(files.items())
        },
    }
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False)
    _add(files, "goldilocks.json", (manifest_text + "\n").encode("utf-8"), "manifest")
    return tuple(
        {"path": path, "role": role, "content": content}
        for path, (content, role) in sorted(files.items())
    )


def archive_bytes(bundle_input: BundleInput) -> bytes:
    return _archive_bytes(bundle_files(bundle_input))


def publish(bundle_input: BundleInput, output: OutputTarget) -> Publication:
    files = bundle_files(bundle_input)
    if isinstance(output, DirectoryOutput):
        return _publish_directory(files, Path(output.path))
    return _publish_archive(files, Path(output.path))


def is_complete(target: str | Path) -> bool:
    """Whether ``target`` (a published directory or archive) carries the
    completion marker. The one check anything consuming a bundle must
    make first -- an unmarked target is exactly as untrustworthy as one
    that does not exist at all, whether it is missing, mid-write, or
    the leftover of a killed publish."""
    path = Path(target)
    if path.is_dir():
        return (path / _COMPLETE_MARKER).is_file()
    return Path(f"{path}{_COMPLETE_MARKER}").is_file()


def _publish_directory(
    files: tuple[InputArtifact, ...], destination: Path
) -> Publication:
    target = destination.expanduser().absolute()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir(mode=0o700)
    try:
        _write_directory_path(target, files)
        (target / _COMPLETE_MARKER).touch()
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return _publication("directory", target, files)


def _write_directory_path(root: Path, files: tuple[InputArtifact, ...]) -> None:
    for file in files:
        output = root.joinpath(*PurePosixPath(file["path"]).parts)
        output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with output.open("xb") as stream:
            stream.write(file["content"])


def _publish_archive(
    files: tuple[InputArtifact, ...], destination: Path
) -> Publication:
    target = destination.expanduser().absolute()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = _archive_bytes(files)
    descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
        Path(f"{target}{_COMPLETE_MARKER}").touch()
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return _publication("archive", target, files)


def _archive_bytes(files: tuple[InputArtifact, ...]) -> bytes:
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        for file in files:
            info = ZipInfo(file["path"], date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, file["content"], compresslevel=9)
    return output.getvalue()


def _publication(
    kind: Literal["directory", "archive"],
    target: Path,
    files: tuple[InputArtifact, ...],
) -> Publication:
    return {
        "kind": kind,
        "path": str(target.resolve()),
        "files": [file["path"] for file in files],
    }


def _add(
    files: dict[str, tuple[bytes, str]], path: str, content: bytes, role: str
) -> None:
    _validate_publication_path(path)
    if path in files:
        raise ValueError(f"duplicate publication path: {path!r}")
    files[path] = (content, role)


def _validate_publication_path(path: str) -> None:
    if not isinstance(path, str) or not path:
        raise ValueError(f"unsafe publication path: {path!r}")
    candidate = PurePosixPath(path)
    if (
        "\\" in path
        or ":" in path
        or any(unicodedata.category(character) == "Cc" for character in path)
        or candidate.is_absolute()
        or any(part in {"", ".", ".."} for part in path.split("/"))
        or candidate.as_posix() != path
    ):
        raise ValueError(f"unsafe publication path: {path!r}")


def _manifest_lines(keys: Iterable[str]) -> str:
    """One Markdown list item per manifest key in ``keys``: what it holds
    (``_MANIFEST_KEYS``)."""
    return "".join(f"- `{key}`: {_MANIFEST_KEYS[key]}.\n" for key in keys)


def _contents(bundle_input: BundleInput) -> list[str]:
    run_order = {
        path: index
        for index, path in enumerate(
            path for step in bundle_input.steps for path in step.files
        )
    }

    def place(artifact: InputArtifact) -> tuple[int, int, str]:
        role = artifact["role"]
        rank = (
            _CONTENTS_ROLES.index(role)
            if role in _CONTENTS_ROLES
            else len(_CONTENTS_ROLES)
        )
        path = artifact["path"]
        return rank, run_order.get(path, len(run_order)), path

    return [artifact["path"] for artifact in sorted(bundle_input.artifacts, key=place)]


def _citations(bundle_input: BundleInput, keys: list[str]) -> str:
    """The records' citations, then each ``licence`` artifact: a table's
    licence material, which holds the per-family references the records do
    not cite (#157). Last, the manifest keys among ``keys`` (those
    ``goldilocks.json`` is written with) that hold the citations (#176)."""
    entries = "".join(
        f"- {citation}\n" for citation in collect_citations(bundle_input.records)
    )
    licences = "".join(
        f"- `{artifact['path']}`\n"
        for artifact in bundle_input.artifacts
        if artifact["role"] == "licence"
    )
    licence_section = (
        "\n## Licences\n\n"
        "Pseudopotentials keep their upstream licences. Each file below holds a "
        "table's licence material, with any per-family references to cite; read "
        "it before redistributing the pseudopotentials.\n\n"
        f"{licences}"
        if licences
        else ""
    )
    provenance = _manifest_lines(key for key in keys if key in _CITATION_KEYS)
    return (
        "# Citations\n\n"
        "Cite the selected pseudopotential and model sources when publishing "
        "results.\n\n"
        f"{entries}{licence_section}"
        "\n## Provenance\n\n"
        "`goldilocks.json` holds:\n\n"
        f"{provenance}"
    )


_CONTENTS_ROLES = ("input", "submission_script", "pseudopotential", "licence")
"""The order ``README.md`` lists the artifacts in, by role (#222)."""


def _readme(bundle_input: BundleInput, keys: list[str]) -> str:
    """What ``goldilocks.json`` holds, key by key for ``keys`` (those it is
    written with, #176), then every artifact path, by role in
    ``_CONTENTS_ROLES`` order, the inputs in the order their steps run and
    the rest by path (#222), then how to run it (#227). Names no code: the
    code is a value of the manifest's ``request``."""
    listing = "".join(f"- `{path}`\n" for path in _contents(bundle_input))
    return (
        "# Goldilocks DFT Input Data\n\n"
        "`goldilocks.json` holds:\n\n"
        f"{_manifest_lines(keys)}"
        "\n## Contents\n\n"
        f"{listing}"
        f"\n{bundle_input.run_instructions}"
    )
