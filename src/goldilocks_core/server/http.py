"""Synchronous stateless HTTP transport over the fixed Core pipeline.

This is a **transport only**. It maps a JSON request body to a
``CoreJobRequest``, runs it through one long-lived ``CoreRuntime``, and returns
``CoreResult`` JSON. It owns no auth, sessions, multi-tenant isolation, job
queues, persistence, file uploads beyond inline text, WebSockets, pod/container
management, or frontend. Those belong in the application layer
(``goldilocks``/``goldilocks-api``).

Sync, stateless: one runtime for the process lifetime, reused across requests,
closed on shutdown. No per-request runtime or model pipeline is constructed.

Request execution (JSON parsing of the body aside) is offloaded from the
ASGI event loop to anyio's thread pool: structure parsing, model inference,
generation, and bundle I/O are blocking, so a sync ``_execute`` runs off the
loop while the one thread-safe runtime is shared across concurrent requests.

HTTP dependencies (FastAPI + uvicorn) live behind the optional ``[http]`` extra.
``import goldilocks_core`` does not import this module. Install with
``uv sync --extra http`` or ``pip install goldilocks-core[http]``.
"""

from __future__ import annotations

import json
import math
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from goldilocks_core.jobs import CoreRuntime
from goldilocks_core.pseudo.pp_metadata import PseudoMetadata
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata
from goldilocks_core.server.request import RequestError, parse_core_job_request

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from typing import Any

# The HTTP names are imported at module scope so that string annotations
# (enabled by ``from __future__ import annotations``) resolve for FastAPI's
# signature inspection. They are guarded so importing this module without the
# ``[http]`` extra does not crash; ``create_app``/``serve`` raise a clear install
# hint before any route is built.
try:  # pragma: no cover - import availability is environment-dependent
    from fastapi import FastAPI, Request
    from starlette.concurrency import run_in_threadpool
    from starlette.exceptions import HTTPException
    from starlette.responses import JSONResponse
except ImportError:  # pragma: no cover - import availability is environment-dependent
    FastAPI = None  # type: ignore[assignment]
    Request = None  # type: ignore[assignment]
    run_in_threadpool = None  # type: ignore[assignment]
    HTTPException = None  # type: ignore[assignment]
    JSONResponse = None  # type: ignore[assignment]

__all__ = ["create_app", "serve"]


_MISSING_HTTP_EXTRA = (
    "goldilocks-core HTTP transport requires the optional '[http]' extra. "
    "Install it with `uv sync --extra http` or `pip install goldilocks-core[http]`."
)

_STATUS_FOR_KIND = {
    "invalid_request": 422,
    "not_found": 404,
}

_HTTP_EXCEPTION_KINDS = {
    404: "not_found",
    405: "method_not_allowed",
}


def _require_http_extra() -> None:
    """Raise a clear install hint if the optional HTTP extra is absent."""
    if FastAPI is None or Request is None or JSONResponse is None:
        raise ImportError(_MISSING_HTTP_EXTRA)


