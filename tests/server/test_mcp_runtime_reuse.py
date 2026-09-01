from __future__ import annotations

import asyncio

import pytest

from goldilocks_core.runtime import Service

pytest.importorskip("mcp")
create_server = pytest.importorskip("goldilocks_core.server.mcp").create_server


class _CountingService(Service):
    """Record preset calls made through one service instance."""

    def __init__(self) -> None:
        super().__init__()
        self.preset_calls = 0

    def run_preset(self, request):
        self.preset_calls += 1
        return super().run_preset(request)


def test_mcp_reuses_one_service_across_tool_calls(request_body) -> None:
    """Serve multiple tool calls through the same process service."""
    service = _CountingService()
    server = create_server(service)

    async def call_twice() -> None:
        first = await server.call_tool("recommend", request_body)
        second = await server.call_tool("recommend", request_body)
        assert not first.is_error
        assert not second.is_error

    try:
        asyncio.run(call_twice())
        assert service.preset_calls == 2
        assert not service.is_closed
    finally:
        service.close()
