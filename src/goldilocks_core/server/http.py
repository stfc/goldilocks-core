"""FastAPI transport over one process-owned Core service.

Endpoints validate external inputs into native Core requests, dispatch through
one process-owned ``Service``, and serialize trusted results directly. Input
validation and named domain errors map to explicit 4xx responses; unexpected
defects remain 500 responses.
Behind the optional ``[http]`` extra; importing :mod:`goldilocks_core` never
imports FastAPI.

Scientific endpoints accept inline Structure Sources, intent, hints, a
registered pseudopotential-table ID, and a Preset or Record selection.
Pseudopotential contents, models, and publication locations are resolved from
the server's environment; request bodies never name server paths or loadable
artifacts.
"""

import json
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from goldilocks_core.runtime.service import OperationFailure, Service
from goldilocks_core.server.readiness import AssetReadiness

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
    static_root: str | Path | None = None,
) -> Any:
    try:
        from fastapi import FastAPI, Request
        from fastapi.exceptions import RequestValidationError
        from fastapi.responses import JSONResponse, Response
        from fastapi.staticfiles import StaticFiles
    except ImportError as error:
        raise ImportError(_MISSING_HTTP_EXTRA) from error
    from goldilocks_core.server.documents import (
        CapabilitiesDocument,
        ComputeRequestDocument,
        ErrorResponseDocument,
        InspectRequestDocument,
        StructureInspectionDocument,
        prepared_computation_document,
    )

    owns_service = service is None
    state = service if service is not None else Service()
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
    app.state.asset_readiness = readiness
    error_responses = {
        status: {"model": ErrorResponseDocument, "content": {"application/json": {}}}
        for status in (422, 424)
    }
    prepared_document = prepared_computation_document(state.capabilities()["tasks"])

    @app.get("/capabilities", response_model=CapabilitiesDocument)
    def capabilities() -> Response:
        return JSONResponse(state.capabilities_document())

    @app.post(
        "/inspect",
        response_model=StructureInspectionDocument,
        responses={422: {"model": ErrorResponseDocument}},
    )
    def inspect(body: InspectRequestDocument) -> Response:
        return JSONResponse(state.inspect_document(body.source))

    @app.post(
        "/compute",
        response_model=prepared_document,
        response_class=Response,
        responses={
            200: {
                "description": "Computation Result and its exact optional archive.",
                "content": {
                    "multipart/form-data": {
                        "schema": {"$ref": "#/components/schemas/PreparedComputation"}
                    }
                },
            },
            **error_responses,
        },
    )
    def compute(body: ComputeRequestDocument) -> Response:
        prepared = state.compute_document(body, prepare_archive=True)
        result = json.dumps(prepared.result, separators=(",", ":")).encode("utf-8")
        payload, media_type = _prepared_multipart(result, prepared.archive)
        return Response(payload, media_type=media_type)

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

    @app.exception_handler(OperationFailure)
    async def operation_failure_handler(
        request: Request, error: OperationFailure
    ) -> JSONResponse:
        del request
        if error.http_status is None:
            raise error.__cause__ or error
        return JSONResponse(
            status_code=error.http_status,
            content={"error": error.error},
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
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
    static_root: str | Path | None = None,
) -> None:
    try:
        import uvicorn
    except ImportError as error:
        raise ImportError(_MISSING_HTTP_EXTRA) from error
    uvicorn.run(
        create_app(
            static_root=static_root,
        ),
        host=host,
        port=port,
    )


def _prepared_multipart(result: bytes, archive: bytes | None) -> tuple[bytes, str]:
    payloads = (result,) if archive is None else (result, archive)
    while True:
        boundary = f"goldilocks-{secrets.token_hex(24)}"
        marker = boundary.encode("ascii")
        if all(marker not in payload for payload in payloads):
            break

    parts = [
        _multipart_part(
            boundary,
            name="result",
            filename="result.json",
            media_type="application/json",
            content=result,
        )
    ]
    if archive is not None:
        parts.append(
            _multipart_part(
                boundary,
                name="archive",
                filename="goldilocks-inputs.zip",
                media_type="application/zip",
                content=archive,
            )
        )
    parts.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(parts), f'multipart/form-data; boundary="{boundary}"'


def _multipart_part(
    boundary: str,
    *,
    name: str,
    filename: str,
    media_type: str,
    content: bytes,
) -> bytes:
    return (
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            f"Content-Type: {media_type}\r\n"
            "\r\n"
        ).encode("ascii")
        + content
        + b"\r\n"
    )
