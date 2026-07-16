"""Shared request/structure deserialization for Core transports.

Used by the HTTP server and intended for reuse by the sibling MCP server. This
module owns the transport-specific parts of a request body:

- structure input: inline CIF/POSCAR text or an allowlisted server-side path;
- server-side path resolution against configured roots with confinement that
  rejects symlink components and traversal escapes;
- bundle ``output_dir`` resolution against a configured bundle root, confined
  the same way.

JSON->dataclass conversion for ``CalculationIntent``, ``CalculationHints``,
``CoreJobRequest``, and ``PseudoMetadata`` is delegated to the ``from_dict``
constructors on the Core contracts. This module defines no duplicate schema and
no compatibility shims. It does not load models, run jobs, or touch the network.

Boundary: this is a transport-only deserializer. No auth, sessions, queues,
persistence, WebSockets, pods, or execution live here.
"""

from __future__ import annotations

import errno
import os
import stat
import unicodedata
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING

from pymatgen.core import Structure

from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    CoreJobRequest,
    JobMode,
    PseudoMetadata,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "ConfinedAccessFailure",
    "RequestError",
    "parse_core_job_request",
    "resolve_structure",
]

# Read chunks of up to 1 MiB when draining a confined structure-file descriptor.
_READ_CHUNK = 1 << 20

# Request-body fields allowed at the top level, per endpoint mode. ``mode`` is
# never accepted: the transport (endpoint or tool) selects it. ``output_dir`` is
# only accepted for ``bundle``.
_STRUCTURE_FIELDS: frozenset[str] = frozenset(
    {"structure", "intent", "hints", "pseudo_metadata"}
)
_STRUCTURE_FORMATS: tuple[str, ...] = ("cif", "poscar")
_POSCAR_SUFFIXES: frozenset[str] = frozenset(
    {".poscar", ".vasp", ".concar", ".fmt", ".struct"}
)
# Structure sub-schema: exactly one variant. ``content`` carries inline text
# with an optional ``format``; ``path`` carries a server-side path resolved by
# suffix. ``format`` is rejected alongside ``path`` (the suffix governs).
_STRUCTURE_CONTENT_KEYS: frozenset[str] = frozenset({"content", "format"})
_STRUCTURE_PATH_KEYS: frozenset[str] = frozenset({"path"})
_STRUCTURE_ALLOWED_KEYS: frozenset[str] = _STRUCTURE_CONTENT_KEYS | _STRUCTURE_PATH_KEYS


class RequestError(ValueError):
    """Invalid transport request, mapped to a deterministic 4xx response.

    Attributes:
        kind: error kind for the response body. ``invalid_request`` maps to
            422; ``not_found`` maps to 404.
        message: human-readable detail carried in the response body.
    """

    def __init__(self, kind: str, message: str) -> None:
        """Store the kind and message; remain a ValueError subclass."""
        super().__init__(message)
        self.kind = kind
        self.message = message


class ConfinedAccessFailure(Exception):
    """Server-side filesystem failure during confined path resolution.

    Raised in place of ``RequestError`` when an ``os.open``/``fstat``/``read``
    on a confined path fails with an error that is not a genuine client path
    condition (e.g. ``EACCES``, ``EMFILE``, ``EIO``). These are server-side
    filesystem failures, not malformed requests, so they map to a redacted 500
    without leaking host paths. This is not a ``ValueError`` subclass so the
    generic ``Exception`` handler redacts it rather than the ``ValueError``
    handler echoing its message.
    """


