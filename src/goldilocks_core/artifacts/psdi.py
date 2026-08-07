"""Resolve artifacts from PSDI Data Collections.

PSDI Data Collections is an InvenioRDM instance. Published files are retrievable
without credentials, and every file entry carries the digest to verify it
against, so a first-run fetch works for any user with no account anywhere.

Retrieval is written against ``requests`` rather than the ``data-collections-api``
client: the client's download paths raise on non-JSON content and buffer whole
artifacts in memory, and neither streaming, digest verification nor the cache
layout would come from it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from goldilocks_core.artifacts.cache import artifact_path, store_verified

PSDI_API = "https://data-collections.psdi.ac.uk/api"
"""Base URL of the production PSDI Data Collections API."""

_CHUNK_BYTES = 1 << 20
_TIMEOUT_SECONDS = 300


class HttpGetter(Protocol):
    """The subset of ``requests`` this module uses."""

    def get(self, url: str, **kwargs: Any) -> Any:
        """Perform an HTTP GET."""


@dataclass(frozen=True, slots=True)
class PsdiFile:
    """One file published in a PSDI record.

    Attributes:
        record_id: record identifier, e.g. ``vtmb1-sr573``. Each version of a
            record has its own identifier, so this pins a version.
        filename: file name within the record.
        size: size in bytes, as published.
        algorithm: digest algorithm, e.g. ``md5``.
        digest: expected hex digest.
        content_url: URL the bytes are served from.
    """

    record_id: str
    filename: str
    size: int
    algorithm: str
    digest: str
    content_url: str


def describe(
    record_id: str,
    filename: str,
    *,
    api: str = PSDI_API,
    http: HttpGetter | None = None,
) -> PsdiFile:
    """Look up one file in a record without downloading it.

    The listing carries both the size and the digest, so a caller can report
    what a fetch will cost before starting it.

    Raises:
        FileNotFoundError: the record has no such file.
    """
    http = _default_http(http)
    listing = http.get(f"{api}/records/{record_id}/files", timeout=30).json()

    for entry in listing.get("entries", ()):
        if entry["key"] != filename:
            continue
        algorithm, _, digest = entry["checksum"].partition(":")
        return PsdiFile(
            record_id=record_id,
            filename=filename,
            size=entry["size"],
            algorithm=algorithm,
            digest=digest,
            content_url=entry["links"]["content"],
        )

    available = ", ".join(sorted(e["key"] for e in listing.get("entries", ())))
    raise FileNotFoundError(
        f"PSDI record {record_id} has no file {filename!r}; it holds: {available}"
    )


def fetch(
    record_id: str,
    filename: str,
    *,
    destination: Path | None = None,
    api: str = PSDI_API,
    http: HttpGetter | None = None,
) -> Path:
    """Fetch one file from a PSDI record into the cache, verified.

    Returns the cached path immediately if the artifact is already present.

    Args:
        record_id: record identifier; pins the record version.
        filename: file name within the record.
        destination: override the cache path. Defaults to a location derived
            from the record id and file name.
        api: API base URL, so a caller can point at the staging instance.
        http: HTTP getter, for tests.

    Returns:
        Path to the verified artifact.

    Raises:
        FileNotFoundError: the record has no such file.
        ChecksumMismatch: the transferred bytes do not match the published
            digest.
    """
    target = destination or artifact_path("psdi", record_id, filename)
    if target.is_file():
        return target

    http = _default_http(http)
    published = describe(record_id, filename, api=api, http=http)

    with http.get(
        published.content_url, stream=True, timeout=_TIMEOUT_SECONDS
    ) as response:
        response.raise_for_status()
        return store_verified(
            response.iter_content(_CHUNK_BYTES),
            target,
            published.algorithm,
            published.digest,
        )


def _default_http(http: HttpGetter | None) -> HttpGetter:
    """Return ``http``, falling back to ``requests``."""
    if http is not None:
        return http

    import requests

    return requests
