"""FastAPI transport over one process-owned Core service.

A thin stateless transport: each endpoint parses the body with the shared
deserializer, dispatches through one ``Service``
held for the process lifetime, and returns the result's JSON form. Stage
``ValueError``\\ s map to 4xx responses with the message preserved; parser
:class:`~goldilocks_core.server.request.RequestError`\\ s map to 422. Behind the
optional ``[http]`` extra; importing :mod:`goldilocks_core` never imports FastAPI.
``DimensionalityClassificationError`` (an ``Exception`` subclass, not
``ValueError``) is mapped explicitly to 422.

Endpoints accept only the calculation itself — an inline Structure Source,
intent, hints, and (for queries) the requested record types. Deployment
configuration is server-side: models, pseudopotentials, and output locations
are resolved from the server's own environment, so no request body names
server-side paths or loadable artifacts.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from goldilocks_core.analysis import DimensionalityClassificationError
from goldilocks_core.assets import AssetCorrupt, AssetNotInstalled
from goldilocks_core.contracts import QueryRequest
from goldilocks_core.generation import GenerationError
from goldilocks_core.io.structures import StructureInputError
from goldilocks_core.pseudo.source import PseudoTableMismatch
from goldilocks_core.runtime import UnknownTask
from goldilocks_core.runtime.service import Service
from goldilocks_core.server.request import RequestError, from_dict

__all__ = ["create_app", "serve"]

_MISSING_HTTP_EXTRA = (
    "The HTTP transport requires goldilocks-core[http]. "
    "Install it with `uv sync --extra http`."
)


def create_app(service: Service | None = None) -> Any:
    """Create the HTTP app, optionally using a caller-owned service."""
    try:
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse
    except ImportError as error:
        raise ImportError(_MISSING_HTTP_EXTRA) from error

    owns_service = service is None
    state = service if service is not None else Service()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        del app
        try:
            yield
        finally:
            if owns_service:
                state.close()

    app = FastAPI(title="goldilocks-core", lifespan=lifespan)
    app.state.goldilocks = state

    @app.exception_handler(RequestError)
    async def request_error_handler(
        request: Request, error: RequestError
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=422,
            content={"error": {"kind": "invalid_request", "message": str(error)}},
        )

    @app.exception_handler(UnknownTask)
    async def unknown_task_handler(
        request: Request, error: UnknownTask
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=422,
            content={"error": {"kind": "invalid_task", "message": str(error)}},
        )

    @app.exception_handler(StructureInputError)
    async def structure_input_handler(
        request: Request, error: StructureInputError
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=422,
            content={"error": {"kind": "invalid_structure", "message": str(error)}},
        )

    @app.exception_handler(GenerationError)
    async def generation_error_handler(
        request: Request, error: GenerationError
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=422,
            content={"error": {"kind": "generation_error", "message": str(error)}},
        )

    @app.exception_handler(DimensionalityClassificationError)
    async def dimensionality_error_handler(
        request: Request, error: DimensionalityClassificationError
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=422,
            content={"error": {"kind": "dimensionality_error", "message": str(error)}},
        )

    @app.exception_handler(AssetNotInstalled)
    async def asset_not_installed_handler(
        request: Request, error: AssetNotInstalled
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=424,
            content={
                "error": {
                    "kind": "asset_not_installed",
                    "message": str(error),
                    "asset_id": error.reference.id,
                    "version": error.reference.version,
                    "root": str(error.root),
                }
            },
        )

    @app.exception_handler(AssetCorrupt)
    async def asset_corrupt_handler(
        request: Request, error: AssetCorrupt
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=424,
            content={
                "error": {
                    "kind": "asset_corrupt",
                    "message": str(error),
                }
            },
        )

    @app.exception_handler(PseudoTableMismatch)
    async def pseudo_table_mismatch_handler(
        request: Request, error: PseudoTableMismatch
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "kind": "pseudo_table_mismatch",
                    "message": str(error),
                }
            },
        )

    @app.exception_handler(FileNotFoundError)
    async def not_found_handler(
        request: Request, error: FileNotFoundError
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=404,
            content={"error": {"kind": "not_found", "message": str(error)}},
        )

    @app.exception_handler(FileExistsError)
    async def output_conflict_handler(
        request: Request, error: FileExistsError
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=409,
            content={"error": {"kind": "output_conflict", "message": str(error)}},
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        """Report process liveness."""
        return {"status": "ok"}

    @app.get("/tasks")
    def tasks() -> dict[str, Any]:
        """List every registered Core task with stable stage and record ids."""
        return {"tasks": [task.to_dict() for task in state.describe_tasks()]}

    @app.get("/codes")
    def codes() -> dict[str, Any]:
        """List target DFT codes with registered input writers."""
        return {"codes": list(state.describe_codes())}

    @app.get("/models")
    def models() -> dict[str, Any]:
        """List available k-mesh models known to the runtime."""
        return {"models": state.describe_models()}

    @app.post("/recommend")
    def recommend(body: dict[str, Any]) -> dict[str, Any]:
        """Run the recommend preset."""
        return _execute("recommend", body, state)

    @app.post("/generate")
    def generate(body: dict[str, Any]) -> dict[str, Any]:
        """Run the generate preset and return generated files."""
        return _execute("generate", body, state)

    @app.post("/compute")
    def compute(body: dict[str, Any]) -> dict[str, Any]:
        """Compute only the requested record types."""
        return _execute("compute", body, state)

    return app


def _execute(endpoint: str, body: dict[str, Any], service: Service) -> dict[str, Any]:
    """Parse, dispatch, and serialize one transport request."""
    raw = dict(body)
    if endpoint == "compute":
        if raw.get("outputs") is None:
            raise RequestError("POST /compute requires 'outputs'.")
    else:
        if raw.get("outputs") is not None:
            raise RequestError("Preset endpoints do not accept 'outputs'.")
        supplied_mode = raw.get("mode")
        if supplied_mode is not None and supplied_mode != endpoint:
            raise RequestError(
                f"Field 'mode' must be {endpoint!r} for POST /{endpoint}."
            )
        raw["mode"] = endpoint

    request = from_dict(raw)
    if isinstance(request, QueryRequest):
        return service.compute(request).to_dict()
    return service.run_preset(request).to_dict()


def serve(*, host: str = "127.0.0.1", port: int = 8000) -> None:
    """Serve the HTTP transport with uvicorn."""
    try:
        import uvicorn
    except ImportError as error:
        raise ImportError(_MISSING_HTTP_EXTRA) from error
    uvicorn.run(create_app(), host=host, port=port)