def parse_core_job_request(
    body: object,
    *,
    mode: JobMode,
    structure_root: Path | None,
    bundle_root: Path | None,
    default_pseudo_metadata: Sequence[PseudoMetadata] = (),
) -> CoreJobRequest:
    """Parse a transport request body into a validated ``CoreJobRequest``.

    The body is the JSON object accepted by the HTTP/MCP transports:

    - ``structure`` (required): ``{"content": str, "format": "cif"|"poscar"}``
      for inline text, or ``{"path": str}`` for an allowlisted server-side path.
    - ``intent`` (optional): ``CalculationIntent.from_dict`` payload.
    - ``hints`` (optional): ``CalculationHints.from_dict`` payload.
    - ``pseudo_metadata`` (optional): list of ``PseudoMetadata.from_dict``
      payloads. Overrides the configured default when present.
    - ``output_dir`` (required for ``bundle``): relative path resolved against
      ``bundle_root``.

    The endpoint selects ``mode``; the body must not carry ``mode``. Unknown
    top-level fields and ``output_dir`` on non-bundle endpoints are rejected so
    typos and wrong-endpoint fields cannot silently change behavior.

    Args:
        body: Parsed JSON object.
        mode: Pipeline mode selected by the transport (endpoint or tool).
        structure_root: Allowlist root for server-side structure paths. When
            ``None``, only inline structure content is accepted.
        bundle_root: Root for bundle ``output_dir`` resolution. Required when
            ``mode`` is ``bundle``.
        default_pseudo_metadata: Pseudopotential metadata loaded once from a
            configured root. Used when the body supplies none.

    Raises:
        RequestError: With ``kind`` set for HTTP status mapping.

    Returns:
        A validated ``CoreJobRequest`` ready for ``CoreRuntime.run``.
    """
    if not isinstance(body, dict):
        raise RequestError("invalid_request", "Request body must be a JSON object.")

    _reject_unknown_top_level(body, mode=mode)

    if "structure" not in body:
        raise RequestError("invalid_request", "Request body requires 'structure'.")

    structure = resolve_structure(body["structure"], structure_root=structure_root)

    try:
        intent = (
            CalculationIntent.from_dict(body["intent"])
            if "intent" in body
            else CalculationIntent()
        )
        hints = (
            CalculationHints.from_dict(body["hints"])
            if "hints" in body
            else CalculationHints()
        )
    except ValueError as error:
        raise RequestError("invalid_request", str(error)) from error

    pseudo_metadata = _resolve_pseudo_metadata(body, default_pseudo_metadata)

    output_dir = _resolve_output_dir(body, mode=mode, bundle_root=bundle_root)

    return CoreJobRequest(
        structure=structure,
        intent=intent,
        hints=hints,
        mode=mode,
        pseudo_metadata=pseudo_metadata,
        output_dir=output_dir,
    )


def resolve_structure(
    structure_field: object,
    *,
    structure_root: Path | None,
) -> Structure:
    """Resolve a transport structure field into a loaded pymatgen Structure.

    Accepts ``{"content": str, "format": "cif"|"poscar"|None}`` for inline text
    or ``{"path": str}`` for an allowlisted server-side path. The structure
    sub-schema is strict: unknown keys are rejected, exactly one of
    ``content`` or ``path`` is required (not both), and ``format`` is only
    accepted with inline ``content``. Server-side paths are confined to
    ``structure_root``: the path must be relative, must not contain ``..``
    traversal or embedded NUL/control characters, and no existing component may
    be a symlink or special file. Files are read through a descriptor walk that
    is free of the TOCTOU race a string-based ``lstat``/``realpath`` check
    would have. Missing files map to ``not_found``; unparseable content or files
    map to ``invalid_request``.
    """
    if not isinstance(structure_field, dict):
        raise RequestError(
            "invalid_request",
            "structure must be an object with 'content' or 'path'.",
        )

    unknown = sorted(set(structure_field) - _STRUCTURE_ALLOWED_KEYS)
    if unknown:
        raise RequestError(
            "invalid_request",
            f"Unknown structure keys: {', '.join(unknown)}",
        )

    has_content = "content" in structure_field
    has_path = "path" in structure_field
    if has_content and has_path:
        raise RequestError(
            "invalid_request",
            "structure must specify exactly one of 'content' or 'path'.",
        )
    if not has_content and not has_path:
        raise RequestError(
            "invalid_request", "structure must have 'content' or 'path'."
        )

    if has_content:
        return _parse_structure_content(structure_field)

    if "format" in structure_field and structure_field["format"] is not None:
        raise RequestError(
            "invalid_request",
            "structure.format is not valid with structure.path.",
        )
    return _load_structure_path(structure_field, structure_root=structure_root)


