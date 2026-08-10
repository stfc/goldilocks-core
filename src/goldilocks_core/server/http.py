"""FastAPI transport over one process-owned Core runtime."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from goldilocks_core.generation.registry import available_codes
from goldilocks_core.jobs import run_core_job
from goldilocks_core.runtime import CoreRuntime
from goldilocks_core.server.request import RequestError, from_dict

__all__ = ["create_app", "serve"]

_MISSING_HTTP_EXTRA = (
    "The HTTP transport requires goldilocks-core[http]. "
    "Install it with `uv sync --extra http`."
)


class _AppState:
    """Runtime state shared by every request to an application."""

    def __init__(self, runtime: CoreRuntime | None) -> None:
        self.provided_runtime = runtime
        self.runtime: CoreRuntime | None = None
        self.owns_runtime = runtime is None

    def close(self) -> None:
        """Close an application-owned runtime."""
        if self.owns_runtime and self.runtime is not None:
            self.runtime.close()


def create_app(runtime: CoreRuntime | None = None) -> Any:
    """Create the HTTP app, optionally using a caller-owned runtime."""
    try:
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse
    except ImportError as error:
        raise ImportError(_MISSING_HTTP_EXTRA) from error

    state = _AppState(runtime)

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

    @app.exception_handler(RequestError)
    async def request_error_handler(
        request: Request, error: RequestError
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=422,
            content={"error": {"kind": "invalid_request", "message": str(error)}},
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, error: ValueError) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=400,
            content={"error": {"kind": "stage_error", "message": str(error)}},
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

    @app.get("/health")
    def health() -> dict[str, str]:
        """Report process liveness."""
        return {"status": "ok"}

    @app.get("/tasks")
    def tasks() -> dict[str, Any]:
        """List every registered Core task with stable stage and record ids."""
        return {"tasks": [task.to_dict() for task in state.runtime.describe_tasks()]}

    @app.get("/codes")
    def codes() -> dict[str, Any]:
        """List target DFT codes with registered input writers."""
        return {"codes": list(available_codes())}

    @app.get("/models")
    def models() -> dict[str, Any]:
        """List available k-mesh models known to the runtime."""
        return {"models": state.runtime.describe_models()}

    @app.post("/recommend")
    def recommend(body: dict[str, Any]) -> dict[str, Any]:
        """Run the recommend preset."""
        return _execute("recommend", body, state)

    @app.post("/generate")
    def generate(body: dict[str, Any]) -> dict[str, Any]:
        """Run the generate preset and optionally publish a bundle."""
        return _execute("generate", body, state)

    @app.post("/compute")
    def compute(body: dict[str, Any]) -> dict[str, Any]:
        """Compute only the requested record types."""
        return _execute("compute", body, state)

    return app


def _execute(endpoint: str, body: dict[str, Any], state: _AppState) -> dict[str, Any]:
    """Parse, dispatch, and serialize one transport request."""
    raw = dict(body)
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

    request = from_dict(raw)
    if state.runtime is None:
        raise RuntimeError("CoreRuntime is not initialized.")
    return run_core_job(request, runtime=state.runtime).to_dict()


def serve(*, host: str = "127.0.0.1", port: int = 8000) -> None:
    """Serve the HTTP transport with uvicorn."""
    try:
        import uvicorn
    except ImportError as error:
        raise ImportError(_MISSING_HTTP_EXTRA) from error
    uvicorn.run(create_app(), host=host, port=port)
