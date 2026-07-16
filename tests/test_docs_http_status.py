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


def _normalize(text: str) -> str:
    """Collapse whitespace so doc wrapping cannot break phrase assertions."""
    return " ".join(text.split())


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


def test_active_docs_describe_implemented_stdio_mcp() -> None:
    """Active docs describe MCP as an implemented stdio-only transport.

    The stdio MCP transport is implemented, not future work. It shares the
    HTTP request parser and contracts and remains a thin process-owned-runtime
    transport.
    """
    for path in (
        _ROOT / "README.md",
        _ROOT / "docs" / "pipeline.md",
        _ROOT / "docs" / "tutorial.md",
    ):
        text = _read(path)
        assert "MCP" in text
        # MCP is described as implemented, not as future/unimplemented.
        assert "implemented" in text
        assert "not implemented here yet" not in text
        # v1 exposes stdio only.
        assert "stdio" in text


def test_pipeline_and_tutorial_confine_mcp_to_shared_parser_and_runtime() -> None:
    """pipeline.md/tutorial.md confine MCP to the shared parser and thin runtime."""
    for path in (_ROOT / "docs" / "pipeline.md", _ROOT / "docs" / "tutorial.md"):
        text = _normalize(_read(path))
        assert "shares the HTTP request parser" in text
        assert "thin process-owned-runtime transport" in text


def test_serialization_shares_json_domain_path_with_stdio_mcp() -> None:
    """serialization.md shares the HTTP JSON->domain path with stdio MCP."""
    text = _normalize(_read(_ROOT / "docs" / "serialization.md"))
    assert "HTTP and stdio MCP transports" in text
    assert "intended for MCP" not in text
    assert "not implemented here yet" not in text
