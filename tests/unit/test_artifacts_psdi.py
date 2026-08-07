"""Tests for PSDI artifact resolution. No test here touches the network."""

from __future__ import annotations

import hashlib

import pytest

from goldilocks_core.artifacts import cache, psdi

PAYLOAD = b"a plausible model artifact"
RECORD = "vtmb1-sr573"


class _Response:
    """Enough of a ``requests`` response for the resolver."""

    def __init__(self, payload=None, json_body=None, chunk_size=8):
        self._payload = payload or b""
        self._json = json_body
        self._chunk_size = chunk_size
        self.raise_for_status_calls = 0

    def json(self):
        return self._json

    def raise_for_status(self):
        self.raise_for_status_calls += 1

    def iter_content(self, _size):
        for start in range(0, len(self._payload), self._chunk_size):
            yield self._payload[start : start + self._chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class _FakeHttp:
    """Serves one record listing and one file body, and records every call."""

    def __init__(self, payload=PAYLOAD, digest=None, filename="QRF95.pkl"):
        self.payload = payload
        self.filename = filename
        self.digest = digest or hashlib.md5(payload).hexdigest()
        self.urls: list[str] = []

    def get(self, url, **_kwargs):
        self.urls.append(url)
        if url.endswith("/files"):
            return _Response(
                json_body={
                    "entries": [
                        {
                            "key": self.filename,
                            "size": len(self.payload),
                            "checksum": f"md5:{self.digest}",
                            "links": {"content": f"{url}/{self.filename}/content"},
                        },
                        {
                            "key": "README.md",
                            "size": 3,
                            "checksum": "md5:" + "1" * 32,
                            "links": {"content": f"{url}/README.md/content"},
                        },
                    ]
                }
            )
        return _Response(payload=self.payload)


@pytest.fixture(autouse=True)
def _isolated_cache(monkeypatch, tmp_path):
    monkeypatch.setenv(cache.CACHE_ENV, str(tmp_path / "cache"))


def test_describe_reports_size_and_digest_without_downloading():
    http = _FakeHttp()

    described = psdi.describe(RECORD, "QRF95.pkl", http=http)

    assert described.size == len(PAYLOAD)
    assert described.algorithm == "md5"
    assert described.digest == http.digest
    assert http.urls == [f"{psdi.PSDI_API}/records/{RECORD}/files"]


def test_describe_names_the_available_files_when_one_is_missing():
    http = _FakeHttp()

    with pytest.raises(FileNotFoundError, match="QRF95.pkl, README.md"):
        psdi.describe(RECORD, "absent.pkl", http=http)


def test_fetch_writes_a_verified_artifact_into_the_cache():
    http = _FakeHttp()

    fetched = psdi.fetch(RECORD, "QRF95.pkl", http=http)

    assert fetched.read_bytes() == PAYLOAD
    assert fetched == cache.artifact_path("psdi", RECORD, "QRF95.pkl")


def test_fetch_rejects_an_artifact_that_does_not_match_its_digest():
    http = _FakeHttp(digest="0" * 32)

    with pytest.raises(cache.ChecksumMismatch):
        psdi.fetch(RECORD, "QRF95.pkl", http=http)

    assert not cache.artifact_path("psdi", RECORD, "QRF95.pkl").exists()


def test_fetch_serves_a_cached_artifact_without_any_request():
    http = _FakeHttp()
    psdi.fetch(RECORD, "QRF95.pkl", http=http)
    calls_after_first_fetch = len(http.urls)

    again = psdi.fetch(RECORD, "QRF95.pkl", http=http)

    assert again.read_bytes() == PAYLOAD
    assert len(http.urls) == calls_after_first_fetch


def test_fetch_honours_an_alternative_api_so_staging_can_be_targeted():
    http = _FakeHttp()
    staging = "https://data-collections-staging.psdi.ac.uk/api"

    psdi.fetch(RECORD, "QRF95.pkl", api=staging, http=http)

    assert http.urls[0].startswith(staging)


def test_fetch_writes_to_an_explicit_destination(tmp_path):
    http = _FakeHttp()
    destination = tmp_path / "elsewhere" / "QRF95.pkl"

    fetched = psdi.fetch(RECORD, "QRF95.pkl", destination=destination, http=http)

    assert fetched == destination
    assert not cache.artifact_path("psdi", RECORD, "QRF95.pkl").exists()