def _reject_unknown_top_level(body: dict[str, object], *, mode: JobMode) -> None:
    """Reject body fields not permitted for this endpoint.

    ``mode`` is never permitted (the transport selects it). ``output_dir`` is
    only permitted for ``bundle``. Everything outside the per-mode allowlist is
    rejected so typos and wrong-endpoint fields surface as 422 rather than
    silently changing behavior.
    """
    allowed = set(_STRUCTURE_FIELDS)
    if mode == "bundle":
        allowed.add("output_dir")
    unknown = sorted(set(body) - allowed)
    if unknown:
        raise RequestError(
            "invalid_request",
            f"Unknown request fields for {mode}: {', '.join(unknown)}",
        )


def _parse_structure_content(structure_field: dict[str, object]) -> Structure:
    """Parse inline CIF/POSCAR text into a Structure."""
    content = structure_field["content"]
    if not isinstance(content, str) or not content.strip():
        raise RequestError(
            "invalid_request", "structure.content must be a non-empty string."
        )

    requested = structure_field.get("format")
    formats: tuple[str, ...]
    if requested is None:
        formats = _STRUCTURE_FORMATS
    else:
        if (
            not isinstance(requested, str)
            or requested.lower() not in _STRUCTURE_FORMATS
        ):
            raise RequestError(
                "invalid_request",
                f"structure.format must be one of {list(_STRUCTURE_FORMATS)} or null.",
            )
        formats = (requested.lower(),)

    return _parse_structure_text(content, formats, "structure content")


def _parse_structure_text(
    content: str,
    formats: tuple[str, ...],
    source: str,
) -> Structure:
    """Try each format and map every failure to a single invalid_request."""
    last_error: Exception | None = None
    for fmt in formats:
        try:
            return Structure.from_str(content, fmt=fmt)
        except Exception as error:  # noqa: BLE001 - surface a single message
            last_error = error
    raise RequestError(
        "invalid_request",
        f"Could not parse {source}: {last_error}",
    )


def _load_structure_path(
    structure_field: dict[str, object],
    *,
    structure_root: Path | None,
) -> Structure:
    """Load a structure from a confined allowlisted server-side path.

    The path is resolved under ``structure_root`` and read through a
    descriptor walk that rejects symlink components and traversal escapes
    without a TOCTOU window. The file content is parsed with a format derived
    from the file suffix, falling back to CIF then POSCAR.
    """
    path_value = structure_field["path"]
    parts = _validate_relative_parts(path_value, field_name="structure.path")

    if structure_root is None:
        raise RequestError(
            "invalid_request",
            "structure.path requires a configured server root.",
        )

    content = _read_confined_file(structure_root, parts, field_name="structure.path")
    formats = _formats_for_suffix(parts[-1])
    return _parse_structure_text(
        content.decode("utf-8", errors="replace"),
        formats,
        f"structure file {path_value!r}",
    )


def _formats_for_suffix(component: str) -> tuple[str, ...]:
    """Return candidate parse formats ordered by the file suffix."""
    suffix = PurePosixPath(component).suffix.lower()
    if suffix == ".cif":
        return ("cif",)
    if suffix in _POSCAR_SUFFIXES:
        return ("poscar",)
    return _STRUCTURE_FORMATS


def _resolve_output_dir(
    body: dict[str, object],
    *,
    mode: JobMode,
    bundle_root: Path | None,
) -> str | None:
    """Resolve bundle ``output_dir`` to a confined canonical absolute path."""
    if mode != "bundle":
        return None

    output_dir = body.get("output_dir")
    parts = _validate_relative_parts(output_dir, field_name="output_dir")

    if bundle_root is None:
        raise RequestError(
            "invalid_request",
            "output_dir requires a configured bundle root.",
        )

    resolved = _confined_destination_path(bundle_root, parts, field_name="output_dir")
    return str(resolved)


def _resolve_pseudo_metadata(
    body: dict[str, object],
    default_pseudo_metadata: Sequence[PseudoMetadata],
) -> tuple[PseudoMetadata, ...]:
    """Return per-request pseudo metadata, falling back to the configured default."""
    if "pseudo_metadata" not in body:
        return tuple(default_pseudo_metadata)

    entries = body["pseudo_metadata"]
    if not isinstance(entries, list):
        raise RequestError("invalid_request", "pseudo_metadata must be a list.")

    parsed: list[PseudoMetadata] = []
    for entry in entries:
        try:
            parsed.append(PseudoMetadata.from_dict(entry))
        except ValueError as error:
            raise RequestError("invalid_request", str(error)) from error
    return tuple(parsed)


