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

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from goldilocks_core.analysis import DimensionalityClassificationError
from goldilocks_core.assets import AssetCorrupt, AssetNotInstalled
from goldilocks_core.generation import GenerationError
from goldilocks_core.io.structures import StructureInputError
from goldilocks_core.pseudo.source import PseudoTableMismatch
from goldilocks_core.runtime import UnavailableRecord, UnknownPreset, UnknownTask
from goldilocks_core.runtime.service import Service
from goldilocks_core.server.capacity import (
    ComputationCapacity,
    ServerBusy,
    configured_compute_wait_seconds,
)
from goldilocks_core.server.readiness import AssetReadiness
from goldilocks_core.server.request import RequestError

__all__ = ["create_app", "serve"]

_MISSING_HTTP_EXTRA = (
    "The HTTP transport requires goldilocks-core[http]. "
    "Install it with `uv sync --extra http`."
)
WORKBENCH_STATIC_ROOT_ENV = "GOLDILOCKS_WORKBENCH_STATIC_ROOT"


def _workbench_static_root(value: str | Path | None) -> Path | None:
    configured = (
        value if value is not None else os.environ.get(WORKBENCH_STATIC_ROOT_ENV)
    )
    if configured is None:
        return None
    root = Path(configured).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Workbench static root is not a directory: {root}")
    if not (root / "index.html").is_file():
        raise FileNotFoundError(f"Workbench static root has no index.html: {root}")
    return root


def create_app(
    service: Service | None = None,
    *,
    compute_wait_seconds: float | None = None,
    static_root: str | Path | None = None,
) -> Any:
    try:
        from fastapi import FastAPI, Request
        from fastapi.exceptions import RequestValidationError
        from fastapi.responses import JSONResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as error:
        raise ImportError(_MISSING_HTTP_EXTRA) from error
    from goldilocks_core.server.http_contract import install_scientific_routes

    owns_service = service is None
    state = service if service is not None else Service()
    capacity = ComputationCapacity(
        configured_compute_wait_seconds(compute_wait_seconds)
    )
    readiness = AssetReadiness(
        state.runtime.asset_store,
        model_registry_path=getattr(state.runtime, "model_registry_path", None),
        pseudo_registry_path=getattr(state.runtime, "pseudo_registry_path", None),
    )
    workbench_static_root = _workbench_static_root(static_root)

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
    app.state.compute_capacity = capacity
    app.state.asset_readiness = readiness
    install_scientific_routes(app, state, capacity)

    @app.exception_handler(ServerBusy)
    async def server_busy_handler(request: Request, error: ServerBusy) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "kind": "server_busy",
                    "message": str(error),
                    "retryable": True,
                    "details": {"retry_after_seconds": error.retry_after_seconds},
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        del request
        validation_errors = [
            {
                "path": ".".join(str(part) for part in item["loc"]),
                "type": item["type"],
                "message": item["msg"],
            }
            for item in error.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "kind": "invalid_request",
                    "message": "The request does not match the transport contract.",
                    "retryable": False,
                    "details": {"validation_errors": validation_errors},
                }
            },
        )

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

    @app.exception_handler(UnknownPreset)
    async def unknown_preset_handler(
        request: Request, error: UnknownPreset
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=422,
            content={"error": {"kind": "invalid_preset", "message": str(error)}},
        )

    @app.exception_handler(UnavailableRecord)
    async def unavailable_record_handler(
        request: Request, error: UnavailableRecord
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=422,
            content={"error": {"kind": "invalid_record", "message": str(error)}},
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
                    "message": (
                        f"Runtime asset {error.reference.id}@{error.reference.version} "
                        f"{error.reason}."
                    ),
                    "asset_id": error.reference.id,
                    "version": error.reference.version,
                    "reason": error.reason,
                }
            },
        )

    @app.exception_handler(AssetCorrupt)
    async def asset_corrupt_handler(
        request: Request, error: AssetCorrupt
    ) -> JSONResponse:
        del request, error
        return JSONResponse(
            status_code=424,
            content={
                "error": {
                    "kind": "asset_corrupt",
                    "message": (
                        "A required runtime asset failed integrity verification."
                    ),
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

    @app.get("/health")
    def health() -> dict[str, str]:
        """Report process liveness."""
        return {"status": "ok"}

    @app.get("/ready")
    def ready() -> Any:
        report = readiness.check()
        if report.ready:
            return {"status": "ready", "asset_count": report.asset_count}
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "kind": "assets_unavailable",
                    "message": (
                        f"Required runtime asset {report.asset_id}@{report.version} "
                        f"is {report.state}."
                    ),
                    "retryable": False,
                    "details": {
                        "asset_id": report.asset_id,
                        "version": report.version,
                        "state": report.state,
                        "required_asset_count": report.asset_count,
                    },
                }
            },
        )

    if workbench_static_root is not None:
        app.mount(
            "/",
            StaticFiles(directory=workbench_static_root, html=True),
            name="workbench-static",
        )

    return app


def serve(
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    compute_wait_seconds: float | None = None,
    static_root: str | Path | None = None,
) -> None:
    try:
        import uvicorn
    except ImportError as error:
        raise ImportError(_MISSING_HTTP_EXTRA) from error
    uvicorn.run(
        create_app(
            compute_wait_seconds=compute_wait_seconds,
            static_root=static_root,
        ),
        host=host,
        port=port,
    )
