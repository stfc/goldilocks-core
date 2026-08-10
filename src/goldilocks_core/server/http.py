"""FastAPI transport over one process-owned Core runtime."""

from contextlib import asynccontextmanager
from typing import Any

from goldilocks_core.jobs import run_core_job
from goldilocks_core.runtime import CoreRuntime
from goldilocks_core.server.concurrency import ComputeGate
from goldilocks_core.server.config import DeploymentConfig
from goldilocks_core.server.errors import register_error_handlers
from goldilocks_core.server.request import RequestError, from_dict
from goldilocks_core.version import package_version

__all__ = ["create_app", "serve"]

_MISSING_HTTP_EXTRA = (
    "The HTTP transport requires goldilocks-core[http]. "
    "Install it with `uv sync --extra http`."
)

_HTTP_FORBIDDEN_FIELDS = frozenset({"output_dir", "pseudo_root", "kmesh_model"})
"""Server-path and model-selection concepts never allowed on the Workbench HTTP surface.

The browser sends inline structure content and identifies pseudos by
filename/library; it never chooses a server-side model or output location.
Python/CLI/MCP retain those capabilities through the shared parser.
"""


def _reject_workbench_server_paths(raw: dict[str, Any]) -> None:
    """Reject server-path concepts that never belong on the HTTP surface.

    The browser sends inline structure content and identifies pseudos by
    filename/library. Any path-shaped field is a misuse of the Workbench
    transport and is surfaced as a structured invalid_request failure.
    """
    for name in _HTTP_FORBIDDEN_FIELDS:
        if name in raw:
            raise RequestError(f"Field {name!r} is not allowed on the HTTP transport.")
    if isinstance(raw.get("structure"), str):
        raise RequestError(
            "Field 'structure' must be inline content, not a server path."
        )
    for entry in raw.get("pseudo_metadata") or ():
        if isinstance(entry, dict) and "filepath" in entry:
            raise RequestError(
                "Field 'pseudo_metadata.filepath' is not allowed on the HTTP transport."
            )


class _AppState:
    """Runtime state shared by every request to an application."""

    def __init__(self, runtime: CoreRuntime | None, config: DeploymentConfig) -> None:
        self.provided_runtime = runtime
        self.runtime: CoreRuntime | None = None
        self.owns_runtime = runtime is None
        self.gate = ComputeGate(config.compute_limit, config.compute_wait_seconds)
        self.pseudo_metadata = config.pseudo_metadata

    def close(self) -> None:
        """Close an application-owned runtime."""
        if self.owns_runtime and self.runtime is not None:
            self.runtime.close()


