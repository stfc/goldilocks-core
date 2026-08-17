"""Streaming acquisition and integrity checks for runtime assets."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from goldilocks_core.assets.records import AssetFile

_CHUNK_SIZE = 1024 * 1024
_TIMEOUT_SECONDS = 300
_RETRIES = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=(429, 502, 503, 504),
    allowed_methods=frozenset({"GET"}),
    raise_on_status=False,
)


class ChecksumMismatch(ValueError):
    """A downloaded source file did not match its declared digest."""
    pass


def _session() -> requests.Session:
    """Return a one-shot session with a transient-failure retry policy."""
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=_RETRIES)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def download(file: AssetFile, destination: Path) -> None:
    """Stream one source file to a new destination and verify it."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    parsed = urlparse(file.url)
    if parsed.scheme == "file":
        with Path(parsed.path).open("rb") as source, destination.open("xb") as target:
            shutil.copyfileobj(source, target, length=_CHUNK_SIZE)
    else:
        with (
            _session().get(file.url, stream=True, timeout=_TIMEOUT_SECONDS) as response,
            destination.open("xb") as target,
        ):
            response.raise_for_status()
            for chunk in response.iter_content(_CHUNK_SIZE):
                target.write(chunk)
    verify_source(file, destination)


def verify_source(file: AssetFile, path: Path) -> None:
    """Verify the declared size and optional checksum of a source file."""
    size = path.stat().st_size
    if file.size is not None and size != file.size:
        raise ChecksumMismatch(
            f"{file.role} size mismatch: expected {file.size}, downloaded {size}"
        )
    if file.checksum is None:
        return
    algorithm, separator, expected = file.checksum.partition(":")
    if not separator or not expected:
        raise ValueError(f"checksum must be '<algorithm>:<digest>': {file.checksum!r}")
    try:
        digest = hashlib.new(algorithm)
    except ValueError as error:
        raise ValueError(f"unsupported checksum algorithm: {algorithm}") from error
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual.lower() != expected.lower():
        raise ChecksumMismatch(
            f"{file.role} checksum mismatch: expected {expected}, downloaded {actual}"
        )
