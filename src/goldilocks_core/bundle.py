"""Bundle-stage portable directory output."""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import shutil
import sys
import tempfile
import warnings
from dataclasses import replace
from pathlib import Path, PurePosixPath, PureWindowsPath

from goldilocks_core.contracts import BundleRecord, CoreResult, JsonDict

MANIFEST_FILENAME = "manifest.json"
MANIFEST_VERSION = 1
_AT_FDCWD = -100
_RENAME_NOREPLACE = 1
_WINDOWS_RESERVED_COMPONENT_CHARACTERS = frozenset(
    {chr(codepoint) for codepoint in range(32)} | {'"', "*", ":", "<", ">", "?", "|"}
)
_WINDOWS_RESERVED_COMPONENT_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"COM{suffix}" for suffix in "123456789¹²³"}
    | {f"LPT{suffix}" for suffix in "123456789¹²³"}
)


def build_bundle_manifest(result: CoreResult) -> JsonDict:
    """Return a JSON-safe manifest for a Core output bundle.

    Args:
        result: Completed Core result, usually including generated files from
            Generate mode.

    Returns:
        Manifest dictionary with schema version, serialized intent, analysis,
        advice, selection, generated-file metadata, and warnings. Generated file
        content is not embedded.
    """
    files = []
    for generated_file in result.generated_files:
        content = generated_file.content.encode("utf-8")
        files.append(
            {
                "path": generated_file.path,
                "role": generated_file.role,
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )

    return {
        "manifest_version": MANIFEST_VERSION,
        "intent": result.intent.to_dict(),
        "analysis": result.analysis.to_dict(),
        "advice": result.advice.to_dict(),
        "selection": result.selection.to_dict(),
        "generated_files": files,
        "warnings": list(result.warnings),
    }


def write_bundle_directory(
    result: CoreResult,
    output_dir: str | Path,
) -> BundleRecord:
    """Publish generated files and a manifest as a new bundle directory.

    Args:
        result: Completed Core result with generated files to write.
        output_dir: New bundle root directory. Its parent directories are
            created if needed, but the bundle directory must not exist.

    Returns:
        ``BundleRecord`` with the output directory path and manifest.

    Raises:
        FileExistsError: If ``output_dir`` already exists.
        OSError: If staging, writing, or atomic publication fails. Staging
            cleanup or probe failures are attached as a note without replacing
            that error.
        ValueError: If generated paths conflict with the bundle layout or fail
            the inherited ``GeneratedFile`` or ``CoreResult`` validation.
    """
    target_dir = Path(output_dir)
    validated_result, relative_paths = _preflight_bundle(result, target_dir)
    manifest = build_bundle_manifest(validated_result)
    manifest_content = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )

    target_dir.parent.mkdir(parents=True, exist_ok=True)
    _refuse_existing_destination(target_dir)

    staging_dir = Path(
        tempfile.mkdtemp(prefix=".goldilocks-bundle-", dir=target_dir.parent)
    )
    try:
        for generated_file, relative_path in zip(
            validated_result.generated_files, relative_paths, strict=True
        ):
            target_path = staging_dir / relative_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(generated_file.content.encode("utf-8"))

        (staging_dir / MANIFEST_FILENAME).write_bytes(manifest_content)
        _publish_staged_directory(staging_dir, target_dir)
    except BaseException as error:
        cleanup_errors, residue_remains = _cleanup_staging_directory(staging_dir)
        _add_cleanup_note(error, staging_dir, cleanup_errors, residue_remains)
        raise

    cleanup_errors, residue_remains = _cleanup_staging_directory(staging_dir)
    if cleanup_errors or residue_remains is not False:
        _warn_post_publication_cleanup(
            staging_dir,
            cleanup_errors,
            residue_remains,
        )

    return BundleRecord(path=str(output_dir), manifest=manifest)


def _preflight_bundle(
    result: CoreResult,
    output_dir: Path,
    *,
    target_is_windows: bool | None = None,
) -> tuple[CoreResult, tuple[Path, ...]]:
    """Validate all records and filesystem paths without creating output."""
    generated_files = tuple(
        replace(generated_file) for generated_file in result.generated_files
    )
    validated_result = replace(result, generated_files=generated_files)
    path_keys = tuple(
        _target_filesystem_path_key(
            generated_file.path,
            windows=target_is_windows,
        )
        for generated_file in validated_result.generated_files
    )
    resolved_paths = tuple(
        _resolve_bundle_path(output_dir, generated_file.path)
        for generated_file in validated_result.generated_files
    )
    bundle_root = output_dir.resolve()
    manifest_path = bundle_root / MANIFEST_FILENAME
    relative_paths = tuple(
        resolved_path.relative_to(bundle_root) for resolved_path in resolved_paths
    )
    manifest_key = _target_filesystem_path_key(
        MANIFEST_FILENAME,
        windows=target_is_windows,
    )

    for index, (resolved_path, path_key) in enumerate(
        zip(resolved_paths, path_keys, strict=True)
    ):
        generated_path = validated_result.generated_files[index].path
        if (
            resolved_path == manifest_path
            or manifest_path in resolved_path.parents
            or _is_path_prefix(manifest_key, path_key)
        ):
            raise ValueError(
                "Generated file path is reserved for the bundle manifest: "
                f"{generated_path}"
            )
        for earlier_key in path_keys[:index]:
            if path_key == earlier_key:
                raise ValueError(
                    "Generated file paths collide on the target filesystem: "
                    f"{generated_path}"
                )
            if _is_path_prefix(path_key, earlier_key) or _is_path_prefix(
                earlier_key, path_key
            ):
                raise ValueError(
                    "Generated file paths conflict as file and directory: "
                    f"{generated_path}"
                )

    return validated_result, relative_paths