def _is_disallowed_path_char(char: str) -> bool:
    """Return True for Unicode control/format/surrogate code points.

    Covers ASCII C0 controls (``U+0000``-``U+001F``), DEL (``U+007F``), C1
    controls (``U+0080``-``U+009F``, notably ``U+0085``), format characters
    (general category ``Cf``: bidi/ZWJ/ZWNJ/BOM marks), and surrogate code
    points (``Cs``, including lone surrogates that would later raise
    ``UnicodeEncodeError`` at ``os.open``). These are unsafe or invisible in
    filesystem paths and are rejected before any OS call.
    """
    return unicodedata.category(char) in {"Cc", "Cf", "Cs"}


def _validate_relative_parts(value: object, *, field_name: str) -> tuple[str, ...]:
    """Validate a relative path lexically and return its POSIX components.

    Rejects non-strings, absolute paths, ``.``-only paths, and any ``..``
    traversal component. Rejects every Unicode control, format, and surrogate
    code point (general categories ``Cc``, ``Cf``, ``Cs``) — ASCII C0
    controls and DEL, C1 controls (notably ``U+0085`` NEXT LINE), bidi/format
    marks, and lone surrogates — before any filesystem call, so they surface as
    a deterministic 422 rather than a stage error or ``UnicodeEncodeError``.
    Symlink components are rejected later by the confined descriptor walk, which
    is the TOCTOU-free check; this lexical pass keeps clear, deterministic
    messages for the common malformed cases.
    """
    if not isinstance(value, str) or not value.strip():
        raise RequestError(
            "invalid_request", f"{field_name} must be a non-empty relative path."
        )

    if any(_is_disallowed_path_char(char) for char in value):
        raise RequestError(
            "invalid_request",
            f"{field_name} must not contain control, format, or surrogate characters.",
        )

    posix_path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if posix_path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise RequestError(
            "invalid_request", f"{field_name} must be relative; got {value!r}"
        )
    if not posix_path.parts or posix_path == PurePosixPath("."):
        raise RequestError(
            "invalid_request", f"{field_name} must identify a location; got {value!r}"
        )
    if ".." in posix_path.parts or ".." in windows_path.parts:
        raise RequestError(
            "invalid_request",
            f"{field_name} must not contain '..' traversal; got {value!r}",
        )

    return tuple(posix_path.parts)


def _read_confined_file(
    root: Path,
    parts: tuple[str, ...],
    *,
    field_name: str,
) -> bytes:
    """Read a file under ``root`` without following any symlink component.

    Walks each component relative to the previous directory descriptor. Each
    intermediate component is opened with
    ``O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_DIRECTORY``: ``O_DIRECTORY`` makes
    the kernel refuse a non-directory (FIFO, device, socket, regular file) with
    ``ENOTDIR`` before its driver ``open`` path runs, ``O_NOFOLLOW`` ensures
    a symlink component is never followed, and the resulting ``ENOTDIR`` is
    classified as a symlink or non-directory component via a non-following stat.
    ``O_NONBLOCK`` keeps the (now kernel-refused) special-file open non-blocking.
    The final component is opened with ``O_RDONLY | O_NOFOLLOW | O_NONBLOCK`` (no
    ``O_DIRECTORY``; the leaf is a file) and ``fstat`` requires a regular file,
    so a FIFO/device/socket at the leaf cannot block the worker in ``os.open``. The
    descriptor-based walk has no string-path re-resolution between the check and
    the read, eliminating the TOCTOU race a ``realpath``/``lstat``-based check
    would have. Every opened descriptor is closed even if ``fstat`` or ``read``
    raises.
    """
    if os.name != "posix":
        raise RequestError(
            "invalid_request",
            f"{field_name} requires a POSIX host for confined server-side paths.",
        )
    display = "/".join(parts)
    root_fd = _open_root(root, field_name=field_name, display=display)
    dir_fds: list[int] = [root_fd]
    try:
        for index, part in enumerate(parts):
            is_last = index == len(parts) - 1
            parent = dir_fds[-1]
            if is_last:
                return _read_confined_final(
                    parent, part, field_name=field_name, display=display
                )
            try:
                child = os.open(
                    part,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_DIRECTORY,
                    dir_fd=parent,
                )
            except OSError as error:
                _raise_confined_oserror(
                    error,
                    field_name=field_name,
                    display=display,
                    parent_fd=parent,
                    part=part,
                )
            try:
                mode = os.fstat(child).st_mode
                if not stat.S_ISDIR(mode):
                    raise RequestError(
                        "invalid_request",
                        f"{field_name} contains a non-directory component: {display}",
                    )
                dir_fds.append(child)
            except BaseException:
                os.close(child)
                raise
        # pragma: no cover - parts is validated non-empty, so the loop returns.
        raise RequestError("invalid_request", f"{field_name} must identify a file.")
    finally:
        for descriptor in reversed(dir_fds):
            os.close(descriptor)


