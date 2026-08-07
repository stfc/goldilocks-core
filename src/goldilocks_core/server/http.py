"""Synchronous stateless HTTP transport over the fixed Core pipeline.

This is a **transport only**. It maps a JSON request body to a
:class:`CoreJobRequest` via the shared :mod:`server.request` parser, runs it
through one long-lived :class:`CoreRuntime`, and returns ``CoreResult`` JSON.
No auth, sessions, queues, persistence, WebSockets, pod management, or
frontend live here.

Sync, stateless: one runtime for the process lifetime, reused across requests,
closed on shutdown. No per-request runtime is constructed.

HTTP dependencies (FastAPI + uvicorn) live behind the optional ``[http]``
extra. ``import goldilocks_core`` does not import this module. Install with
``uv sync --extra http`` or ``pip install goldilocks-core[http]``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from goldilocks_core._lint import allow_swallow
from goldilocks_core.contracts.serial import to_jsonable
from goldilocks_core.runtime import CoreRuntime
from goldilocks_core.server.request import RequestError, from_dict

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

__all__ = ["create_app", "serve"]


@allow_swallow
def _try_import_http_deps() -> tuple[Any, ...]:
    """Import FastAPI/Starlette, returning Nones when the ``[http]`` extra is absent."""
    try:
        from fastapi import FastAPI, Request
        from starlette.concurrency import run_in_threadpool
        from starlette.exceptions import HTTPException
        from starlette.responses import JSONResponse
    except ImportError:
        return (None, None, None, None, None)
    return (FastAPI, Request, run_in_threadpool, HTTPException, JSONResponse)


(
    FastAPI,
    Request,
    run_in_threadpool,
    HTTPException,
    JSONResponse,
) = _try_import_http_deps()

_MISSING_HTTP_EXTRA = (
    "goldilocks-core HTTP transport requires the optional '[http]' extra. "
    "Install it with `uv sync --extra http` or `pip install goldilocks-core[http]`."
)

_STATUS_FOR_KIND: dict[str, int] = {
    "invalid_request": 422,
    "not_found": 404,
    "stage_error": 400,
}

_HTTP_EXCEPTION_KINDS: dict[int, str] = {
    404: "not_found",
    405: "method_not_allowed",
}

# Stage-specific error types are imported lazily inside ``_register_error_handlers``
# so this module imports clean without the core analysis module at load time.


def _require_http_extra() -> None:
    """Raise a clear install hint if the optional HTTP extra is absent."""
    if FastAPI is None or Request is None or JSONResponse is None:
        raise ImportError(_MISSING_HTTP_EXTRA)


def create_app(
    runtime: CoreRuntime | None = None,
    *,
    title: str = "goldilocks-core",
) -> FastAPI:
    """Build the FastAPI application with one app-owned ``CoreRuntime``.

    Args:
        runtime: Optional pre-built runtime. When omitted, the app owns a
            runtime created at startup and closes it on shutdown. When
            provided, the caller owns it; the app does not close it.
        title: OpenAPI title.

    Returns:
        A FastAPI application configured with the Core transport endpoints.

    Raises:
        ImportError: If the ``[http]`` extra is not installed.
    """
    _require_http_extra()
    assert FastAPI is not None

    state = _AppState(provided_runtime=runtime)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Own one CoreRuntime for the process lifetime."""
        del app
        state.runtime = state.provided_runtime or CoreRuntime()
        try:
            yield
        finally:
            state.close()

    app = FastAPI(
        title=title,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.goldilocks = state

    _register_routes(app, state)
    _register_error_handlers(app)
    return app


def serve(*, host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the HTTP server with uvicorn (CLI entry point).

    Args:
        host: Bind host. Defaults to loopback.
        port: Bind port.

    Raises:
        ImportError: If the ``[http]`` extra is not installed.
    """
    _require_http_extra()
    import uvicorn

    app = create_app()
    uvicorn.run(app, host=host, port=port)


class _AppState:
    """Mutable application state holding the runtime."""

    def __init__(self, *, provided_runtime: CoreRuntime | None) -> None:
        """Store the optional provided runtime; the owned one is built at startup."""
        self.provided_runtime = provided_runtime
        self.runtime: CoreRuntime | None = None
        self._owns_runtime = provided_runtime is None

    def close(self) -> None:
        """Close the runtime only when the app owns it."""
        runtime = self.runtime
        if runtime is not None and self._owns_runtime and not runtime.is_closed:
            runtime.close()


def _register_routes(app: FastAPI, state: _AppState) -> None:
    """Register the Core transport endpoints."""
    assert Request is not None and JSONResponse is not None

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Return liveness without loading models or running a job."""
        return {"status": "ok"}

    async def _read_body(request: Request) -> dict[str, Any]:
        raw = await request.body()
        if not raw:
            raise RequestError("invalid_request", "Request body must be a JSON object.")
        import json

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as error:
            raise RequestError(
                "invalid_request", f"Request body is not valid JSON: {error}"
            ) from error
        if not isinstance(parsed, dict):
            raise RequestError("invalid_request", "Request body must be a JSON object.")
        return parsed

    async def _run(request: Request, entrypoint: str) -> JSONResponse:
        body = await _read_body(request)
        return await run_in_threadpool(_execute, entrypoint, body, state)

    @app.post("/recommend")
    async def recommend(request: Request) -> JSONResponse:
        """Run Load → Analyze → Advise → Kmesh → Select; return CoreResult JSON."""
        return await _run(request, "recommend")

    @app.post("/generate")
    async def generate(request: Request) -> JSONResponse:
        """Run the pipeline through Generate; return CoreResult JSON."""
        return await _run(request, "generate")

    @app.post("/analyze")
    async def analyze(request: Request) -> JSONResponse:
        """Run Load → Analyze and return the analysis record JSON."""
        return await _run(request, "analyze")

    @app.post("/kmesh")
    async def kmesh(request: Request) -> JSONResponse:
        """Run the Kmesh stage and return the k-point selection JSON."""
        return await _run(request, "kmesh")

    @app.post("/advise")
    async def advise(request: Request) -> JSONResponse:
        """Run Load → Analyze → Advise and return the advice record JSON."""
        return await _run(request, "advise")

    @app.post("/select")
    async def select(request: Request) -> JSONResponse:
        """Run Load → Analyze → Advise → Select and return the selection JSON."""
        return await _run(request, "select")


def _execute(entrypoint: str, body: dict[str, Any], state: _AppState) -> JSONResponse:
    """Run the blocking parse + pipeline off the event loop and build the response."""
    assert JSONResponse is not None
    request = from_dict(body)
    runtime = state.runtime
    if runtime is None:  # pragma: no cover - lifespan invariant
        raise RuntimeError("CoreRuntime is not initialized.")
    if entrypoint == "generate":
        result = runtime.generate(request, output_dir=request.output_dir)
    else:
        result = getattr(runtime, entrypoint)(request)
    return _build_response(result)


def _build_response(result: Any) -> JSONResponse:
    """Serialize a stage record or CoreResult into a JSONResponse."""
    assert JSONResponse is not None
    return JSONResponse(content=to_jsonable(result))


def _register_error_handlers(app: FastAPI) -> None:
    """Register deterministic error handlers that preserve error reasons."""
    assert JSONResponse is not None and HTTPException is not None

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        del request
        kind = _HTTP_EXCEPTION_KINDS.get(exc.status_code, "http_error")
        message = exc.detail if isinstance(exc.detail, str) else "http error"
        return JSONResponse(
            content={"error": {"kind": kind, "message": message}},
            status_code=exc.status_code,
        )

    @app.exception_handler(RequestError)
    async def _request_error_handler(
        request: Request, exc: RequestError
    ) -> JSONResponse:
        del request
        return JSONResponse(
            content={"error": {"kind": exc.kind, "message": exc.message}},
            status_code=_STATUS_FOR_KIND.get(exc.kind, 400),
        )

    @app.exception_handler(ValueError)
    async def _value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        del request
        if isinstance(exc, RequestError):  # pragma: no cover - has its own handler
            return JSONResponse(
                content={"error": {"kind": exc.kind, "message": exc.message}},
                status_code=_STATUS_FOR_KIND.get(exc.kind, 400),
            )
        return JSONResponse(
            content={"error": {"kind": "stage_error", "message": str(exc)}},
            status_code=400,
        )

    # Stage-specific exception types that carry client-actionable reasons.
    from goldilocks_core.analysis import (
        DimensionalityClassificationError,
        SymmetryAnalysisError,
    )

    @app.exception_handler(DimensionalityClassificationError)
    async def _dim_error_handler(
        request: Request, exc: DimensionalityClassificationError
    ) -> JSONResponse:
        del request
        return JSONResponse(
            content={"error": {"kind": "stage_error", "message": str(exc)}},
            status_code=422,
        )

    @app.exception_handler(SymmetryAnalysisError)
    async def _sym_error_handler(
        request: Request, exc: SymmetryAnalysisError
    ) -> JSONResponse:
        del request
        return JSONResponse(
            content={"error": {"kind": "stage_error", "message": str(exc)}},
            status_code=422,
        )

    @app.exception_handler(FileNotFoundError)
    async def _not_found_handler(
        request: Request, exc: FileNotFoundError
    ) -> JSONResponse:
        del request
        return JSONResponse(
            content={"error": {"kind": "not_found", "message": str(exc)}},
            status_code=404,
        )

    @app.exception_handler(Exception)
    async def _internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
        del request, exc
        return JSONResponse(
            content={
                "error": {"kind": "internal_error", "message": "internal server error"}
            },
            status_code=500,
        )
