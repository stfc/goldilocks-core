"""Structured HTTP failure contract shared by the FastAPI transport.

Expected transport and domain errors map to stable ``{kind, message, status,
details}`` responses. Unexpected exceptions remain HTTP 500 with the full
server-side traceback logged; they are never silently replaced.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from goldilocks_core.server.request import RequestError

logger = logging.getLogger("goldilocks_core.server.http")

KIND_INVALID_REQUEST = "invalid_request"
KIND_STAGE_ERROR = "stage_error"
KIND_NOT_FOUND = "not_found"
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