def _target_filesystem_path_key(
    relative_path: str | Path,
    *,
    windows: bool | None = None,
) -> tuple[str, ...]:
    """Return a validated collision key using target path semantics."""
    target_is_windows = os.name == "nt" if windows is None else windows
    if target_is_windows:
        return tuple(
            _canonical_windows_component(part, relative_path)
            for part in PureWindowsPath(relative_path).parts
        )
    return PurePosixPath(relative_path).parts


def _canonical_windows_component(component: str, path: str | Path) -> str:
    """Return a case-insensitive Windows component after conservative validation."""
    if _is_windows_reserved_component(component):
        raise ValueError(
            f"Generated file path contains a component invalid for Windows: {path}"
        )
    return component.casefold()


def _is_windows_reserved_component(component: str) -> bool:
    """Return whether a component is conservatively reserved by Windows."""
    if component[-1:] in {".", " "}:
        return component not in {".", ".."}
    if _WINDOWS_RESERVED_COMPONENT_CHARACTERS.intersection(component):
        return True

    device_name = component.partition(".")[0].rstrip(" ").upper()
    return device_name in _WINDOWS_RESERVED_COMPONENT_NAMES


def _is_path_prefix(parent: tuple[str, ...], child: tuple[str, ...]) -> bool:
    """Return whether ``parent`` is the same as or contains ``child``."""
    return len(parent) <= len(child) and child[: len(parent)] == parent


def _cleanup_staging_directory(
    staging_dir: Path,
) -> tuple[tuple[BaseException, ...], bool | None]:
    """Attempt staging cleanup twice and report errors and residue status.

    ``None`` means an existence probe failed, so residue status is unknown.
    """
    errors: list[BaseException] = []
    for _ in range(2):
        try:
            residue_remains = os.path.lexists(staging_dir)
        except BaseException as error:
            errors.append(error)
            return tuple(errors), None
        if not residue_remains:
            return tuple(errors), False
        try:
            shutil.rmtree(staging_dir)
        except BaseException as error:
            errors.append(error)

    try:
        return tuple(errors), os.path.lexists(staging_dir)
    except BaseException as error:
        errors.append(error)
        return tuple(errors), None


def _add_cleanup_note(
    primary_error: BaseException,
    staging_dir: Path,
    cleanup_errors: tuple[BaseException, ...],
    residue_remains: bool | None,
) -> None:
    """Attach an accurate cleanup outcome without replacing the primary error."""
    cleanup_outcome = _cleanup_outcome(
        staging_dir,
        cleanup_errors,
        residue_remains,
    )
    if cleanup_outcome is not None:
        primary_error.add_note(f"Bundle staging cleanup: {cleanup_outcome}.")


def _warn_post_publication_cleanup(
    staging_dir: Path,
    cleanup_errors: tuple[BaseException, ...],
    residue_remains: bool | None,
) -> None:
    """Warn when cleanup cannot be confirmed after publication succeeds."""
    cleanup_outcome = _cleanup_outcome(
        staging_dir,
        cleanup_errors,
        residue_remains,
    )
    if cleanup_outcome is not None:
        warnings.warn(
            "Bundle publication succeeded; post-publication staging cleanup: "
            f"{cleanup_outcome}.",
            RuntimeWarning,
            stacklevel=2,
        )


def _cleanup_outcome(
    staging_dir: Path,
    cleanup_errors: tuple[BaseException, ...],
    residue_remains: bool | None,
) -> str | None:
    """Describe cleanup errors and known or unknown staging residue."""
    if not cleanup_errors and residue_remains is False:
        return None

    failures = (
        "; ".join(f"{type(error).__name__}: {error}" for error in cleanup_errors)
        or "cleanup left staging in place"
    )
    if residue_remains is True:
        outcome = f"staging residue remains at {staging_dir}"
    elif residue_remains is False:
        outcome = "staging cleanup completed after an earlier failure"
    else:
        outcome = f"could not verify whether staging residue remains at {staging_dir}"
    return f"{failures}; {outcome}"


def _refuse_existing_destination(target_dir: Path) -> None:
    """Reject files, directories, and dangling symlinks at the destination."""
    if os.path.lexists(target_dir):
        raise FileExistsError(
            errno.EEXIST,
            "Bundle destination already exists",
            str(target_dir),
        )


def _publish_staged_directory(staging_dir: Path, target_dir: Path) -> None:
    """Atomically rename staging without replacing a concurrent destination."""
    if sys.platform == "linux":
        _linux_rename_noreplace(staging_dir, target_dir)
        return

    if os.name == "nt":
        os.rename(staging_dir, target_dir)
        return

    raise OSError(
        errno.ENOTSUP,
        "Atomic no-replace directory publication is unsupported on this platform",
        str(target_dir),
    )


def _linux_rename_noreplace(staging_dir: Path, target_dir: Path) -> None:
    """Publish with Linux renameat2(RENAME_NOREPLACE)."""
    renameat2 = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
    if renameat2 is None:
        raise OSError(
            errno.ENOTSUP,
            "Atomic no-replace directory publication is unavailable",
            str(target_dir),
        )

    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        _AT_FDCWD,
        os.fsencode(staging_dir),
        _AT_FDCWD,
        os.fsencode(target_dir),
        _RENAME_NOREPLACE,
    )
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), str(target_dir))


def _resolve_bundle_path(output_dir: Path, relative_path: str) -> Path:
    """Resolve a generated file path without allowing path traversal."""
    target_path = (output_dir / relative_path).resolve()
    root = output_dir.resolve()

    if target_path == root or root not in target_path.parents:
        raise ValueError(
            f"Generated file path escapes bundle directory: {relative_path}"
        )

    return target_path
