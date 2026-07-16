"""Synchronous MCP transport over the fixed Core pipeline.

This is a **transport only**. It maps constrained tool arguments to a
``CoreJobRequest`` via the shared ``parse_core_job_request`` deserializer, runs
it through one long-lived ``CoreRuntime``, and returns strict ``CoreResult``
JSON. It owns no auth, sessions, multi-tenant isolation, job queues,
persistence, file uploads beyond inline structure text, arbitrary execution,
downloads, containers, frontend, or job management. Those belong in the
application layer (``goldilocks``/``goldilocks-api``).

Sync tool calls: one runtime for the process lifetime, reused across tool
calls, closed on shutdown. No per-call ``CoreRuntime`` or ``Pipeline``
construction.

Tool arguments are **not validated by the MCP SDK**. The server is built on
the public low-level ``mcp.server.Server``. Tools are registered through the
public ``@server.list_tools`` and ``@server.call_tool(validate_input=False)``
extension points: ``list_tools`` publishes the hand-built constrained
``inputSchema`` (root ``additionalProperties: false``, Core contract enums and
field sets) and ``call_tool`` is invoked with the untouched client argument
dict (``validate_input=False`` disables the SDK's jsonschema pre-validation).
Every field is therefore routed through the shared ``parse_core_job_request``
deserializer and the ``from_dict`` constructors on the Core contracts. That
deserializer is the single source of truth: it rejects unknown root keys
(including ``mode`` and ``output_dir`` on the wrong tool), rejects explicit
``null`` for ``intent``/``hints``/``pseudo_metadata`` (a supplied ``null`` is
malformed, not omitted), and performs ``isinstance``-based strict validation
with no coercion of booleans, strings, or floats. A stage ``ValueError`` is
redacted to ``internal_error`` so internal model/config paths never leak; only
the client-relative bundle destination is echoed.

The published ``inputSchema`` is still constrained: it is generated from
per-tool root Pydantic models with ``extra="forbid"`` (root
``additionalProperties: false``) and the Core contract ``Literal`` aliases
(``CodeName``, ``CalcTask``, ``VdwMethod``, structure ``format``) and
``CoreJobRequest`` / ``CalculationHints`` / ``PseudoMetadata`` field sets, so
agents get constrained inputs. These schema models only shape the published
schema; they never validate arguments. ``mode`` is selected by the tool, not
the body; ``accuracy_level`` is absent (removed from contracts).

Because SDK pre-validation is disabled, every client input failure (request,
path, stage, internal) is returned as the stable MCP ``isError`` JSON body
``{"error": {"kind": ..., "message": ...}}`` documented for this server, never
as SDK-generated ``Error executing tool ...`` prose.

This Core-level MCP exposes the **full Core pipeline** (recommend / generate /
bundle / analyze). It is deliberately distinct from the ``goldilocks-mcp``
repository, which exposes the ML k-point *models* only. Merging them would
couple Core's release cadence to the model-exposing repo and pull model-only
tools into a pipeline transport. They may share a host process at deploy time;
they do not share a package.

**Transport scope (v1): stdio only.** The server runs over the public
``mcp.server.stdio.stdio_server`` primitive — the agent-native path used by LLM
hosts (Claude Desktop and similar). HTTP-style transports (``sse`` /
``streamable-http``) are deliberately not exposed here: the MCP Python SDK only
offers those through the FastMCP high-level wrapper, whose raw-argument
extension points are internal/unsupported, and this transport refuses to depend
on those internals. Operators needing network exposure should terminate TLS
and front stdio with a small adapter in the application layer.

MCP dependencies (the ``mcp`` SDK) live behind the optional ``[mcp]`` extra.
``import goldilocks_core`` does not import this module. Install with
``uv sync --extra mcp`` or ``pip install goldilocks-core[mcp]``.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from anyio import to_thread

from goldilocks_core.analysis import analyze_structure
from goldilocks_core.contracts import (
    CalcTask,
    CodeName,
    CoreResult,
    JobMode,
    VdwMethod,
)
from goldilocks_core.jobs import CoreRuntime
from goldilocks_core.pseudo.pp_metadata import PseudoMetadata
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata
from goldilocks_core.server.request import (
    RequestError,
    parse_core_job_request,
    resolve_structure,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# MCP SDK imports are guarded so importing this module without the ``[mcp]``
# extra does not crash; ``create_server``/``serve`` raise a clear install hint
# before any tool is built. Only public, documented SDK surfaces are used:
# ``mcp.server.Server`` (low-level server), ``mcp.server.stdio.stdio_server``
# (stdio primitive), and ``mcp.types`` protocol types (``Tool``,
# ``CallToolResult``, ``TextContent``). Pydantic ships with the ``mcp``
# distribution and is used only for the published schema view models.
try:  # pragma: no cover - import availability is environment-dependent
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import CallToolResult, TextContent, Tool
    from pydantic import BaseModel, ConfigDict, Field
except ImportError:  # pragma: no cover - import availability is environment-dependent
    Server = None  # type: ignore[assignment]
    stdio_server = None  # type: ignore[assignment]
    Tool = None  # type: ignore[assignment]
    CallToolResult = None  # type: ignore[assignment]
    TextContent = None  # type: ignore[assignment]
    BaseModel = None  # type: ignore[assignment]
    ConfigDict = None  # type: ignore[assignment]
    Field = None  # type: ignore[assignment]

__all__ = ["create_server", "serve"]


_MISSING_MCP_EXTRA = (
    "goldilocks-core MCP transport requires the optional '[mcp]' extra. "
    "Install it with `uv sync --extra mcp` or `pip install goldilocks-core[mcp]`."
)

# Error-kind vocabulary shared with the HTTP transport so clients see one
# deterministic shape across Core transports.
_KIND_INVALID = "invalid_request"
_KIND_NOT_FOUND = "not_found"
_KIND_STAGE = "stage_error"
_KIND_INTERNAL = "internal_error"

# Pipeline mode selected by tool name. ``analyze`` is handled separately (it
# runs the stateless Analyze stage only and does not consult the runtime).
_TOOL_MODES: dict[str, JobMode] = {
    "recommend": "recommend",
    "generate": "generate",
    "bundle": "bundle",
}

# ``analyze`` accepts only ``structure`` at the root; any other key (``mode``,
# ``output_dir``, ``intent``, ...) is rejected as ``invalid_request``. The
# pipeline tools (``recommend`` / ``generate`` / ``bundle``) delegate root-key
# rejection to the shared parser's ``_reject_unknown_top_level``, which refuses
# ``mode`` always and ``output_dir`` outside ``bundle``.
_ANALYZE_TOP_LEVEL: frozenset[str] = frozenset({"structure"})


def _require_mcp_extra() -> None:
    """Raise a clear install hint if the optional MCP extra is absent."""
    if (
        Server is None
        or stdio_server is None
        or Tool is None
        or CallToolResult is None
        or TextContent is None
    ):
        raise ImportError(_MISSING_MCP_EXTRA)


# --- Schema view models -----------------------------------------------------
#
# Pydantic view objects mirroring the Core contract field sets. These models are
# used ONLY to generate the published ``inputSchema``. They never validate tool
# arguments: that is the shared deserializer's job. ``Literal`` fields are
# imported from ``contracts`` so the generated schemas carry the constrained
# enums (``CodeName``, ``CalcTask``, ``VdwMethod``) from the same source the
# contract validates against. ``extra="forbid"`` makes every schema object
# (root and the named nested models) express ``additionalProperties: false``.
#
# Two nested fields are **intentional free-form metadata-map exceptions**, not
# closed objects: ``PseudoMetadataArg.pseudo_info`` and
# ``PseudoMetadataArg.sssp_recommended_cutoff`` publish
# ``type: object, additionalProperties: true`` because the Core
# ``PseudoMetadata`` contract models them as ``dict[str, Any]`` (raw UPF header
# metadata and raw SSPSS cutoff maps whose keys are not part of the Core
# contract). Every other root and nested published schema object is closed.
# These two maps are still validated at runtime: ``PseudoMetadata.from_dict``
# requires them to be JSON objects (rejecting non-object values with a stable
# ``invalid_request``) and rejects any unknown *typed* ``PseudoMetadata`` key.
# The free-form *contents* of these two maps are accepted by contract design.


class StructureArg(BaseModel):
    """Structure input: inline text or an allowlisted server-side path.

    Exactly one of ``content`` or ``path`` is required (enforced by the shared
    ``resolve_structure`` deserializer, not by this schema). ``format`` is only
    accepted with inline ``content``.
    """

    model_config = ConfigDict(extra="forbid")
    content: str | None = None
    format: Literal["cif", "poscar"] | None = None
    path: str | None = None


class IntentArg(BaseModel):
    """Operator intent, mirroring ``CalculationIntent``."""

    model_config = ConfigDict(extra="forbid")
    code: CodeName = "quantum_espresso"
    task: CalcTask = "scf_single_point"
    functional: str = "PBE"
    pseudo_mode: str = "efficiency"


class HintsArg(BaseModel):
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
    vdw_method: VdwMethod | None = None


class PseudoMetadataArg(BaseModel):
    """Pseudopotential metadata, mirroring ``PseudoMetadata.from_dict``.

    ``pseudo_info`` and ``sssp_recommended_cutoff`` are the two intentional
    free-form metadata-map exceptions (``dict[str, Any]``): their published
    schemas are open objects (``additionalProperties: true``) because their keys
    are raw UPF/SSSP header data outside the Core contract. All other fields are
    closed; ``PseudoMetadata.from_dict`` validates types and rejects unknown
    typed keys at runtime.
    """

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


# Per-tool root argument models. Their JSON schemas are the published
# ``inputSchema``. ``extra="forbid"`` makes the root object strict
# (``additionalProperties: false``). ``mode`` is never a field (the tool selects
# it). ``output_dir`` appears only on ``bundle``. ``analyze`` takes only
# ``structure``. These models never validate arguments.


class _PipelineArgs(BaseModel):
    """Root arguments for ``recommend`` / ``generate``."""

    model_config = ConfigDict(extra="forbid")
    structure: StructureArg
    intent: IntentArg | None = None
    hints: HintsArg | None = None
    pseudo_metadata: list[PseudoMetadataArg] | None = None


class _BundleArgs(BaseModel):
    """Root arguments for ``bundle`` (adds ``output_dir``)."""

    model_config = ConfigDict(extra="forbid")
    structure: StructureArg
    output_dir: str
    intent: IntentArg | None = None
    hints: HintsArg | None = None
    pseudo_metadata: list[PseudoMetadataArg] | None = None


class _AnalyzeArgs(BaseModel):
    """Root arguments for ``analyze`` (structure facts only)."""

    model_config = ConfigDict(extra="forbid")
    structure: StructureArg


def _build_tool_definitions() -> list[Tool]:
    """Build the four constrained Core pipeline tool definitions.

    Each tool publishes a constrained ``inputSchema`` (root
    ``additionalProperties: false``, contract enums and field sets) generated
    from the schema root models. Arguments are never validated against these
    schemas: ``call_tool`` is registered with ``validate_input=False`` so the
    untouched client argument dict is forwarded to the shared deserializer,
    which is the single validator.
    """
    assert Tool is not None

    return [
        Tool(
            name="recommend",
            description=(
                "Run Load → Analyze → Advise → Kmesh → Select and return strict "
                "CoreResult JSON (stages end at 'select'). Provenance and warnings "
                "are always preserved."
            ),
            inputSchema=_PipelineArgs.model_json_schema(),
        ),
        Tool(
            name="generate",
            description=(
                "Run the pipeline through Generate and return strict CoreResult "
                "JSON with generated input files."
            ),
            inputSchema=_PipelineArgs.model_json_schema(),
        ),
        Tool(
            name="bundle",
            description=(
                "Run the full pipeline and publish a portable bundle directory "
                "under the configured bundle root. Returns strict CoreResult JSON "
                "with a bundle record; bundle.path is server-relative."
            ),
            inputSchema=_BundleArgs.model_json_schema(),
        ),
        Tool(
            name="analyze",
            description=(
                "Run the Analyze stage only and return the StructureAnalysisRecord "
                "JSON (formula, elements, symmetry, heavy/magnetic candidates, "
                "dimensionality, electronic character, disorder warnings). A thin "
                "fact tool for agents that want structure facts before a full run."
            ),
            inputSchema=_AnalyzeArgs.model_json_schema(),
        ),
    ]


# --- Server state and lifecycle ----------------------------------------------


class _ServerConfig:
    """Immutable construction config captured before the lifespan runs."""

    def __init__(
        self,
        *,
        provided_runtime: CoreRuntime | None,
        pseudo_root: Path | None,
        structure_root: Path | None,
        bundle_root: Path,
        model: str | None,
        model_name: str | None,
        model_version: str | None,
        heuristic_kpoints: bool,
    ) -> None:
        """Store config; the runtime is created during lifespan startup."""
        self.provided_runtime = provided_runtime
        self.pseudo_root = pseudo_root
        self.structure_root = structure_root
        self.bundle_root = bundle_root
        self.model = model
        self.model_name = model_name
        self.model_version = model_version
        self.heuristic_kpoints = heuristic_kpoints


class _ServerState:
    """Mutable lifespan state holding the runtime and loaded defaults."""

    def __init__(self, config: _ServerConfig) -> None:
        """Store config; the runtime is created during startup."""
        self._config = config
        self.runtime: CoreRuntime | None = None
        self.structure_root = config.structure_root
        self.bundle_root = config.bundle_root
        self.default_pseudo_metadata: tuple[PseudoMetadata, ...] = ()
        # The server owns and closes a runtime only when the caller did not
        # provide one. A caller-provided runtime stays open for the caller.
        self._owns_runtime = config.provided_runtime is None

    def startup_runtime(self) -> None:
        """Build the runtime once (the app owns it unless a caller provided one)."""
        self.runtime = self._config.provided_runtime or _build_runtime(
            model=self._config.model,
            model_name=self._config.model_name,
            model_version=self._config.model_version,
            heuristic_kpoints=self._config.heuristic_kpoints,
        )

    def load_default_pseudo_metadata(self) -> None:
        """Load default pseudo metadata once; may fail, leaving the runtime closable."""
        self.default_pseudo_metadata = _load_default_pseudo_metadata(
            self._config.pseudo_root
        )

    def close(self) -> None:
        """Close the runtime only when the server owns it."""
        runtime = self.runtime
        if runtime is not None and self._owns_runtime and not runtime.is_closed:
            runtime.close()


def _load_default_pseudo_metadata(
    pseudo_root: Path | None,
) -> tuple[PseudoMetadata, ...]:
    """Load pseudopotential metadata once at startup, returning empty when unset."""
    if pseudo_root is None:
        return ()
    return tuple(load_pseudo_metadata(pseudo_root))


def _validate_backend_options(
    *,
    model: str | None,
    model_name: str | None,
    model_version: str | None,
    heuristic_kpoints: bool,
) -> None:
    """Reject backend-only metadata without a model and contradictory backends."""
    if model is not None and heuristic_kpoints:
        raise ValueError("--model and --heuristic-kpoints are mutually exclusive.")
    backend_only_options = [
        option
        for option, value in (
            ("--model-name", model_name),
            ("--model-version", model_version),
        )
        if value is not None
    ]
    if model is None and backend_only_options:
        options = " and ".join(backend_only_options)
        verb = "requires" if len(backend_only_options) == 1 else "require"
        raise ValueError(f"{options} {verb} --model")


def _build_runtime(
    *,
    model: str | None,
    model_name: str | None,
    model_version: str | None,
    heuristic_kpoints: bool,
) -> CoreRuntime:
    """Build a runtime whose pipeline mirrors the CLI backend composition."""
    from goldilocks_core.advisors import ml_kmesh_advisor
    from goldilocks_core.contracts import ModelSpec
    from goldilocks_core.jobs import Pipeline
    from goldilocks_core.kmesh import resolve_kpoints_from_advice

    pipeline: Pipeline | None
    if model is not None:
        spec = ModelSpec(
            name=model_name or "server-kmesh-model",
            version=model_version or "unknown",
            model_type="random_forest",
            target="k_index",
            feature_set="cslr",
            source="local",
            location=model,
        )
        pipeline = Pipeline(kmesh=ml_kmesh_advisor(spec))
    elif heuristic_kpoints:
        pipeline = Pipeline(kmesh=resolve_kpoints_from_advice)
    else:
        pipeline = None

    return CoreRuntime(pipeline=pipeline)


# --- Tool execution ---------------------------------------------------------


class _ToolError(Exception):
    """Carries a stable error kind and safe message out of the worker thread.

    Not a ``ValueError`` subclass: the worker must not let it collide with the
    stage ``ValueError`` redaction. The async tool wrapper translates it into an
    MCP ``isError`` result.
    """

    def __init__(self, kind: str, message: str) -> None:
        """Store the kind and message."""
        super().__init__(message)
        self.kind = kind
        self.message = message


def _execute_pipeline(
    mode: JobMode,
    body: dict[str, Any],
    public_output_dir: str | None,
    state: _ServerState,
) -> dict[str, Any]:
    """Parse, run, and serialize one tool call off the event loop.

    ``body`` is the untouched client argument dict, which is exactly the request
    body shape ``parse_core_job_request`` expects (``structure`` /
    ``intent`` / ``hints`` / ``pseudo_metadata`` / ``output_dir``). The shared
    deserializer rejects unknown root keys (including ``mode`` and ``output_dir``
    on the wrong tool), rejects explicit ``null`` for optional sections, and
    performs strict ``isinstance`` validation with no coercion. Stage
    ``ValueError`` is redacted to ``internal_error`` so internal model/config
    paths never leak; only the client-relative bundle destination is echoed.
    """
    runtime = state.runtime
    if runtime is None:  # pragma: no cover - lifespan invariant
        raise _ToolError(_KIND_INTERNAL, "internal error")
    try:
        core_request = parse_core_job_request(
            body,
            mode=mode,
            structure_root=state.structure_root,
            bundle_root=state.bundle_root,
            default_pseudo_metadata=state.default_pseudo_metadata,
        )
        result: CoreResult = runtime.run(core_request)
    except RequestError as error:
        raise _ToolError(error.kind, error.message) from None
    except FileExistsError as error:
        if mode != "bundle":
            raise _ToolError(_KIND_INTERNAL, "internal error") from error
        raise _ToolError(
            _KIND_STAGE, _bundle_destination_message(public_output_dir)
        ) from error
    except ValueError:
        # A ``ValueError`` from a pipeline stage is an internal stage failure
        # (model load, QRF runtime contract, generation internals). It must not
        # echo its message, which may carry absolute model/config paths. Client-
        # actionable request errors are ``RequestError`` (handled above) and the
        # bundle-destination ``FileExistsError`` is handled above with the public
        # path. Redact everything else deterministically.
        raise _ToolError(_KIND_INTERNAL, "internal error") from None
    except Exception:
        # ``ConfinedAccessFailure`` (server-side filesystem failures such as
        # ``EACCES``/``EMFILE``/``EIO``) and any unexpected error are redacted
        # without leaking host paths or internals.
        raise _ToolError(_KIND_INTERNAL, "internal error") from None

    content = result.to_dict()
    if mode == "bundle" and content.get("bundle") is not None:
        content["bundle"]["path"] = public_output_dir or ""
    return content


def _execute_analyze(
    arguments: dict[str, Any],
    state: _ServerState,
) -> dict[str, Any]:
    """Run the Analyze stage only and return the analysis record JSON.

    ``analyze_structure`` is a stateless fact-only stage with no model
    resources, so it does not consult the shared runtime. Structure loading is
    confined by the shared ``resolve_structure`` deserializer. Only
    ``structure`` is accepted at the root; any other key (``mode``,
    ``output_dir``, ``intent``, ...) is rejected as ``invalid_request``.
    """
    if not isinstance(arguments, dict):
        raise _ToolError(_KIND_INVALID, "Request arguments must be a JSON object.")
    unknown = sorted(set(arguments) - _ANALYZE_TOP_LEVEL)
    if unknown:
        raise _ToolError(
            _KIND_INVALID, f"Unknown request fields for analyze: {', '.join(unknown)}"
        )
    try:
        structure = resolve_structure(
            arguments.get("structure"), structure_root=state.structure_root
        )
        record = analyze_structure(structure)
    except RequestError as error:
        raise _ToolError(error.kind, error.message) from None
    except ValueError:
        raise _ToolError(_KIND_INTERNAL, "internal error") from None
    except Exception:
        raise _ToolError(_KIND_INTERNAL, "internal error") from None
    return record.to_dict()


def _public_bundle_output_dir(body: dict[str, Any]) -> str | None:
    """Return the client-supplied ``output_dir`` string, never the host path."""
    value = body.get("output_dir")
    return value if isinstance(value, str) else None


def _bundle_destination_message(public_output_dir: str | None) -> str:
    """Build a sanitized stage error for an existing bundle destination."""
    if public_output_dir:
        return f"bundle destination already exists: {public_output_dir}"
    return "bundle destination already exists"


def _success_result(content: dict[str, Any]) -> CallToolResult:
    """Build an MCP success result with strict CoreResult JSON text."""
    return CallToolResult(
        content=[
            TextContent(type="text", text=json.dumps(content, indent=2, default=str))
        ],
        isError=False,
    )


def _error_result(kind: str, message: str) -> CallToolResult:
    """Build an MCP ``isError`` result with a JSON error body."""
    body = {"error": {"kind": kind, "message": message}}
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(body))],
        isError=True,
    )


def _run_pipeline_mode(
    mode: JobMode,
    arguments: dict[str, Any],
    state: _ServerState,
) -> CallToolResult:
    """Validate and run one pipeline mode, returning a ``CallToolResult``.

    The tool function must never raise: any escape would become SDK
    ``Error executing tool ...`` prose. ``_execute_pipeline`` converts every
    expected failure to ``_ToolError``; this wrapper also nets any unexpected
    failure (including result serialization) as a redacted ``internal_error``.
    """
    public_output_dir = (
        _public_bundle_output_dir(arguments) if mode == "bundle" else None
    )
    try:
        content = _execute_pipeline(mode, arguments, public_output_dir, state)
        return _success_result(content)
    except _ToolError as error:
        return _error_result(error.kind, error.message)
    except Exception:
        return _error_result(_KIND_INTERNAL, "internal error")


def _run_analyze(
    arguments: dict[str, Any],
    state: _ServerState,
) -> CallToolResult:
    """Validate and run analyze, returning a ``CallToolResult``.

    Never raises; unexpected failures (including serialization) become a
    redacted ``internal_error`` rather than SDK prose.
    """
    try:
        content = _execute_analyze(arguments, state)
        return _success_result(content)
    except _ToolError as error:
        return _error_result(error.kind, error.message)
    except Exception:
        return _error_result(_KIND_INTERNAL, "internal error")


def _state(server: Server) -> _ServerState:
    """Return the lifespan-owned server state for this tool call.

    The low-level ``Server`` publishes the request's lifespan context through
    ``Server.request_context`` (a ``RequestContext`` whose
    ``lifespan_context`` is what the server lifespan yielded). Accessed inside
    the ``call_tool`` handler, where the request context is set.
    """
    state = server.request_context.lifespan_context
    if state is None:  # pragma: no cover - lifespan invariant
        raise RuntimeError("MCP server state is not initialized.")
    return state


# --- Server construction -----------------------------------------------------


def create_server(
    *,
    runtime: CoreRuntime | None = None,
    pseudo_root: str | Path | None = None,
    structure_root: str | Path | None = None,
    bundle_root: str | Path | None = None,
    model: str | None = None,
    model_name: str | None = None,
    model_version: str | None = None,
    heuristic_kpoints: bool = False,
    name: str = "goldilocks-core",
) -> Server:
    """Build the low-level MCP server with one server-owned CoreRuntime.

    The server is built on the public ``mcp.server.Server`` low-level API. Tools
    are registered through the public ``@server.list_tools`` and
    ``@server.call_tool(validate_input=False)`` decorators: the published
    ``inputSchema`` is the hand-built constrained schema, and ``call_tool``
    receives the untouched client argument dict (SDK jsonschema pre-validation
    disabled), forwarding it to the shared deserializer — the single validator.

    Args:
        runtime: Optional pre-built runtime. When omitted, the server owns a
            runtime built at startup from the backend composition options and
            closes it on shutdown. When provided, the caller owns it; the
            server does not close it.
        pseudo_root: Optional directory of UPF files loaded once at startup as
            the default pseudopotential metadata. Per-call ``pseudo_metadata``
            overrides it.
        structure_root: Optional allowlist root for server-side structure paths.
            Canonicalized at construction. When ``None``, only inline structure
            content is accepted.
        bundle_root: Root for bundle ``output_dir`` resolution, canonicalized at
            construction. Defaults to ``goldilocks_output``.
        model: Local ML Kmesh model path. Replaces the default QRF backend.
            Ignored when ``runtime`` is provided.
        model_name: Model name recorded in Kmesh provenance. Requires ``model``.
        model_version: Model version recorded in metadata. Requires ``model``.
        heuristic_kpoints: Use advice-based k-point resolution instead of the
            default QRF model. Ignored when ``runtime`` is provided.
        name: MCP server name.

    Returns:
        A low-level ``mcp.server.Server`` configured with the Core pipeline
        tools and a one-runtime lifespan.

    Raises:
        ImportError: If the ``[mcp]`` extra is not installed.
        ValueError: If backend composition options are invalid and no
            ``runtime`` is provided.
    """
    _require_mcp_extra()
    assert Server is not None

    _validate_backend_options(
        model=model,
        model_name=model_name,
        model_version=model_version,
        heuristic_kpoints=heuristic_kpoints,
    )

    config = _ServerConfig(
        provided_runtime=runtime,
        pseudo_root=Path(pseudo_root) if pseudo_root is not None else None,
        structure_root=(
            Path(structure_root).resolve() if structure_root is not None else None
        ),
        bundle_root=(
            Path(bundle_root) if bundle_root is not None else Path("goldilocks_output")
        ).resolve(),
        model=model,
        model_name=model_name,
        model_version=model_version,
        heuristic_kpoints=heuristic_kpoints,
    )

    @asynccontextmanager
    async def lifespan(server: Server) -> AsyncIterator[_ServerState]:
        """Own one CoreRuntime and default pseudo metadata for the process.

        The runtime is built before the ``try`` so a startup pseudo-load failure
        still closes the app-owned runtime in the ``finally`` (mirrors the HTTP
        transport).
        """
        del server
        state = _ServerState(config)
        state.startup_runtime()
        try:
            state.load_default_pseudo_metadata()
            yield state
        finally:
            state.close()

    server = Server(
        name=name,
        instructions=(
            "Goldilocks Core DFT input recommendation pipeline. "
            "Tools return strict CoreResult JSON. "
            "No auth, sessions, persistence, or execution of generated inputs."
        ),
        lifespan=lifespan,
    )

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        """Publish the four constrained Core pipeline tools."""
        return _build_tool_definitions()

    @server.call_tool(validate_input=False)
    async def _call_tool(tool_name: str, arguments: dict[str, Any]) -> CallToolResult:
        """Dispatch a tool call with untouched arguments to the shared parser.

        ``validate_input=False`` is the public extension point that delivers the
        raw client argument dict (unknown root keys and explicit ``null``
        preserved) without SDK jsonschema pre-validation. Execution is offloaded
        to a worker thread so blocking model inference / bundle I/O does not
        block the transport. The handler never raises: every failure becomes the
        stable ``isError`` JSON body, never SDK ``Error executing tool ...``
        prose.
        """
        try:
            state = _state(server)
            if tool_name == "analyze":
                return await to_thread.run_sync(_run_analyze, arguments, state)
            mode = _TOOL_MODES.get(tool_name)
            if mode is None:
                return _error_result(_KIND_INVALID, f"unknown tool: {tool_name}")
            return await to_thread.run_sync(_run_pipeline_mode, mode, arguments, state)
        except Exception:
            return _error_result(_KIND_INTERNAL, "internal error")

    return server


async def _serve_stdio(server: Server) -> None:
    """Run the server over the public stdio transport primitive.

    Reads JSON-RPC from stdin and writes JSON-RPC to stdout using the SDK's
    public ``mcp.server.stdio.stdio_server`` context manager and
    ``Server.run``. This is the only v1 transport; see the module docstring for
    why HTTP-style transports are intentionally not exposed here.
    """
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def serve(
    *,
    pseudo_root: str | Path | None = None,
    structure_root: str | Path | None = None,
    bundle_root: str | Path | None = None,
    model: str | None = None,
    model_name: str | None = None,
    model_version: str | None = None,
    heuristic_kpoints: bool = False,
) -> None:
    """Run the MCP server over stdio (CLI entry point).

    v1 exposes **stdio only** — the agent-native path used by LLM-agent hosts
    (Claude Desktop and similar). HTTP-style transports are not exposed; see the
    module docstring. Backend composition mirrors the ``goldilocks-core`` CLI
    and the HTTP ``serve`` command: default QRF model, ``--heuristic-kpoints``
    advice-based resolution, or ``--model`` local CSLR model. Composition is
    process configuration, not tool-call data. The serving path does not pass a
    pre-built runtime; the server owns the runtime built from these options and
    closes it on shutdown.

    Args:
        pseudo_root: Directory of UPF files for default pseudo metadata.
        structure_root: Allowlist root for server-side structure paths.
        bundle_root: Root for bundle output directories.
        model: Local ML Kmesh model path. Replaces the default QRF backend.
        model_name: Model name recorded in Kmesh provenance. Requires ``model``.
        model_version: Model version recorded in metadata. Requires ``model``.
        heuristic_kpoints: Use advice-based k-point resolution instead of the
            default QRF model.

    Raises:
        ImportError: If the ``[mcp]`` extra is not installed.
        ValueError: If backend-only metadata is supplied without ``model``,
            or ``model`` and ``heuristic_kpoints`` are both set.
    """
    _require_mcp_extra()
    _validate_backend_options(
        model=model,
        model_name=model_name,
        model_version=model_version,
        heuristic_kpoints=heuristic_kpoints,
    )
    server = create_server(
        pseudo_root=pseudo_root,
        structure_root=structure_root,
        bundle_root=bundle_root,
        model=model,
        model_name=model_name,
        model_version=model_version,
        heuristic_kpoints=heuristic_kpoints,
    )
    import anyio

    anyio.run(_serve_stdio, server)
