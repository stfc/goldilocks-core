"""HTTP transport shared by the artifact resolvers.

Resolvers differ in how an entry becomes a URL and an expected digest. Moving
the bytes is the same work every time, so it lives here: streamed, never held
in memory whole, and injectable so resolver tests need no network.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, Protocol

CHUNK_BYTES = 1 << 20
TIMEOUT_SECONDS = 300


class HttpClient(Protocol):
    """The subset of ``requests`` the resolvers use."""

    def get(self, url: str, **kwargs: Any) -> Any:
        """Perform an HTTP GET."""

    def head(self, url: str, **kwargs: Any) -> Any:
        """Perform an HTTP HEAD."""


def default_client(http: HttpClient | None = None) -> HttpClient:
    """Return ``http``, falling back to ``requests``."""
    if http is not None:
        return http

    import requests

    return requests


def stream(
    url: str,
    *,
    http: HttpClient | None = None,
    chunk_bytes: int = CHUNK_BYTES,
) -> Iterator[bytes]:
    """Yield the body of ``url`` in chunks.

    Memory use is bounded by ``chunk_bytes`` regardless of artifact size, and
    the caller can digest the bytes as they pass rather than re-reading the
    file afterwards.
    """
    client = default_client(http)
    with client.get(url, stream=True, timeout=TIMEOUT_SECONDS) as response:
        response.raise_for_status()
        yield from response.iter_content(chunk_bytes)


def transferred_size(url: str, *, http: HttpClient | None = None) -> int | None:
    """Return the size ``url`` will transfer, without transferring it.

    This is what a fetch prompt should quote: the bytes that cross the network,
    which for a compressed archive is not the size it occupies once unpacked.
    Returns ``None`` when the server declines to say.
    """
    client = default_client(http)
    response = client.head(url, allow_redirects=True, timeout=30)
    response.raise_for_status()

    declared = response.headers.get("Content-Length")
    return int(declared) if declared is not None else None


def download(url: str, destination: Path, *, http: HttpClient | None = None) -> Path:
    """Stream ``url`` to ``destination`` when no digest is published for it.

    Used for the PseudoDojo archives, whose contents are verified individually
    after unpacking rather than as a whole. Prefer
    :func:`goldilocks_core.artifacts.cache.store_verified` wherever a digest
    exists.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as out_file:
        for chunk in stream(url, http=http):
            out_file.write(chunk)

    return destination
