"""Structured HTTP failure contract shared by the FastAPI transport.

Expected transport and domain errors map to stable ``{kind, message, status,
details}`` responses. Unexpected exceptions remain HTTP 500 with the full
server-side traceback logged; they are never silently replaced.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from goldilocks_core.server.concurrency import ComputeBusyError
from goldilocks_core.server.request import RequestError

logger = logging.getLogger("goldilocks_core.server.http")

KIND_INVALID_REQUEST = "invalid_request"
KIND_STAGE_ERROR = "stage_error"
KIND_NOT_FOUND = "not_found"
KIND_SERVER_BUSY = "server_busy"
KIND_UNEXPECTED = "unexpected"


def error_response(
    kind: str,
    message: str,
    *,
    status: int,
    details: Any = None,
) -> JSONResponse:
    """Build a stable structured failure response."""
    error: dict[str, Any] = {
        "kind": kind,
        "message": message,
        "status": status,
        "details": details,
    }
    return JSONResponse(status_code=status, content={"error": error})


def register_error_handlers(app: FastAPI) -> None:
    """Register the transport's structured failure handlers on ``app``."""

    @app.exception_handler(RequestError)
    async def request_error_handler(
        request: Request, error: RequestError
    ) -> JSONResponse:
        del request
        return error_response(KIND_INVALID_REQUEST, str(error), status=422)

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        """Map FastAPI/Pydantic body validation failures to the structured
        invalid_request envelope so the Workbench never sees an ambiguous
        `{"detail": [...]}` shape."""
        del request
        details = [
            {
                "loc": list(raw.get("loc", ())),
                "msg": str(raw.get("msg", "Invalid value")),
                "type": str(raw.get("type", "value_error")),
            }
            for raw in error.errors()
        ]
        first = details[0] if details else {}
        location = ".".join(str(part) for part in first.get("loc", []))
        suffix = f" at {location}" if location else ""
        message = first.get("msg", "Invalid request body.") + suffix
        return error_response(
            KIND_INVALID_REQUEST,
            message,
            status=422,
            details=details,
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, error: ValueError) -> JSONResponse:
        del request
        return error_response(KIND_STAGE_ERROR, str(error), status=400)

    @app.exception_handler(FileNotFoundError)
    async def not_found_handler(
        request: Request, error: FileNotFoundError
    ) -> JSONResponse:
        del request
        return error_response(KIND_NOT_FOUND, str(error), status=404)

    @app.exception_handler(ComputeBusyError)
    async def server_busy_handler(
        request: Request, error: ComputeBusyError
    ) -> JSONResponse:
        """Surface a saturated computation gate as a retryable 503."""
        del request
        response = error_response(
            KIND_SERVER_BUSY,
            str(error),
            status=503,
            details={"retryable": True},
        )
        response.headers["Retry-After"] = str(error.retry_after)
        return response

    @app.exception_handler(Exception)
    async def unexpected_handler(request: Request, error: Exception) -> JSONResponse:
        logger.exception(
            "Unexpected server error handling %s %s",
            request.method,
            request.url.path,
            exc_info=error,
        )
        return error_response(
            KIND_UNEXPECTED,
            "An unexpected server error occurred.",
            status=500,
        )
