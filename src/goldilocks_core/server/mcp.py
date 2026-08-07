"""MCP transport over the fixed Core pipeline.

This is a **transport only**. It maps constrained tool arguments to a
:class:`CoreJobRequest` via the shared :mod:`server.request` parser, runs it
through one long-lived :class:`CoreRuntime`, and returns strict ``CoreResult``
JSON. No auth, sessions, queues, persistence, or pod management live here.

One runtime for the process lifetime, reused across tool calls, closed on
shutdown. No per-call ``CoreRuntime`` is constructed.

MCP dependencies (the ``mcp`` SDK) live behind the optional ``[mcp]`` extra.
``import goldilocks_core`` does not import this module. Install with
``uv sync --extra mcp`` or ``pip install goldilocks-core[mcp]``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Literal

from goldilocks_core._lint import allow_swallow
from goldilocks_core.contracts.serial import to_jsonable
from goldilocks_core.runtime import CoreRuntime
from goldilocks_core.server.request import from_dict

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

__all__ = ["create_server", "serve"]


@allow_swallow
def _try_import_mcp_deps() -> tuple[Any, ...]:
    """Import MCP/Pydantic, returning Nones when the ``[mcp]`` extra is absent."""
    try:
        from mcp.server.mcpserver import MCPServer
        from pydantic import BaseModel, ConfigDict, Field
    except ImportError:
        return (None, None, None, None)
    return (MCPServer, BaseModel, ConfigDict, Field)


(
    MCPServer,
    BaseModel,
    ConfigDict,
    Field,
) = _try_import_mcp_deps()

_MISSING_MCP_EXTRA = (
    "goldilocks-core MCP transport requires the optional '[mcp]' extra. "
    "Install it with `uv sync --extra mcp` or `pip install goldilocks-core[mcp]`."
)


def _require_mcp_extra() -> None:
    """Raise a clear install hint if the optional MCP extra is absent."""
    if MCPServer is None or BaseModel is None:
        raise ImportError(_MISSING_MCP_EXTRA)


# --- Schema view models -----------------------------------------------------
#
# Pydantic view objects mirroring the Core contract field sets. These models
# generate the published ``inputSchema`` via FastMCP's schema generation, so
# agents get constrained choices. ``extra="forbid"`` makes every schema object
# strict (``additionalProperties: false``). Argument validation is then routed
# through the shared ``from_dict`` deserializer — the single validator — which
# rejects unknown keys, bad types, and constructs the ``CoreJobRequest``.
# ``mode`` is selected by the tool, not the body.


if BaseModel is not None:

    class _StructureArg(BaseModel):
        """Structure input: a path string or inline content object."""

        model_config = ConfigDict(extra="forbid")

        path: str | None = None
        content: str | None = None
        format: Literal["cif", "poscar"] | None = None

    class _IntentArg(BaseModel):
        """Operator intent, mirroring ``CalculationIntent``."""

        model_config = ConfigDict(extra="forbid")

        code: str = "quantum_espresso"
        task: str = "scf_single_point"
        functional: str = "PBEsol"
        pseudo_mode: str = "efficiency"

    class _HintsArg(BaseModel):
        """Operator overrides, mirroring ``CalculationHints``."""

        model_config = ConfigDict(extra="forbid")

        k_spacing: float | None = None
        k_grid: tuple[int, int, int] | None = None
        smearing_type: str | None = None
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
        vdw_method: str | None = None

    class _PseudoMetadataArg(BaseModel):
        """Pseudopotential metadata entry, mirroring ``PseudoMetadata``."""

        model_config = ConfigDict(extra="forbid")

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

    class _ModelSpecArg(BaseModel):
        """Local k-index model spec, mirroring ``ModelSpec``."""

        model_config = ConfigDict(extra="forbid")

        name: str
        version: str
        model_type: str = "random_forest"
        target: str = "k_index"
        feature_set: str = "cslr"
        source: str = "local"
        location: str
        revision: str | None = None

    class _PipelineArgs(BaseModel):
        """Root arguments for ``recommend`` / ``generate``."""

        model_config = ConfigDict(extra="forbid")

        structure: _StructureArg
        intent: _IntentArg | None = None
        hints: _HintsArg | None = None
        pseudo_metadata: list[_PseudoMetadataArg] | None = None
        pseudo_root: str | None = None
        output_dir: str | None = None
        kmesh_model: _ModelSpecArg | None = None

    class _StageArgs(BaseModel):
        """Root arguments for raw stage tools (``analyze`` / ``kmesh`` / ...)."""

        model_config = ConfigDict(extra="forbid")

        structure: _StructureArg
        intent: _IntentArg | None = None
        hints: _HintsArg | None = None
        pseudo_metadata: list[_PseudoMetadataArg] | None = None
        pseudo_root: str | None = None
        kmesh_model: _ModelSpecArg | None = None


def _flatten_args(args: BaseModel) -> dict[str, Any]:
    """Flatten a pydantic argument model into the raw request dict shape.

    Drops ``None`` values so absent optional fields are treated as "use
    default" by :func:`from_dict`. Unpacks the nested ``structure`` model
    into the path-string or content-object shape the parser expects.
    """
    raw = args.model_dump(exclude_none=True)
    structure = raw.pop("structure", None)
    if isinstance(structure, dict):
        if structure.get("path") is not None:
            raw["structure"] = structure["path"]
        else:
            raw["structure"] = {
                key: value
                for key in ("content", "format")
                if (value := structure.get(key)) is not None
            }
    return raw


def _run_entrypoint(
    entrypoint: str,
    body: dict[str, Any],
    runtime: CoreRuntime,
) -> dict[str, Any]:
    """Parse, run, and serialize one tool call."""
    request = from_dict(body)
    if entrypoint == "generate":
        result = runtime.generate(request, output_dir=request.output_dir)
    else:
        result = getattr(runtime, entrypoint)(request)
    return to_jsonable(result)  # type: ignore[return-value]


def create_server(
    runtime: CoreRuntime | None = None,
    *,
    name: str = "goldilocks-core",
) -> MCPServer:
    """Build the MCP server with one server-owned ``CoreRuntime``.

    Args:
        runtime: Optional pre-built runtime. When omitted, the server owns a
            runtime created at startup and closes it on shutdown. When
            provided, the caller owns it; the server does not close it.
        name: MCP server name.

    Returns:
        An ``MCPServer`` configured with the six Core pipeline tools.

    Raises:
        ImportError: If the ``[mcp]`` extra is not installed.
    """
    _require_mcp_extra()
    assert MCPServer is not None

    state = _ServerState(provided_runtime=runtime)

    @asynccontextmanager
    async def lifespan(server: MCPServer) -> AsyncIterator[_ServerState]:
        """Own one CoreRuntime for the process lifetime."""
        del server
        state.runtime = state.provided_runtime or CoreRuntime()
        try:
            yield state
        finally:
            state.close()

    server = MCPServer(
        name=name,
        version="0.1.0",
        instructions=(
            "Goldilocks Core DFT input recommendation pipeline. "
            "Tools return strict CoreResult or stage-record JSON. "
            "No auth, sessions, persistence, or execution of generated inputs."
        ),
        lifespan=lifespan,
    )

    @server.tool(
        description=(
            "Run Load → Analyze → Advise → Kmesh → Select; return CoreResult JSON."
        )
    )
    async def recommend(args: _PipelineArgs) -> dict[str, Any]:
        """Full recommendation through Select (no generated files)."""
        return _run_entrypoint("recommend", _flatten_args(args), _runtime(state))

    @server.tool(
        description=(
            "Run the pipeline through Generate; return CoreResult JSON "
            "with generated files."
        )
    )
    async def generate(args: _PipelineArgs) -> dict[str, Any]:
        """Full pipeline through Generate, optionally writing a bundle."""
        return _run_entrypoint("generate", _flatten_args(args), _runtime(state))

    @server.tool(
        description="Run Load → Analyze and return the StructureAnalysisRecord JSON."
    )
    async def analyze(args: _StageArgs) -> dict[str, Any]:
        """Structure facts only (formula, elements, dimensionality, ...)."""
        return _run_entrypoint("analyze", _flatten_args(args), _runtime(state))

    @server.tool(description="Run the Kmesh stage and return the KPointSelection JSON.")
    async def kmesh(args: _StageArgs) -> dict[str, Any]:
        """Concrete k-point grid from hints or the model backend."""
        return _run_entrypoint("kmesh", _flatten_args(args), _runtime(state))

    @server.tool(
        description="Run Load → Analyze → Advise and return the ParameterAdvice JSON."
    )
    async def advise(args: _StageArgs) -> dict[str, Any]:
        """Provenance-backed parameter recommendations."""
        return _run_entrypoint("advise", _flatten_args(args), _runtime(state))

    @server.tool(
        description=(
            "Run Load → Analyze → Advise → Select and return the SelectionRecord JSON."
        )
    )
    async def select(args: _StageArgs) -> dict[str, Any]:
        """Concrete pseudopotential selections and cutoffs."""
        return _run_entrypoint("select", _flatten_args(args), _runtime(state))

    return server


def serve() -> None:
    """Run the MCP server over stdio (CLI entry point).

    Raises:
        ImportError: If the ``[mcp]`` extra is not installed.
    """
    _require_mcp_extra()
    import anyio

    server = create_server()
    anyio.run(server.run_stdio_async)


class _ServerState:
    """Mutable lifespan state holding the runtime."""

    def __init__(self, *, provided_runtime: CoreRuntime | None) -> None:
        """Store the optional provided runtime; the owned one is built at startup."""
        self.provided_runtime = provided_runtime
        self.runtime: CoreRuntime | None = None
        self._owns_runtime = provided_runtime is None

    def close(self) -> None:
        """Close the runtime only when the server owns it."""
        runtime = self.runtime
        if runtime is not None and self._owns_runtime and not runtime.is_closed:
            runtime.close()


def _runtime(state: _ServerState) -> CoreRuntime:
    """Return the runtime, creating it lazily if the lifespan hasn't run yet.

    Over a real transport the lifespan sets ``state.runtime`` at startup. For
    in-process ``call_tool`` testing (no lifespan), the runtime is created on
    first use so tool calls work without a transport.
    """
    if state.runtime is None:
        state.runtime = state.provided_runtime or CoreRuntime()
    return state.runtime
