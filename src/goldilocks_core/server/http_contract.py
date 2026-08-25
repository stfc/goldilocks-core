from __future__ import annotations

import json
import secrets
from typing import Any

from fastapi import FastAPI
from fastapi.responses import Response

from goldilocks_core.contracts import Capabilities, DftInputData, StructureInspection
from goldilocks_core.publication import Publisher
from goldilocks_core.runtime.service import Service
from goldilocks_core.server.capacity import ComputationCapacity
from goldilocks_core.server.request import (
    RequestError,
    compute_from_dict,
    inspection_source_from_dict,
)
from goldilocks_core.server.wire import (
    ComputeRequestDocument,
    ErrorResponseDocument,
    InspectRequestDocument,
    computation_result_document,
    prepared_computation_document,
)

_ERROR_RESPONSES = {
    status: {
        "model": ErrorResponseDocument,
        "content": {"application/json": {}},
    }
    for status in (422, 424, 503)
}
_PREPARED_RESPONSE = {
    "description": "One reviewed Computation Result and its exact optional archive.",
    "content": {
        "multipart/form-data": {
            "schema": {"$ref": "#/components/schemas/PreparedComputation"}
        }
    },
}


class PreparedMultipartResponse(Response):
    media_type = "multipart/form-data"


def install_scientific_routes(
    app: FastAPI,
    service: Service,
    capacity: ComputationCapacity,
) -> None:
    tasks = service.capabilities().tasks
    result_document = computation_result_document(tasks)
    prepared_document = prepared_computation_document(tasks)

    @app.get("/capabilities", response_model=Capabilities)
    def capabilities() -> dict[str, Any]:
        return service.capabilities().to_dict()

    @app.post(
        "/inspect",
        response_model=StructureInspection,
        responses={422: {"model": ErrorResponseDocument}},
    )
    def inspect(body: InspectRequestDocument) -> dict[str, Any]:
        try:
            source = inspection_source_from_dict(body.model_dump())
        except ValueError as error:
            if isinstance(error, RequestError):
                raise
            raise RequestError(str(error)) from error
        return service.inspect_structure(source).to_dict()

    @app.post(
        "/compute",
        response_model=prepared_document,
        response_model_exclude_unset=True,
        response_class=Response,
        responses={200: _PREPARED_RESPONSE, **_ERROR_RESPONSES},
    )
    def compute(body: ComputeRequestDocument) -> Response:
        try:
            request = compute_from_dict(body.model_dump())
        except ValueError as error:
            if isinstance(error, RequestError):
                raise
            raise RequestError(str(error)) from error
        with capacity.acquire():
            result = service.compute(request)
            result_payload = json.dumps(
                result_document.model_validate(result.to_dict()).model_dump(
                    mode="json", exclude_unset=True
                ),
                separators=(",", ":"),
            ).encode("utf-8")
            input_data = result.records.get(DftInputData)
            archive = (
                Publisher(service.runtime.asset_store).archive_bytes(input_data)
                if input_data is not None
                else None
            )
            return _prepared_response(result_payload, archive)


def _prepared_response(result: bytes, archive: bytes | None) -> Response:
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
