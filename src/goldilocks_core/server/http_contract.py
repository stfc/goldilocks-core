from __future__ import annotations

import json
import secrets

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response

from goldilocks_core.contracts import Capabilities, StructureInspection
from goldilocks_core.runtime.service import Service
from goldilocks_core.server.request import (
    ComputeRequestDocument,
    InspectRequestDocument,
)
from goldilocks_core.server.wire import (
    ErrorResponseDocument,
    prepared_computation_document,
)

_ERROR_RESPONSES = {
    status: {
        "model": ErrorResponseDocument,
        "content": {"application/json": {}},
    }
    for status in (422, 424)
}
_PREPARED_RESPONSE = {
    "description": "One reviewed Computation Result.",
    "content": {
        "multipart/form-data": {
            "schema": {"$ref": "#/components/schemas/PreparedComputation"}
        }
    },
}


class PreparedMultipartResponse(Response):
    media_type = "multipart/form-data"


def install_scientific_routes(app: FastAPI, service: Service) -> None:
    tasks = service.capabilities().tasks
    prepared_document = prepared_computation_document(tasks)

    @app.get("/capabilities", response_model=Capabilities)
    def capabilities() -> Response:
        return JSONResponse(service.capabilities().to_dict())

    @app.post(
        "/inspect",
        response_model=StructureInspection,
        responses={422: {"model": ErrorResponseDocument}},
    )
    def inspect(body: InspectRequestDocument) -> Response:
        return JSONResponse(service.inspect_structure(body.source).to_dict())

    @app.post(
        "/compute",
        response_model=prepared_document,
        response_class=Response,
        responses={200: _PREPARED_RESPONSE, **_ERROR_RESPONSES},
    )
    def compute(body: ComputeRequestDocument) -> Response:
        result = service.compute(body)
        result_payload = json.dumps(
            result.to_dict(),
            separators=(",", ":"),
        ).encode("utf-8")
        return _prepared_response(result_payload)


def _prepared_response(result: bytes) -> Response:
    while True:
        boundary = f"goldilocks-{secrets.token_hex(24)}"
        marker = boundary.encode("ascii")
        if marker not in result:
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
    parts.append(f"--{boundary}--\r\n".encode("ascii"))
    return PreparedMultipartResponse(
        b"".join(parts),
        media_type=f'multipart/form-data; boundary="{boundary}"',
    )


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