def _read_confined_final(
    parent_fd: int,
    part: str,
    *,
    field_name: str,
    display: str,
) -> bytes:
    """Open and read the final confined component, requiring a regular file.

    Opens with ``O_NOFOLLOW`` (rejects symlinks with ``ELOOP``) and
    ``O_NONBLOCK`` so a FIFO, device, or socket at the final component cannot
    block the worker in ``os.open``. ``fstat`` then requires a regular file;
    special files (FIFO/char/block/socket) map to ``invalid_request``. The
    descriptor is closed even if ``fstat`` or ``read`` raises.
    """
    try:
        child = os.open(
            part, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd
        )
    except OSError as error:
        _raise_confined_oserror(error, field_name=field_name, display=display)
    try:
        mode = os.fstat(child).st_mode
        if stat.S_ISDIR(mode):
            raise RequestError(
                "invalid_request", f"{field_name} is a directory, not a file."
            )
        if not stat.S_ISREG(mode):
            raise RequestError(
                "invalid_request",
                f"{field_name} must be a regular file: {display}",
            )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(child, _READ_CHUNK)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(child)


def _confined_destination_path(
    root: Path,
    parts: tuple[str, ...],
    *,
    field_name: str,
) -> Path:
    """Return a confined canonical destination path under ``root``.

    Walks existing components relative to ``root`` with
    ``open(O_NOFOLLOW | O_NONBLOCK | O_DIRECTORY)`` so ``O_NOFOLLOW`` never
    follows a symlink component and ``O_DIRECTORY`` makes the kernel refuse any
    non-directory (FIFO, device, socket, regular file, or symlink) with
    ``ENOTDIR`` before its driver ``open`` path runs; the resulting ``ENOTDIR``
    is classified as a symlink or non-directory component via a non-following
    stat. ``O_NONBLOCK`` keeps the (now kernel-refused) special-file open
    non-blocking. The walk stops at the first non-existent component; the
    bundle stage creates the remainder. Because no existing component is a
    symlink and ``root`` is canonical, ``root / parts`` is the canonical
    destination. The bundle stage's atomic ``renameat2(RENAME_NOREPLACE)``
    publication then refuses any final component that appears (including a
    symlink) between this check and publication, so nothing is written outside
    ``root`` absent concurrent mutation of the operator-controlled root (see
    the HTTP security docs).
    """
    if os.name != "posix":
        raise RequestError(
            "invalid_request",
            f"{field_name} requires a POSIX host for confined bundle paths.",
        )
    display = "/".join(parts)
    try:
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    except OSError as error:
        if error.errno == errno.ENOENT:
            # The root does not exist yet; the bundle stage creates it fresh, so
            # no symlink can be traversed. Return the canonical join for the stage.
            return root.joinpath(*parts)
        if error.errno == errno.ENOTDIR:
            raise RequestError(
                "invalid_request",
                f"{field_name} requires a configured root that is a directory.",
            ) from error
        raise ConfinedAccessFailure from error
    dir_fds: list[int] = [root_fd]
    try:
        for part in parts:
            parent = dir_fds[-1]
            try:
                child = os.open(
                    part,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_DIRECTORY,
                    dir_fd=parent,
                )
            except OSError as error:
                if error.errno == errno.ENOENT:
                    # The rest of the path does not exist yet; the bundle stage
                    # creates it under the verified parent. No symlink can be
                    # traversed because there is nothing to traverse.
                    break
                _raise_confined_oserror(
                    error,
                    field_name=field_name,
                    display=display,
                    parent_fd=parent,
                    part=part,
                )
            try:
                mode = os.fstat(child).st_mode
                if not stat.S_ISDIR(mode):
                    raise RequestError(
                        "invalid_request",
                        f"{field_name} contains a non-directory component: {display}",
                    )
                dir_fds.append(child)
            except BaseException:
                os.close(child)
                raise
        return root.joinpath(*parts)
    finally:
        for descriptor in reversed(dir_fds):
            os.close(descriptor)


