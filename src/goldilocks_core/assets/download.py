from __future__ import annotations

import hashlib
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from goldilocks_core.assets.records import AssetFile

_CHUNK_SIZE = 1024 * 1024
# (connect, read) rather than one shared value: PSDI's failure mode isn't
# only a fast error response -- some requests against a bad signed URL
# simply never answer at all. A single generous timeout (previously 300s)
# means a hung request eats minutes before the retry-with-a-fresh-URL logic
# ever gets a turn; a request that is actually progressing normally never
# goes anywhere near 30s between chunks, so this fails a genuine hang far
# sooner without cutting into real transfers (observed directly: a 7m43s
# total install that should complete in seconds, 2026-09-18).
_TIMEOUT_SECONDS = (10, 30)
_RETRIES = Retry(
    total=3,
    backoff_factor=0.5,
    # 500 is in this list alongside the usual transient codes because PSDI's
    # presigned-S3 file endpoint (data-collections.psdi.ac.uk) intermittently
    # answers a plain GET with a bodyless "500 UnknownError" (reproduced
    # directly against S3 with plain curl, independent of this client).
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"GET"}),
    raise_on_status=False,
)
_RANGED_THRESHOLD_BYTES = 8 * 1024 * 1024
_RANGE_CONNECTIONS = 8
# A retry within one request (``_RETRIES`` above) reuses the exact signed URL
# a redirect already resolved to -- fine for an ordinary transient blip, but
# PSDI's failure mode above sometimes keeps failing on that *specific* signed
# URL while a fresh top-level request (a new redirect hop, thus a new
# signature) succeeds (observed directly against a real PSDI record,
# 2026-09-18: same file, alternating success/500 across separate requests).
# This retries the whole fetch -- every range's own redirect included -- not
# just one already-resolved hop.
_SOURCE_ATTEMPTS = 3
_SOURCE_RETRY_BACKOFF_SECONDS = 1.0


class ChecksumMismatch(ValueError):
    pass


def _session() -> requests.Session:
    """Return a one-shot session with a transient-failure retry policy."""
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=_RETRIES)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def download(file: AssetFile, destination: Path) -> None:
    """Fetch an asset file to ``destination`` over ``file://`` or HTTP(S).

    Large HTTP sources are fetched with parallel ranged GETs when the server
    honors byte ranges; everything else, including sources that ignore the
    Range header, is streamed over one connection. ``destination`` must not
    exist when a fetch attempt starts. Raises ``ChecksumMismatch`` (or any
    ``requests`` error) on a failed or corrupted download.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    parsed = urlparse(file.url)
    if parsed.scheme == "file":
        # url2pathname converts the URL path to a host path, stripping the
        # leading slash before a Windows drive letter and unquoting escapes.
        with (
            Path(url2pathname(parsed.path)).open("rb") as source,
            destination.open("xb") as target,
        ):
            shutil.copyfileobj(source, target, length=_CHUNK_SIZE)
    else:
        _fetch_remote(file, destination)
    verify_source(file, destination)


def _fetch_remote(file: AssetFile, destination: Path) -> None:
    for attempt in range(_SOURCE_ATTEMPTS):
        destination.unlink(missing_ok=True)
        try:
            with _session().get(
                file.url, stream=True, timeout=_TIMEOUT_SECONDS
            ) as response:
                response.raise_for_status()
                total = int(response.headers.get("Content-Length", 0))
                if (
                    response.headers.get("Accept-Ranges") != "bytes"
                    or total < _RANGED_THRESHOLD_BYTES
                ):
                    _stream_body(response, destination)
                else:
                    _download_ranged(file.url, destination, total)
            return
        except requests.RequestException:
            if attempt == _SOURCE_ATTEMPTS - 1:
                raise
            time.sleep(_SOURCE_RETRY_BACKOFF_SECONDS * (attempt + 1))


def _stream_body(response: requests.Response, destination: Path) -> None:
    """Write one full response body to a fresh ``destination``."""
    with destination.open("xb") as target:
        for chunk in response.iter_content(_CHUNK_SIZE):
            target.write(chunk)


def _download_ranged(url: str, destination: Path, total: int) -> None:
    """Fetch ``url`` with concurrent ranged GETs reassembled into one file.

    The first range runs in-thread; a 200 answer means the source ignores
    ranges and the download falls back to that single stream.
    """
    step = total // _RANGE_CONNECTIONS
    bounds = [
        (index * step, (index + 1) * step - 1)
        for index in range(_RANGE_CONNECTIONS - 1)
    ]
    bounds.append(((_RANGE_CONNECTIONS - 1) * step, total - 1))
    with destination.open("xb") as target:
        target.truncate(total)

    first_start, first_end = bounds[0]
    with _session().get(
        url,
        headers={"Range": f"bytes={first_start}-{first_end}"},
        stream=True,
        timeout=_TIMEOUT_SECONDS,
    ) as response:
        if response.status_code == 200:
            destination.unlink()
            _stream_body(response, destination)
            return
        _write_range(response, destination, first_start)

    def fetch(index: int) -> None:
        start, end = bounds[index]
        with _session().get(
            url,
            headers={"Range": f"bytes={start}-{end}"},
            stream=True,
            timeout=_TIMEOUT_SECONDS,
        ) as response:
            _write_range(response, destination, start)

    with ThreadPoolExecutor(max_workers=len(bounds) - 1) as pool:
        list(pool.map(fetch, range(1, len(bounds))))


def _write_range(response: requests.Response, destination: Path, start: int) -> None:
    """Stream one 206 body into ``destination`` at ``start``; reject non-206."""
    if response.status_code != 206:
        response.raise_for_status()
        raise requests.RequestException(
            f"range request returned HTTP {response.status_code}, expected 206"
        )
    with destination.open("r+b") as target:
        target.seek(start)
        for chunk in response.iter_content(_CHUNK_SIZE):
            target.write(chunk)


def verify_source(file: AssetFile, path: Path) -> None:
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
