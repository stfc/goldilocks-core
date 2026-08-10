from __future__ import annotations

import asyncio

import pytest

from goldilocks_core.runtime import CoreRuntime

pytest.importorskip("mcp")
create_server = pytest.importorskip("goldilocks_core.server.mcp").create_server


class _CountingRuntime(CoreRuntime):
    """Record recommend calls made through one runtime instance."""

    def __init__(self) -> None:
        super().__init__()
        self.recommend_calls = 0

    def recommend(self, request):
        self.recommend_calls += 1
        return super().recommend(request)


def test_mcp_reuses_one_runtime_across_tool_calls(request_body) -> None:
    """Serve multiple tool calls through the same process runtime."""
    runtime = _CountingRuntime()
    server = create_server(runtime)

    async def call_twice() -> None:
        first = await server.call_tool("recommend", request_body)
        second = await server.call_tool("recommend", request_body)
        assert not first.is_error
        assert not second.is_error

    try:
        asyncio.run(call_twice())
        assert runtime.recommend_calls == 2
        assert not runtime.is_closed
    finally:
        runtime.close()
