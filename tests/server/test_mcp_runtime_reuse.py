from __future__ import annotations

import asyncio

import pytest

from goldilocks_core.runtime import Service

pytest.importorskip("mcp")
create_server = pytest.importorskip("goldilocks_core.server.mcp").create_server


class _CountingService(Service):
    def __init__(self) -> None:
        super().__init__()
        self.computation_calls = 0

    def compute(self, request, *, output=None):
        self.computation_calls += 1
        return super().compute(request, output=output)


def test_mcp_reuses_one_service_across_tool_calls(request_body) -> None:
    service = _CountingService()
    server = create_server(service)

    async def call_twice() -> None:
        first = await server.call_tool("recommend", request_body)
        second = await server.call_tool("recommend", request_body)
        assert not first.is_error
        assert not second.is_error

    try:
        asyncio.run(call_twice())
        assert service.computation_calls == 2
        assert not service.is_closed
    finally:
        service.close()