def create_app(
    runtime: CoreRuntime | None = None,
    config: DeploymentConfig | None = None,
) -> Any:
    """Create the HTTP app, optionally using a caller-owned runtime/config."""
    try:
        from fastapi import FastAPI

        from goldilocks_core.server.schemas import (
            ComputationRequest,
            CoreResultResponse,
            ErrorResponse,
            RecordQuery,
            RecordSetResponse,
            StructureDocumentModel,
            StructureSource,
            TaskCatalogueModel,
        )
    except ImportError as error:
        raise ImportError(_MISSING_HTTP_EXTRA) from error

    from goldilocks_core.io.structures import (
        load_structure_from_text,
        structure_to_document,
    )
    from goldilocks_core.server.static import mount_workbench

    config = config if config is not None else DeploymentConfig.from_environ()
    state = _AppState(runtime, config)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        del app
        state.runtime = state.provided_runtime or CoreRuntime()
        try:
            yield
        finally:
            state.close()

    app = FastAPI(title="goldilocks-core", lifespan=lifespan)
    app.state.goldilocks = state
    register_error_handlers(app)

    _ERROR_RESPONSES = {
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    }

    @app.get("/health", responses={200: {"description": "Process liveness"}})
    async def health() -> dict[str, str]:
        """Report process liveness without occupying a compute thread."""
        return {"status": "ok"}

    @app.post(
        "/structure/load",
        response_model=StructureDocumentModel,
        responses=_ERROR_RESPONSES,
    )
    def load_structure(body: StructureSource) -> dict[str, Any]:
        """Validate inline structure content and return a Structure Document."""
        try:
            structure = load_structure_from_text(body.content, body.format)
        except ValueError as error:
            raise RequestError(str(error)) from error
        return structure_to_document(structure, source_format=body.format).to_dict()

    @app.get("/tasks", response_model=TaskCatalogueModel, responses=_ERROR_RESPONSES)
    async def tasks() -> dict[str, Any]:
        """Describe every registered Core task with stable identifiers."""
        if state.runtime is None:
            raise RuntimeError("CoreRuntime is not initialized.")
        return {"tasks": [task.to_dict() for task in state.runtime.describe_tasks()]}

    @app.post(
        "/recommend", response_model=CoreResultResponse, responses=_ERROR_RESPONSES
    )
    def recommend(body: ComputationRequest) -> dict[str, Any]:
        """Run the recommend preset."""
        return _execute("recommend", body, state)

    @app.post(
        "/generate", response_model=CoreResultResponse, responses=_ERROR_RESPONSES
    )
    def generate(body: ComputationRequest) -> dict[str, Any]:
        """Run the generate preset and return generated input contents."""
        return _execute("generate", body, state)

    @app.post(
        "/compute",
        response_model=RecordSetResponse,
        responses=_ERROR_RESPONSES,
    )
    def compute(body: RecordQuery) -> dict[str, Any]:
        """Compute only the requested record types."""
        return _execute("compute", body, state)

    # Serve the built Workbench only when a build directory exists, and only
    # after every API route so the SPA fallback never shadows them.
    mount_workbench(app)

    return app


def _execute(endpoint: str, body: Any, state: _AppState) -> dict[str, Any]:
    """Parse, dispatch, and serialize one transport request."""
    raw = dict(body.model_dump(exclude_none=True))
    _reject_workbench_server_paths(raw)
    if endpoint in {"recommend", "generate"}:
        if raw.get("outputs") is not None:
            raise RequestError("Preset endpoints do not accept 'outputs'.")
        supplied_mode = raw.get("mode")
        if supplied_mode is not None and supplied_mode != endpoint:
            raise RequestError(
                f"Field 'mode' must be {endpoint!r} for POST /{endpoint}."
            )
        raw["mode"] = endpoint
    elif raw.get("outputs") is None:
        raise RequestError("POST /compute requires 'outputs'.")

    _inject_server_pseudo_metadata(raw, state)
    request = from_dict(raw)
    if state.runtime is None:
        raise RuntimeError("CoreRuntime is not initialized.")
    with state.gate:
        result = run_core_job(request, runtime=state.runtime).to_dict()
    if endpoint in {"recommend", "generate"}:
        result["core_version"] = package_version()
    return result


def _inject_server_pseudo_metadata(raw: dict[str, Any], state: _AppState) -> None:
    """Inject administrator-configured pseudo metadata when none is supplied.

    The browser never submits server paths; instead the operator configures
    pseudo metadata on the server (JSON manifest or mounted UPF root). When a
    request carries neither ``pseudo_metadata`` nor ``pseudo_root``, the
    configured metadata is added so recommendation/generation receive it.
    A request that supplies its own metadata is never overridden.
    """
    if not state.pseudo_metadata:
        return
    if "pseudo_metadata" in raw or "pseudo_root" in raw:
        return
    raw["pseudo_metadata"] = [metadata.to_dict() for metadata in state.pseudo_metadata]


def serve(*, host: str = "127.0.0.1", port: int = 8000) -> None:
    """Serve the HTTP transport with uvicorn."""
    try:
        import uvicorn
    except ImportError as error:
        raise ImportError(_MISSING_HTTP_EXTRA) from error
    uvicorn.run(create_app(), host=host, port=port)
