"""Shared surface for optional Core transports.

HTTP (FastAPI) and MCP transports live in :mod:`goldilocks_core.server.http` and
:mod:`goldilocks_core.server.mcp` and import their heavy dependencies lazily,
so importing this facade (and ``goldilocks_core``) never pulls ``fastapi`` or
``mcp``. The shared request deserializer is re-exported here because both
transports use it and it has no optional dependencies.
"""
from __future__ import annotations

from goldilocks_core.server.request import RequestError, from_dict

__all__ = ["RequestError", "from_dict"]