def create_app(
    *,
    runtime: CoreRuntime | None = None,
    pseudo_root: str | Path | None = None,
    structure_root: str | Path | None = None,
    bundle_root: str | Path | None = None,
    model: str | None = None,
    model_name: str | None = None,
    model_version: str | None = None,
    heuristic_kpoints: bool = False,
    title: str = "goldilocks-core",
) -> FastAPI:
    """Build the FastAPI application with one app-owned CoreRuntime.

    Args:
        runtime: Optional pre-built runtime. When omitted, the app owns a
            runtime built at startup from the backend composition options and
            closes it on shutdown. When provided, the caller owns it; the app
            does not close it.
        pseudo_root: Optional directory of UPF files loaded once at startup as
            the default pseudopotential metadata. Per-request ``pseudo_metadata``
            overrides it.
        structure_root: Optional allowlist root for server-side structure paths.
            Canonicalized at app construction. When ``None``, only inline
            structure content is accepted.
        bundle_root: Root for bundle ``output_dir`` resolution, canonicalized at
            app construction. Defaults to ``goldilocks_output``.
        model: Local ML Kmesh model path. Replaces the default QRF backend.
            Ignored when ``runtime`` is provided.
        model_name: Model name recorded in Kmesh provenance. Requires ``model``.
        model_version: Model version recorded in metadata. Requires ``model``.
        heuristic_kpoints: Use advice-based k-point resolution instead of the
            default QRF model. Ignored when ``runtime`` is provided.
        title: OpenAPI title.

    Returns:
        A FastAPI application configured with the Core transport endpoints.

    Raises:
        ImportError: If the ``[http]`` extra is not installed.
        ValueError: If backend composition options are invalid and no
            ``runtime`` is provided.
    """
    _require_http_extra()
    assert FastAPI is not None

    _validate_backend_options(
        model=model,
        model_name=model_name,
        model_version=model_version,
        heuristic_kpoints=heuristic_kpoints,
    )

    resolved_bundle_root = (
        Path(bundle_root) if bundle_root is not None else Path("goldilocks_output")
    ).resolve()
    resolved_structure_root = (
        Path(structure_root).resolve() if structure_root is not None else None
    )
    app_state = _AppState(
        provided_runtime=runtime,
        pseudo_root=Path(pseudo_root) if pseudo_root is not None else None,
        structure_root=resolved_structure_root,
        bundle_root=resolved_bundle_root,
        model=model,
        model_name=model_name,
        model_version=model_version,
        heuristic_kpoints=heuristic_kpoints,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Own one CoreRuntime and default pseudo metadata for the process."""
        app_state.runtime = app_state.provided_runtime or _build_runtime(
            model=app_state.model,
            model_name=app_state.model_name,
            model_version=app_state.model_version,
            heuristic_kpoints=app_state.heuristic_kpoints,
        )
        try:
            app_state.default_pseudo_metadata = _load_default_pseudo_metadata(
                app_state.pseudo_root
            )
            yield
        finally:
            app_state.close()

    app = FastAPI(
        title=title,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.goldilocks = app_state

    _register_routes(app, app_state)
    _register_error_handlers(app)
    return app


def serve(
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    pseudo_root: str | Path | None = None,
    structure_root: str | Path | None = None,
    bundle_root: str | Path | None = None,
    model: str | None = None,
    model_name: str | None = None,
    model_version: str | None = None,
    heuristic_kpoints: bool = False,
) -> None:
    """Run the HTTP server with uvicorn (CLI entry point).

    Backend composition mirrors the ``goldilocks-core`` CLI: default QRF model,
    ``--heuristic-kpoints`` advice-based resolution, or ``--model`` local CSLR
    model. Composition is process configuration, not request data. The serving
    path does not pass a pre-built runtime; the app owns the runtime built from
    these options and closes it on shutdown or startup failure.

    Args:
        host: Bind host. Defaults to loopback; binding to ``0.0.0.0`` is an
            explicit operator choice.
        port: Bind port.
        pseudo_root: Directory of UPF files for default pseudo metadata.
        structure_root: Allowlist root for server-side structure paths.
        bundle_root: Root for bundle output directories.
        model: Local ML Kmesh model path. Replaces the default QRF backend.
        model_name: Model name recorded in Kmesh provenance. Requires ``model``.
        model_version: Model version recorded in metadata. Requires ``model``.
        heuristic_kpoints: Use advice-based k-point resolution instead of the
            default QRF model.

    Raises:
        ImportError: If the ``[http]`` extra is not installed.
        ValueError: If backend-only metadata is supplied without ``model``,
            or ``model`` and ``heuristic_kpoints`` are both set.
    """
    _require_http_extra()

    import uvicorn

    _validate_backend_options(
        model=model,
        model_name=model_name,
        model_version=model_version,
        heuristic_kpoints=heuristic_kpoints,
    )
    app = create_app(
        pseudo_root=pseudo_root,
        structure_root=structure_root,
        bundle_root=bundle_root,
        model=model,
        model_name=model_name,
        model_version=model_version,
        heuristic_kpoints=heuristic_kpoints,
    )
    uvicorn.run(app, host=host, port=port)


class _AppState:
    """Mutable application state holding the runtime and config."""

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
        """Store config; the runtime is created during the lifespan startup."""
        self.provided_runtime = provided_runtime
        self.runtime: CoreRuntime | None = None
        self.pseudo_root = pseudo_root
        self.structure_root = structure_root
        self.bundle_root = bundle_root
        self.default_pseudo_metadata: tuple[PseudoMetadata, ...] = ()
        self.model = model
        self.model_name = model_name
        self.model_version = model_version
        self.heuristic_kpoints = heuristic_kpoints
        # The app owns and closes a runtime only when the caller did not
        # provide one. A caller-provided runtime stays open for the caller.
        self._owns_runtime = provided_runtime is None

    def close(self) -> None:
        """Close the runtime only when the app owns it."""
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


def _register_routes(app: FastAPI, app_state: _AppState) -> None:
    """Register the Core transport endpoints."""
    assert Request is not None and JSONResponse is not None

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Return liveness without loading models or running a job."""
        return {"status": "ok"}

    async def _run(mode: str, request: Request) -> JSONResponse:
        body = await _read_json_body(request)
        return await run_in_threadpool(_execute, mode, body, app_state)

    @app.post("/recommend")
    async def recommend(request: Request) -> JSONResponse:
        """Run Load -> Analyze -> Advise -> Kmesh -> Select and return
        CoreResult JSON."""
        return await _run("recommend", request)

    @app.post("/generate")
    async def generate(request: Request) -> JSONResponse:
        """Run the pipeline through Generate and return CoreResult JSON."""
        return await _run("generate", request)

    @app.post("/bundle")
    async def bundle(request: Request) -> JSONResponse:
        """Run the full pipeline and publish a bundle directory under bundle root."""
        return await _run("bundle", request)


def _execute(mode: str, body: dict[str, Any], app_state: _AppState) -> JSONResponse:
    """Run the blocking parse + pipeline off the event loop and build the response.

    Runs in anyio's thread pool so concurrent requests do not serialize on the
    ASGI event loop. The single ``CoreRuntime`` is thread-safe across requests.
    """
    core_request = parse_core_job_request(
        body,
        mode=mode,  # type: ignore[arg-type]
        structure_root=app_state.structure_root,
        bundle_root=app_state.bundle_root,
        default_pseudo_metadata=app_state.default_pseudo_metadata,
    )
    runtime = app_state.runtime
    if runtime is None:  # pragma: no cover - lifespan invariant
        raise RuntimeError("CoreRuntime is not initialized.")
    try:
        result = runtime.run(core_request)
    except FileExistsError as error:
        # Only the bundle publication boundary raises ``FileExistsError`` for an
        # existing destination, and only ``bundle`` reaches that boundary. A
        # ``FileExistsError`` raised anywhere else (e.g. an internal stage of
        # ``/recommend`` or ``/generate``) is an unexpected internal failure:
        # re-raise it so the generic handler returns a redacted 500 rather than
        # a misleading ``stage_error``.
        if mode != "bundle":
            raise
        public_path = _public_bundle_path(body)
        raise _bundle_destination_error(public_path) from error
    return _build_response(result, body, mode)


def _build_response(result: Any, body: dict[str, Any], mode: str) -> JSONResponse:
    """Serialize CoreResult and replace the absolute bundle path with a public one."""
    content = result.to_dict()
    if mode == "bundle" and content.get("bundle") is not None:
        content["bundle"]["path"] = _public_bundle_path(body)
    return JSONResponse(content=content)


def _public_bundle_path(body: dict[str, Any]) -> str:
    """Return the server-relative output_dir the client supplied, never absolute."""
    value = body.get("output_dir")
    if isinstance(value, str):
        return value
    return ""


def _bundle_destination_error(public_path: str) -> ValueError:
    """Build a sanitized stage error for an existing bundle destination."""
    message = (
        f"bundle destination already exists: {public_path}"
        if public_path
        else "bundle destination already exists"
    )
    return ValueError(message)


def _register_error_handlers(app: FastAPI) -> None:
    """Register deterministic error handlers that do not leak internals."""
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
        if isinstance(
            exc, RequestError
        ):  # pragma: no cover - RequestError has its own handler
            return JSONResponse(
                content={"error": {"kind": exc.kind, "message": exc.message}},
                status_code=_STATUS_FOR_KIND.get(exc.kind, 400),
            )
        return JSONResponse(
            content={"error": {"kind": "stage_error", "message": str(exc)}},
            status_code=400,
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


async def _read_json_body(request: Request) -> dict[str, Any]:
    """Read and parse the request body as a strict JSON object with a 422 on bad JSON.

    Strictness beyond the stdlib ``json`` defaults: non-standard constants
    (``NaN``/``Infinity``/``-Infinity``) and overflow to a non-finite float are
    rejected, duplicate object keys at any nesting level are rejected, malformed
    UTF-8 encoding is rejected, and unpaired surrogate code points (JSON escapes
    such as a lone ``\\uD800``) are rejected anywhere in the parsed value. Each
    failure is a deterministic 422 ``invalid_request`` rather than a silent
    last-wins parse, a non-finite value reaching the contract deserializers, or a
    lone surrogate reaching ``os.open`` as a ``UnicodeEncodeError`` stage error.
    """
    raw = await request.body()
    if not raw:
        raise RequestError("invalid_request", "Request body must be a JSON object.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RequestError(
            "invalid_request", f"Request body is not valid UTF-8: {error}"
        ) from error
    try:
        parsed = json.loads(
            text,
            parse_constant=_reject_nonstandard_json_constant,
            parse_float=_parse_finite_float,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except json.JSONDecodeError as error:
        raise RequestError(
            "invalid_request", f"Request body is not valid JSON: {error}"
        ) from error
    if not isinstance(parsed, dict):
        raise RequestError("invalid_request", "Request body must be a JSON object.")
    _reject_lone_surrogates(parsed)
    return parsed


def _reject_lone_surrogates(value: Any) -> None:
    """Reject strings containing unpaired surrogate code points.

    A JSON escape such as ``\\uD800`` decodes to a lone surrogate code point.
    Valid surrogate pairs combine into a single supplementary code point during
    ``json.loads``, so any remaining code point in ``U+D800``-``U+DFFF`` is
    unpaired. Such a string cannot be encoded to the filesystem's UTF-8 and
    would otherwise reach ``os.open`` and surface as a ``UnicodeEncodeError``
    stage error. Reject it at the strict-JSON boundary with a deterministic,
    redacted 422. Keys are checked too.
    """
    if isinstance(value, str):
        if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise RequestError(
                "invalid_request",
                "Request body contains an unpaired surrogate code point.",
            )
    elif isinstance(value, dict):
        for key, item in value.items():
            _reject_lone_surrogates(key)
            _reject_lone_surrogates(item)
    elif isinstance(value, list):
        for item in value:
            _reject_lone_surrogates(item)


def _reject_nonstandard_json_constant(token: str) -> float:
    """Reject ``NaN``/``Infinity``/``-Infinity`` literals that stdlib json accepts."""
    raise RequestError(
        "invalid_request",
        f"Request body contains a non-standard JSON constant: {token}",
    )


def _parse_finite_float(token: str) -> float:
    """Parse a JSON number, rejecting overflow to infinity or non-finite values."""
    value = float(token)
    if not math.isfinite(value):
        raise RequestError(
            "invalid_request", "Request body contains a non-finite number."
        )
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate object keys at this nesting level; JSON objects are unique."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RequestError(
                "invalid_request",
                f"Request body contains a duplicate object key: {key!r}",
            )
        result[key] = value
    return result


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
