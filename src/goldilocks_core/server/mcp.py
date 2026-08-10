"""MCP tools over one process-owned Core runtime."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Literal

try:
    from mcp.server.mcpserver import MCPServer
    from pydantic import BaseModel, ConfigDict, Field
except ImportError as error:
    raise ImportError(
        "The MCP transport requires goldilocks-core[mcp]. "
        "Install it with `uv sync --extra mcp`."
    ) from error

from goldilocks_core.contracts import ModelSource, ModelType, SmearingType, VdwMethod
from goldilocks_core.jobs import run_core_job
from goldilocks_core.runtime import CoreRuntime
from goldilocks_core.server.request import from_dict

__all__ = ["create_server", "serve"]

_OutputName = Literal[
    "analysis",
    "advice",
    "k_points",
    "selection",
    "generated_files",
]


class _InlineStructure(BaseModel):
    """Inline CIF or POSCAR content."""

    model_config = ConfigDict(extra="forbid")

    content: str
    format: Literal["cif", "poscar"] | None = None


class _Intent(BaseModel):
    """Calculation intent fields."""

    model_config = ConfigDict(extra="forbid")

    code: str = "quantum_espresso"
    task: str = "scf_single_point"
    functional: str = "PBEsol"
    pseudo_mode: str = "efficiency"


class _Hints(BaseModel):
    """Operator hint fields."""

    model_config = ConfigDict(extra="forbid")

    k_spacing: float | None = None
    k_grid: tuple[int, int, int] | None = None
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

    model_config = ConfigDict(extra="forbid")

    filename: str
    header_format: str
    filepath: str | None = None
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

    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    model_type: ModelType
    target: str
    feature_set: str
    source: ModelSource
    location: str
    revision: str | None = None


class _ServerState:
    """Runtime state shared by every tool call."""

    def __init__(self, runtime: CoreRuntime | None) -> None:
        self.runtime = runtime or CoreRuntime()
        self.owns_runtime = runtime is None

    def close(self) -> None:
        """Close a server-owned runtime."""
        if self.owns_runtime:
            self.runtime.close()


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


def _run(body: dict[str, Any], state: _ServerState) -> dict[str, Any]:
    """Parse, dispatch, and serialize one MCP call."""
    request = from_dict(body)
    return run_core_job(request, runtime=state.runtime).to_dict()


def create_server(
    runtime: CoreRuntime | None = None, *, name: str = "goldilocks-core"
) -> MCPServer:
    """Create an MCP server, optionally using a caller-owned runtime."""
    state = _ServerState(runtime)

    @asynccontextmanager
    async def lifespan(server: MCPServer):
        del server
        try:
            yield state
        finally:
            state.close()

    server = MCPServer(
        name=name,
        version="0.1.0",
        instructions=(
            "Recommend or generate DFT inputs, or compute selected Core records."
        ),
        lifespan=lifespan,
    )

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
        return _run(body, state)

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
        return _run(body, state)

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
        return _run(body, state)

    return server


def serve() -> None:
    """Run the MCP server over stdio."""
    create_server().run("stdio")
