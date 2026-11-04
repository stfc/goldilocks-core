"""FastAPI transport over the v2 ``service``/``capabilities``/
``set_overrides`` stack (v2 epic 8, #8).

Replaces v1's ``Service``/``Runtime``-backed transport: every route now
calls ``server/_handlers.py``'s free functions, the exact same path
``server/mcp.py`` calls -- one shared request-validation/dispatch
implementation for both transports, not two.

**Workbench static-file mount.** Three ways to reach it, in precedence
order: an explicit ``static_root`` given to ``create_app()``/``serve()``;
``GOLDILOCKS_WORKBENCH_STATIC_ROOT``; a ``webapp/`` directory bundled
inside this installed package (#122) -- present only when this package
was built from a release that ran ``npm run build`` first (see
``.github/workflows/release.yml``), absent from a plain source checkout
or dev install, so ``uv build``/``uv sync`` here never needs a frontend
build lying around either. Whichever is found is mounted at ``/`` --
same origin as the API, no CORS (v2 epic 12, #12). ``cli/_serve.py``'s
own ``--static-root`` flag (#59) is the other, CLI-facing way to reach
the first tier -- the Docker image uses the env var instead since it has
no CLI invocation to add a flag to. A relative root is resolved against
the cwd once, when the app is created, so later requests never depend on
the process's cwd (#136).

**Strict JSON documents.** ``/explain``, ``/magnetic-orderings`` and
``/run`` return a ``JSONResponse`` rather than letting FastAPI serialize
the document: ``JSONResponse`` raises on a non-finite float (a 500),
where FastAPI's route serializer silently writes it as ``null`` (#137).
``/explain`` and ``/magnetic-orderings`` keep their ``-> Any``
annotations, so the OpenAPI schema does not change.

Behind the optional ``[http]`` extra; importing ``goldilocks_core``
never imports FastAPI (P7).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from goldilocks_core.bundle import archive_bytes
from goldilocks_core.capabilities import capabilities
from goldilocks_core.failures import ExpectedFailure
from goldilocks_core.server import _handlers
from goldilocks_core.server.documents import (
    ComputeRequestDocument,
    InlineStructureDocument,
    MagneticOrderingsRequestDocument,
    RunRequestDocument,
)

try:
    # Module-level, not deferred into create_app() like the rest of
    # FastAPI: with `from __future__ import annotations` in effect,
    # route return-type hints are strings resolved against *this
    # module's* __globals__ when FastAPI builds the OpenAPI schema
    # (#31). A name bound only inside create_app() never satisfies
    # that lookup, so .openapi() dies on a stale forward ref. The
    # fallback keeps the module importable without the [http] extra --
    # create_app()'s own try/except still raises _MISSING_HTTP_EXTRA
    # for anyone who actually calls it.
    from fastapi.responses import JSONResponse, Response
except ImportError:
    JSONResponse = Response = Any  # type: ignore[assignment,misc]

__all__ = ["create_app", "serve"]

_MISSING_HTTP_EXTRA = (
    "The HTTP transport requires goldilocks-core[http]. "
    "Install it with `uv sync --extra http`."
)
_STATIC_ROOT_ENV = "GOLDILOCKS_WORKBENCH_STATIC_ROOT"
_STATUS_BY_CATEGORY = {"input": 422, "dependency": 424, "local": 500}


def create_app(*, static_root: str | Path | None = None) -> Any:
    try:
        from fastapi import FastAPI
    except ImportError as error:
        raise ImportError(_MISSING_HTTP_EXTRA) from error

    readiness = _handlers.build_readiness()
    app = FastAPI(title="goldilocks-core")
    app.state.asset_readiness = readiness
    _register_error_handlers(app)
    _register_operational_routes(app, readiness)

    @app.get("/capabilities")
    def get_capabilities() -> Any:
        return capabilities()

    @app.post("/inspect")
    def inspect(body: InlineStructureDocument) -> Any:
        return _handlers.inspect(body)

    @app.post("/explain")
    def explain(body: ComputeRequestDocument) -> Any:
        return JSONResponse(_handlers.explain(body))

    @app.post("/magnetic-orderings")
    def magnetic_orderings(body: MagneticOrderingsRequestDocument) -> Any:
        return JSONResponse(_handlers.magnetic_orderings(body))

    @app.post("/run")
    def run(body: RunRequestDocument) -> Response:
        summary, bundle_input = _handlers.run(body)
        if body.respond_with == "archive":
            return Response(archive_bytes(bundle_input), media_type="application/zip")
        return JSONResponse(summary)

    _mount_workbench(app, static_root)
    return app


def _bundled_static_root() -> Path | None:
    """A ``webapp/`` directory shipped inside this installed package, if a
    release build put one there (#122) -- ``None`` for a plain source
    checkout or dev install, where nothing ever creates it."""
    from importlib import resources

    candidate = resources.files("goldilocks_core") / "webapp"
    if candidate.is_dir() and (candidate / "index.html").is_file():
        return Path(str(candidate))
    return None


def _mount_workbench(app: Any, static_root: str | Path | None) -> None:
    static_root = (
        static_root or os.environ.get(_STATIC_ROOT_ENV) or _bundled_static_root()
    )
    if not static_root:
        return
    from fastapi.staticfiles import StaticFiles

    # Mounted last, after every API route above: Starlette matches routes
    # in registration order, so the explicit routes still win even though
    # this Mount's prefix ("/") would otherwise swallow everything.
    # Resolved once, here: StaticFiles joins a relative directory with
    # whatever the cwd is on every request (#136). `check_dir` (default
    # True) still fails fast with a RuntimeError if it doesn't exist.
    app.mount(
        "/",
        StaticFiles(directory=Path(static_root).resolve(), html=True),
        name="workbench",
    )


def _register_error_handlers(app: Any) -> None:
    from fastapi import Request
    from fastapi.exceptions import RequestValidationError

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, error: RequestValidationError
    ) -> JSONResponse:
        # pydantic's own error.errors() embeds the raw exception object
        # in ctx for custom validators (e.g. this module's own
        # _reject_path_shaped_content) -- not JSON-safe. Keep only the
        # string fields, same sanitization v1's handler already did.
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
                    "details": {"validation_errors": validation_errors},
                }
            },
        )

    @app.exception_handler(ExpectedFailure)
    async def expected_failure_handler(
        _request: Request, error: ExpectedFailure
    ) -> JSONResponse:
        status = _STATUS_BY_CATEGORY.get(error.category, 500)
        return JSONResponse(status_code=status, content={"error": error.public_error()})


def _register_operational_routes(app: Any, readiness: Any) -> None:
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
                    "details": {
                        "asset_id": report.asset_id,
                        "version": report.version,
                        "state": report.state,
                    },
                }
            },
        )


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
    uvicorn.run(create_app(static_root=static_root), host=host, port=port)
