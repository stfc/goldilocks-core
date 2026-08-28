"""MCP tools over one process-owned Core service.

A thin transport: each tool builds the shared parser's mapping from typed
pydantic arguments, dispatches through one
:class:`~goldilocks_core.runtime.service.CoreService` held for the process
lifetime, and returns the result's JSON form. Tool input schemas are derived
from the contract types so agents get constrained choices. Behind the optional
``[mcp]`` extra; importing :mod:`goldilocks_core` never imports the MCP SDK.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Literal

from goldilocks_core.contracts import (
    ModelSource,
    ModelType,
    QueryRequest,
    SmearingType,
    VdwMethod,
)
from goldilocks_core.runtime.service import CoreService
from goldilocks_core.server.request import from_dict

try:
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
    from pydantic import BaseModel, ConfigDict, Field
except ImportError as error:
    raise ImportError(
        "The MCP transport requires goldilocks-core[mcp]. "
        "Install it with `uv sync --extra mcp`."
    ) from error

__all__ = ["create_server", "serve"]

_OutputName = Literal[
    "analysis",
    "advice",
    "k_points",
    "selection",
    "generated_files",
]


class _StrictMCPServer(MCPServer):
    """MCP server that enforces each published root input schema."""

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


class _InlineStructure(BaseModel):
    """Inline CIF or POSCAR content."""

    model_config = ConfigDict(extra="forbid", strict=True)

    content: str
    format: Literal["cif", "poscar"] | None = None


class _Intent(BaseModel):
    """Calculation intent fields."""

    model_config = ConfigDict(extra="forbid", strict=True)

    code: str = "quantum_espresso"
    task: str = "scf_single_point"
    functional: str = "PBEsol"
    pseudo_mode: str = "efficiency"


class _Hints(BaseModel):
    """Operator hint fields."""

    model_config = ConfigDict(extra="forbid", strict=True)

    k_spacing: float | None = None
    k_grid: list[int] | None = None
    smearing_type: SmearingType | None = None
    smearing_width_ry: float | None = None
    spin_polarized: bool | None = None
    spin_orbit_coupling: bool | None = None
    pseudo_mode: str | None = None
    pseudo_type: str | None = None
    relativistic_mode: str | None = None
    conv_thr: float | None = None
    mixing_beta: float | None = None
    electron_maxstep: int | None = None
    use_vdw: bool | None = None
    vdw_method: VdwMethod | None = None


class _PseudoMetadata(BaseModel):
    """Pseudopotential metadata accepted by the Core contract."""

    model_config = ConfigDict(extra="forbid", strict=True)

    filepath: str
    filename: str
    header_format: str
    library: str | None = None
    source_set: str | None = None
    element: str | None = None
    pseudo_type: str | None = None
    functional: str | None = None
    relativistic: str | None = None
    z_valence: float | None = None
    pseudo_info: dict[str, Any] = Field(default_factory=dict)
    is_sssp: bool = False
    source_pseudopotential: str | None = None
    sssp_recommended_cutoff: dict[str, Any] | None = None


class _KmeshModel(BaseModel):
    """Optional local k-mesh model specification."""

    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    version: str
    model_type: ModelType
    target: str
    feature_set: str
    source: ModelSource
    location: str
    revision: str | None = None


def _body(
    structure: str | _InlineStructure,
    intent: _Intent | None,
    hints: _Hints | None,
    pseudo_metadata: list[_PseudoMetadata] | None,
    pseudo_root: str | None,
    kmesh_model: _KmeshModel | None,
) -> dict[str, Any]:
    """Build the shared parser's mapping from typed MCP arguments."""
    body: dict[str, Any] = {
        "structure": (
            structure.model_dump(exclude_none=True)
            if isinstance(structure, BaseModel)
            else structure
        )
    }
    for name, value in (
        ("intent", intent),
        ("hints", hints),
        ("pseudo_metadata", pseudo_metadata),
        ("pseudo_root", pseudo_root),
        ("kmesh_model", kmesh_model),
    ):
        if value is None:
            continue
        if isinstance(value, BaseModel):
            body[name] = value.model_dump(exclude_none=True)
        elif isinstance(value, list) and value and isinstance(value[0], BaseModel):
            body[name] = [item.model_dump(exclude_none=True) for item in value]
        else:
            body[name] = value
    return body


def _run(body: dict[str, Any], service: CoreService) -> dict[str, Any]:
    """Parse, dispatch, and serialize one MCP call."""
    request = from_dict(body)
    if isinstance(request, QueryRequest):
        return service.compute(request).to_dict()
    return service.run_preset(request).to_dict()


def create_server(
    service: CoreService | None = None, *, name: str = "goldilocks-core"
) -> MCPServer:
    """Create an MCP server, optionally using a caller-owned service."""
    owns_service = service is None
    state = service if service is not None else CoreService()

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
            "Recommend or generate DFT inputs, or compute selected Core records."
        ),
        lifespan=lifespan,
    )

    @server.tool(description="List every registered Core task with stages and presets.")
    async def list_tasks() -> dict[str, Any]:
        return {"tasks": [task.to_dict() for task in state.describe_tasks()]}

    @server.tool(description="List target DFT codes with registered input writers.")
    async def list_codes() -> dict[str, Any]:
        return {"codes": list(state.describe_codes())}

    @server.tool(description="List available k-mesh models known to the runtime.")
    async def list_models() -> dict[str, Any]:
        return {"models": state.describe_models()}

    @server.tool(description="Run the recommend preset and return CoreResult JSON.")
    async def recommend(
        structure: str | _InlineStructure,
        intent: _Intent | None = None,
        hints: _Hints | None = None,
        pseudo_metadata: list[_PseudoMetadata] | None = None,
        pseudo_root: str | None = None,
        kmesh_model: _KmeshModel | None = None,
    ) -> dict[str, Any]:
        body = _body(
            structure, intent, hints, pseudo_metadata, pseudo_root, kmesh_model
        )
        body["mode"] = "recommend"
        return await asyncio.to_thread(_run, body, state)

    @server.tool(description="Run the generate preset and return CoreResult JSON.")
    async def generate(
        structure: str | _InlineStructure,
        intent: _Intent | None = None,
        hints: _Hints | None = None,
        pseudo_metadata: list[_PseudoMetadata] | None = None,
        pseudo_root: str | None = None,
        output_dir: str | None = None,
        kmesh_model: _KmeshModel | None = None,
    ) -> dict[str, Any]:
        body = _body(
            structure, intent, hints, pseudo_metadata, pseudo_root, kmesh_model
        )
        body["mode"] = "generate"
        if output_dir is not None:
            body["output_dir"] = output_dir
        return await asyncio.to_thread(_run, body, state)

    @server.tool(description="Compute selected Core record types.")
    async def compute(
        structure: str | _InlineStructure,
        outputs: list[_OutputName],
        intent: _Intent | None = None,
        hints: _Hints | None = None,
        pseudo_metadata: list[_PseudoMetadata] | None = None,
        pseudo_root: str | None = None,
        kmesh_model: _KmeshModel | None = None,
    ) -> dict[str, Any]:
        body = _body(
            structure, intent, hints, pseudo_metadata, pseudo_root, kmesh_model
        )
        body["outputs"] = outputs
        return await asyncio.to_thread(_run, body, state)

    return server


def serve() -> None:
    """Run the MCP server over stdio."""
    create_server().run("stdio")
