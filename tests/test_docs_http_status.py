from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

# Active docs that must describe the HTTP server transport as implemented.
_ACTIVE_DOCS = [
    _ROOT / "README.md",
    _ROOT / "docs" / "contracts.md",
    _ROOT / "docs" / "pipeline.md",
    _ROOT / "docs" / "tutorial.md",
    _ROOT / "docs" / "server" / "http.md",
]

# Source modules whose module/class docstrings reference the shared job runner.
_ACTIVE_SOURCE = [
    _ROOT / "src" / "goldilocks_core" / "jobs.py",
    _ROOT / "src" / "goldilocks_core" / "contracts.py",
]

# Phrases that claim the HTTP transport is not yet implemented. MCP may still be
# described as future; these patterns are scoped to HTTP only.
_STALE_HTTP_PHRASES = [
    "future HTTP",
    "HTTP transport is not implemented",
    "HTTP and MCP transports are not implemented",
    "Those transports are not implemented yet",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", _ACTIVE_DOCS, ids=lambda p: str(p.relative_to(_ROOT)))
def test_active_docs_do_not_claim_http_unimplemented(path: Path) -> None:
    """Active docs must not describe the HTTP transport as future/unimplemented."""
    text = _read(path)
    for phrase in _STALE_HTTP_PHRASES:
        assert phrase not in text, f"{path.relative_to(_ROOT)}: stale phrase {phrase!r}"


@pytest.mark.parametrize(
    "path", _ACTIVE_SOURCE, ids=lambda p: str(p.relative_to(_ROOT))
)
def test_source_docstrings_do_not_claim_http_unimplemented(path: Path) -> None:
    """Source docstrings must not describe the HTTP transport as future."""
    text = _read(path)
    for phrase in _STALE_HTTP_PHRASES:
        assert phrase not in text, f"{path.relative_to(_ROOT)}: stale phrase {phrase!r}"


def test_http_transport_doc_describes_implementation() -> None:
    """docs/server/http.md documents the implemented HTTP server transport."""
    text = _read(_ROOT / "docs" / "server" / "http.md")
    assert "goldilocks-core serve" in text
    # The transport is described as implemented, not as future work.
    assert "HTTP server transport" in text


def test_mcp_remains_described_as_future() -> None:
    """MCP is a sibling concern that stays future in active docs."""
    tutorial = _read(_ROOT / "docs" / "tutorial.md")
    assert "MCP" in tutorial
    assert "sibling concern" in tutorial
    # The tutorial explicitly marks MCP as not implemented yet.
    assert "not" in tutorial and "implemented here yet" in tutorial

    readme = _read(_ROOT / "README.md")
    assert "MCP transport is a sibling concern, not implemented here yet" in readme
    pipeline = _read(_ROOT / "docs" / "pipeline.md")
    assert "not implemented here yet" in pipeline
