"""Tests for the user-owned artifact cache."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from goldilocks_core.artifacts import cache


def _digest(payload: bytes) -> str:
    return hashlib.md5(payload).hexdigest()


def test_cache_root_prefers_the_explicit_override(monkeypatch, tmp_path):
    monkeypatch.setenv(cache.CACHE_ENV, str(tmp_path / "shared"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "ignored"))

    assert cache.cache_root() == tmp_path / "shared"


def test_cache_root_falls_back_to_xdg_then_home(monkeypatch, tmp_path):
    monkeypatch.delenv(cache.CACHE_ENV, raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert cache.cache_root() == tmp_path / "xdg" / "goldilocks-core"

    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path / "home"))
    expected = tmp_path / "home" / ".local" / "share" / "goldilocks-core"
    assert cache.cache_root() == expected


def test_cache_root_is_never_inside_the_installed_package(monkeypatch, tmp_path):
    """An upgrade replaces the package directory; fetched artifacts must survive it."""
    monkeypatch.delenv(cache.CACHE_ENV, raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path / "home"))

    package_directory = Path(cache.__file__).resolve().parent
    assert package_directory not in cache.cache_root().resolve().parents


def test_store_verified_writes_when_the_digest_matches(tmp_path):
    payload = b"pseudopotential bytes"
    destination = tmp_path / "nested" / "Si.upf"

    written = cache.store_verified([payload], destination, "md5", _digest(payload))

    assert written == destination
    assert destination.read_bytes() == payload


def test_store_verified_reassembles_chunks_in_order(tmp_path):
    chunks = [b"one", b"two", b"three"]
    destination = tmp_path / "model.pkl"

    cache.store_verified(chunks, destination, "md5", _digest(b"".join(chunks)))

    assert destination.read_bytes() == b"onetwothree"


def test_store_verified_rejects_a_mismatch_and_leaves_nothing_behind(tmp_path):
    destination = tmp_path / "model.pkl"

    with pytest.raises(cache.ChecksumMismatch, match="expected md5"):
        cache.store_verified([b"corrupted"], destination, "md5", "0" * 32)

    assert not destination.exists()
    assert list(tmp_path.iterdir()) == []


def test_store_verified_does_not_replace_an_existing_file_on_mismatch(tmp_path):
    destination = tmp_path / "model.pkl"
    destination.write_bytes(b"the good one")

    with pytest.raises(cache.ChecksumMismatch):
        cache.store_verified([b"the bad one"], destination, "md5", "0" * 32)

    assert destination.read_bytes() == b"the good one"


def test_store_verified_never_holds_the_whole_artifact(tmp_path):
    """Chunks are consumed lazily, so memory does not scale with artifact size."""
    live = 0

    def chunks():
        nonlocal live
        for _ in range(64):
            live += 1
            yield b"x" * 1024
            live -= 1

    payload = b"x" * 1024 * 64
    cache.store_verified(chunks(), tmp_path / "big.bin", "md5", _digest(payload))

    assert live == 0


def test_artifact_path_is_relative_to_the_cache_root(monkeypatch, tmp_path):
    monkeypatch.setenv(cache.CACHE_ENV, str(tmp_path))

    assert cache.artifact_path("psdi", "abc12-xyz34", "QRF95.pkl") == (
        tmp_path / "psdi" / "abc12-xyz34" / "QRF95.pkl"
    )