def _open_root(root: Path, *, field_name: str, display: str) -> int:
    """Open the configured root directory descriptor or raise a boundary error.

    ``ENOENT`` and ``ENOTDIR`` are genuine client-facing configuration errors
    (422). Any other failure (``EACCES``, ``EMFILE``, ``EIO``, ...) is a
    server-side filesystem failure mapped to a redacted 500.
    """
    try:
        return os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    except OSError as error:
        if error.errno == errno.ENOENT:
            raise RequestError(
                "invalid_request",
                f"{field_name} requires a configured root that exists.",
            ) from error
        if error.errno == errno.ENOTDIR:
            raise RequestError(
                "invalid_request",
                f"{field_name} requires a configured root that is a directory.",
            ) from error
        raise ConfinedAccessFailure from error


def _raise_confined_oserror(
    error: OSError,
    *,
    field_name: str,
    display: str,
    parent_fd: int | None = None,
    part: str | None = None,
) -> None:
    """Translate a confined-descriptor OSError into a deterministic boundary error.

    Genuine client path conditions map to a 4xx ``RequestError``: ``ENOENT``
    to ``not_found``, ``ELOOP`` to ``invalid_request`` (symlink component).
    ``ENOTDIR`` is reported as a symlink component when ``parent_fd``/``part``
    are supplied and the component is a symlink, otherwise as a non-directory
    component; with ``O_DIRECTORY`` the kernel returns ``ENOTDIR`` (rather than
    ``ELOOP``) for a symlink, so the non-following stat disambiguates the
    documented classification. The client-supplied relative ``display`` path is
    safe to echo. Any other error (``EACCES``, ``EMFILE``, ``EIO``, ...) is a
    server-side filesystem failure mapped to a redacted ``ConfinedAccessFailure``
    (500) without host paths.

    Always raises; never returns normally.
    """
    if error.errno == errno.ENOENT:
        raise RequestError("not_found", f"{field_name} not found: {display}") from error
    if error.errno == errno.ELOOP:
        raise RequestError(
            "invalid_request",
            f"{field_name} must not contain symlink components: {display}",
        ) from error
    if error.errno == errno.ENOTDIR:
        if (
            parent_fd is not None
            and part is not None
            and _is_symlink_component(parent_fd, part)
        ):
            raise RequestError(
                "invalid_request",
                f"{field_name} must not contain symlink components: {display}",
            ) from error
        raise RequestError(
            "invalid_request",
            f"{field_name} contains a non-directory component: {display}",
        ) from error
    if error.errno == errno.ENXIO:
        # A special file (e.g. a Unix socket) that cannot be opened for reading
        # is a client-supplied non-regular path, not a server filesystem failure.
        raise RequestError(
            "invalid_request",
            f"{field_name} must be a regular file: {display}",
        ) from error
    raise ConfinedAccessFailure from error


def _is_symlink_component(parent_fd: int, part: str) -> bool:
    """Return True if ``part`` under ``parent_fd`` is a symlink, without following.

    Uses a non-following ``stat`` relative to the held parent descriptor
    (``fstatat`` with ``AT_SYMLINK_NOFOLLOW``) purely to classify an ``ENOTDIR``
    from an ``O_DIRECTORY`` open; it never follows the link and never weakens the
    descriptor-walk confinement (the ``open`` already refused the component).
    """
    try:
        mode = os.stat(part, dir_fd=parent_fd, follow_symlinks=False).st_mode
    except OSError:
        return False
    return stat.S_ISLNK(mode)
