"""User-owned cache for artifacts fetched on first use."""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

CACHE_ENV = "GOLDILOCKS_CACHE"
"""Environment variable overriding the artifact cache location."""

_PART_SUFFIX = ".part"


class ChecksumMismatch(ValueError):
    """A fetched artifact did not match its published digest."""


def cache_root() -> Path:
    """Return the directory holding fetched artifacts.

    Resolution order: ``GOLDILOCKS_CACHE``, then ``XDG_DATA_HOME``, then
    ``~/.local/share``. The location is deliberately outside the installed
    package: ``pip install --upgrade`` replaces the package directory, and on
    shared installations it is often read-only.
    """
    override = os.environ.get(CACHE_ENV)
    if override:
        return Path(override).expanduser()

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = (
        Path(xdg_data_home).expanduser()
        if xdg_data_home
        else Path.home() / ".local" / "share"
    )
    return base / "goldilocks-core"


def artifact_path(*parts: str) -> Path:
    """Return the cache path for an artifact addressed by ``parts``."""
    return cache_root().joinpath(*parts)


def store_verified(
    chunks: Iterable[bytes],
    destination: Path,
    algorithm: str,
    expected: str,
) -> Path:
    """Write ``chunks`` to ``destination``, keeping them only if they verify.

    The digest is computed as the bytes pass through, so the artifact is never
    read back to check it, and the result is written to a temporary name and
    renamed only once it matches. A caller therefore sees either the complete
    verified artifact or no file at all -- an interrupted transfer cannot leave
    a truncated model that later loads as a corrupt one.

    Args:
        chunks: byte chunks in order. Not held in memory beyond the current one.
        destination: final path. Parent directories are created.
        algorithm: digest name as published by the source (e.g. ``md5``).
        expected: expected hex digest.

    Returns:
        The path the artifact was written to.

    Raises:
        ChecksumMismatch: the transferred bytes do not match ``expected``. The
            partial file is removed.
    """
    digest = hashlib.new(algorithm)
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        delete=False, dir=destination.parent, suffix=_PART_SUFFIX
    ) as partial_file:
        partial = Path(partial_file.name)
        for chunk in chunks:
            partial_file.write(chunk)
            digest.update(chunk)

    actual = digest.hexdigest()
    if actual != expected:
        partial.unlink(missing_ok=True)
        raise ChecksumMismatch(
            f"{destination.name}: expected {algorithm} {expected}, got {actual}"
        )

    partial.replace(destination)
    return destination
