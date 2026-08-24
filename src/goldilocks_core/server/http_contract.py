from __future__ import annotations

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
    http_output_from_dict,
    inspection_source_from_dict,
)
from goldilocks_core.server.wire import (
    ComputationResultDocument,
    ComputeRequestDocument,
    ErrorResponseDocument,
    InspectRequestDocument,
)

_ERROR_RESPONSES = {
    status: {"model": ErrorResponseDocument} for status in (422, 424, 503)
}
_ARCHIVE_RESPONSE = {
    "description": "Canonical Computation Result JSON or an in-memory ZIP archive.",
    "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
}


def install_scientific_routes(
    app: FastAPI,
    service: Service,
    capacity: ComputationCapacity,
) -> None:
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
        response_model=ComputationResultDocument,
        responses={200: _ARCHIVE_RESPONSE, **_ERROR_RESPONSES},
    )
    def compute(body: ComputeRequestDocument) -> Any:
        document = body.model_dump()
        try:
            output = http_output_from_dict(document.pop("output"))
            request = compute_from_dict(document)
        except ValueError as error:
            if isinstance(error, RequestError):
                raise
            raise RequestError(str(error)) from error
        with capacity.acquire():
            result = service.compute(request)
            if output.kind == "memory":
                return result.to_dict()
            input_data = result.records.get(DftInputData)
            if input_data is None:
                raise RequestError(
                    "Archive output requires a Result containing DFT Input Data."
                )
            payload = Publisher(service.runtime.asset_store).archive_bytes(input_data)
            return Response(
                payload,
                media_type="application/zip",
                headers={
                    "Content-Disposition": (
                        'attachment; filename="goldilocks-inputs.zip"'
                    )
                },
            )
