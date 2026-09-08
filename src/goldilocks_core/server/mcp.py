from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from goldilocks_core.request import ComputeRequest
from goldilocks_core.runtime.service import OperationFailure, Service
from goldilocks_core.server.documents import (
    DraftDocument,
    InlineStructureDocument,
    MemoryOutputDocument,
    SelectionDocument,
)

try:
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError as error:
    raise ImportError(
        "The MCP transport requires goldilocks-core[mcp]. "
        "Install it with `uv sync --extra mcp`."
    ) from error

__all__ = ["create_server", "serve"]


class _StrictMCPServer(MCPServer):
    async def list_tools(self) -> list[Any]:
        tools = await super().list_tools()
        for tool in tools:
            tool.input_schema["additionalProperties"] = False
        return tools

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        context: Any | None = None,
    ) -> Any:
        tools = await self.list_tools()
        tool = next((candidate for candidate in tools if candidate.name == name), None)
        if tool is not None:
            allowed = set(tool.input_schema.get("properties", {}))
            unknown = sorted(set(arguments) - allowed)
            if unknown:
                raise ToolError(f"Unknown {name} arguments: {', '.join(unknown)}")
        return await super().call_tool(name, arguments, context)


def create_server(
    service: Service | None = None, *, name: str = "goldilocks-core"
) -> MCPServer:
    owns_service = service is None
    state = service if service is not None else Service()

    @asynccontextmanager
    async def lifespan(server: MCPServer):
        del server
        try:
            yield state
        finally:
            if owns_service:
                state.close()

    server = _StrictMCPServer(
        name=name,
        version="0.1.0",
        instructions=(
            "Inspect structures and compute Goldilocks Core records or named presets."
        ),
        lifespan=lifespan,
    )

    @server.tool(
        description="Describe Core tasks, presets, records, codes, and assets."
    )
    async def capabilities() -> dict[str, Any]:
        try:
            return await asyncio.to_thread(state.capabilities_document)
        except OperationFailure as error:
            raise ToolError(str(error)) from error

    @server.tool(description="Normalize and inspect an inline structure source.")
    async def inspect_structure(
        source: InlineStructureDocument,
    ) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(state.inspect_document, source)
        except OperationFailure as error:
            raise ToolError(str(error)) from error

    @server.tool(
        description=(
            "Compute one named preset or selected record ids. Omitted output "
            "automatically publishes complete DFT Input Data."
        )
    )
    async def compute(
        draft: DraftDocument,
        selection: SelectionDocument,
        output: MemoryOutputDocument | None = None,
    ) -> dict[str, Any]:
        try:
            prepared = await asyncio.to_thread(
                state.compute_document,
                ComputeRequest(draft, selection),
                publication="auto" if output is None else "memory",
            )
        except OperationFailure as error:
            raise ToolError(str(error)) from error
        return prepared.result

    return server


def serve() -> None:
    create_server().run("stdio")
