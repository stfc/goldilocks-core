from __future__ import annotations

import hashlib
import shutil
from concurrent.futures import ThreadPoolExecutor
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
_RANGED_THRESHOLD_BYTES = 8 * 1024 * 1024
_RANGE_CONNECTIONS = 8


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
    advertises byte ranges; everything else is streamed over one connection.
    ``destination`` must not exist. Raises ``ChecksumMismatch`` (or any
    ``requests`` error) on a failed or corrupted download.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    parsed = urlparse(file.url)
    if parsed.scheme == "file":
        with Path(parsed.path).open("rb") as source, destination.open("xb") as target:
            shutil.copyfileobj(source, target, length=_CHUNK_SIZE)
    else:
        with _session().get(
            file.url, stream=True, timeout=_TIMEOUT_SECONDS
        ) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length", 0))
            if (
                response.headers.get("Accept-Ranges") != "bytes"
                or total < _RANGED_THRESHOLD_BYTES
            ):
                with destination.open("xb") as target:
                    for chunk in response.iter_content(_CHUNK_SIZE):
                        target.write(chunk)
            else:
                _download_ranged(file.url, destination, total)
    verify_source(file, destination)


def _download_ranged(url: str, destination: Path, total: int) -> None:
    """Fetch ``url`` with concurrent ranged GETs reassembled into one file."""
    step = total // _RANGE_CONNECTIONS
    bounds = [
        (index * step, (index + 1) * step - 1)
        for index in range(_RANGE_CONNECTIONS - 1)
    ]
    bounds.append(((_RANGE_CONNECTIONS - 1) * step, total - 1))
    with destination.open("xb") as target:
        target.truncate(total)

    def fetch(index: int) -> None:
        start, end = bounds[index]
        with _session().get(
            url,
            headers={"Range": f"bytes={start}-{end}"},
            stream=True,
            timeout=_TIMEOUT_SECONDS,
        ) as response:
            if response.status_code != 206:
                response.raise_for_status()
                raise requests.RequestException(
                    f"range request returned HTTP {response.status_code}, expected 206"
                )
            with destination.open("r+b") as target:
                target.seek(start)
                for chunk in response.iter_content(_CHUNK_SIZE):
                    target.write(chunk)

    with ThreadPoolExecutor(max_workers=len(bounds)) as pool:
        list(pool.map(fetch, range(len(bounds))))


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
