from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Literal

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, JsonValue, field_validator

from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    PresetRequest,
    Result,
    record_type_id,
)
from goldilocks_core.io.structures import (
    StructureInputError,
    parse_structure_content,
    structure_document,
)
from goldilocks_core.pseudo.registry import (
    PseudoTable,
    default_table,
    load_tables,
)
from goldilocks_core.runtime import Service
from goldilocks_core.server.archive import (
    WorkbenchArchive,
    build_workbench_archive,
)
from goldilocks_core.server.capacity import ComputationCapacity


class WorkbenchRequestError(ValueError):
    def __init__(
        self,
        operation: str,
        message: str,
        *,
        kind: str = "invalid_request",
        status_code: int = 422,
        retryable: bool = False,
        details: dict[str, JsonValue] | None = None,
    ) -> None:
        super().__init__(message)
        self.operation = operation
        self.kind = kind
        self.status_code = status_code
        self.retryable = retryable
        self.details = details or {}


class _Document(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)


class StructureSourceRequest(_Document):
    name: str
    format: Literal["cif", "poscar"] | None = None
    content: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if (
            not value
            or value in {".", ".."}
            or "/" in value
            or "\\" in value
            or PurePath(value).name != value
        ):
            raise ValueError("source name must be one non-empty filename")
        return value


class StructureInspectionRequest(_Document):
    source: StructureSourceRequest


class SourceDocument(_Document):
    name: str
    format: str
    sha256: str
    size_bytes: int


class SpeciesDocument(_Document):
    symbol: str
    label: str
    occupancy: float
    oxidation_state: float | None = None


class SiteDocument(_Document):
    fractional_coordinates: tuple[float, float, float]
    cartesian_coordinates_angstrom: tuple[float, float, float]
    species: tuple[SpeciesDocument, ...]


class LatticeResponse(_Document):
    vectors_angstrom: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ]
    lengths_angstrom: tuple[float, float, float]
    angles_degrees: tuple[float, float, float]
    volume_angstrom3: float


class StructureResponse(_Document):
    schema_version: int
    source: SourceDocument
    formula: str
    reduced_formula: str
    site_count: int
    lattice: LatticeResponse
    periodicity: tuple[bool, bool, bool]
    sites: tuple[SiteDocument, ...]


class IntentResponse(_Document):
    code: str = "quantum_espresso"
    task: str = "scf_single_point"
    functional: str = "PBEsol"
    pseudo_accuracy: Literal["efficiency", "precision"] = "efficiency"


class HintsResponse(_Document):
    k_spacing: float | None = None
    k_grid: tuple[int, int, int] | None = None
    smearing_type: str | None = None
    smearing_width_ry: float | None = None
    spin_polarized: bool | None = None
    spin_orbit_coupling: bool | None = None
    pseudo_accuracy: Literal["efficiency", "precision"] | None = None
    pseudo_type: str | None = None
    relativistic_mode: str | None = None
    conv_thr: float | None = None
    mixing_beta: float | None = None
    electron_maxstep: int | None = None
    use_vdw: bool | None = None
    vdw_method: str | None = None


class CalculationDefaults(_Document):
    intent: IntentResponse
    hints: HintsResponse


class GuidedRequest(_Document):
    source: StructureSourceRequest
    intent: IntentResponse = IntentResponse()
    hints: HintsResponse = HintsResponse()
    pseudo_table_id: str | None = None

    @field_validator("pseudo_table_id")
    @classmethod
    def validate_table_id(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("pseudo_table_id must be null or a non-empty string")
        return value


class ArchiveRequest(GuidedRequest):
    review_digest: str

    @field_validator("review_digest")
    @classmethod
    def validate_review_digest(cls, value: str) -> str:
        if len(value) != 64:
            raise ValueError("review_digest must contain 64 hexadecimal characters")
        try:
            int(value, 16)
        except ValueError as error:
            raise ValueError(
                "review_digest must contain 64 hexadecimal characters"
            ) from error
        return value


class PseudoTableResponse(_Document):
    id: str
    version: str
    provider: str
    upstream_table: str
    functional: str
    accuracy: Literal["efficiency", "precision"]
    relativistic: str
    licence: str
    citation: str
    elements: tuple[str, ...]
    default: bool


class StructureInspectionResponse(_Document):
    structure: StructureResponse
    canonical_cif: str
    defaults: CalculationDefaults
    pseudo_tables: tuple[PseudoTableResponse, ...]


class GeneratedFileResponse(_Document):
    path: str
    role: str
    content: str
    sha256: str


class SelectedPseudoResponse(_Document):
    element: str
    filename: str
    sha256: str
    functional: str | None
    ecutwfc_ry: float | None
    ecutrho_ry: float | None
    provenance: dict[str, JsonValue]
    warnings: tuple[str, ...]


class PseudoSelectionResponse(_Document):
    table: PseudoTableResponse
    files: tuple[SelectedPseudoResponse, ...]
    warnings: tuple[str, ...]


class RecommendationResponse(_Document):
    schema_version: int
    review_digest: str
    structure: StructureResponse
    canonical_cif: str
    intent: IntentResponse
    hints: HintsResponse
    records: dict[str, JsonValue]
    generated_files: tuple[GeneratedFileResponse, ...]
    selection: PseudoSelectionResponse
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ReviewComputation:
    response: RecommendationResponse
    result: Result
    table: PseudoTable


def _table_response(table: PseudoTable) -> PseudoTableResponse:
    return PseudoTableResponse(
        id=table.id,
        version=table.version,
        provider=table.provider,
        upstream_table=table.upstream_table,
        functional=table.functional,
        accuracy=table.accuracy,
        relativistic=table.relativistic,
        licence=table.licence,
        citation=table.citation,
        elements=table.elements,
        default=table.default,
    )


def _guided_preset(
    request: GuidedRequest, operation: str
) -> tuple[PresetRequest, StructureResponse, str]:
    source = request.source
    try:
        structure, resolved_format = parse_structure_content(
            source.content, source.format
        )
        preset = PresetRequest(
            structure=structure,
            intent=CalculationIntent(**request.intent.model_dump()),
            hints=CalculationHints(**request.hints.model_dump()),
            mode="generate",
            pseudo_table=request.pseudo_table_id,
        )
    except (StructureInputError, TypeError, ValueError) as error:
        raise WorkbenchRequestError(operation, str(error)) from error
    document = structure_document(
        structure,
        source_name=source.name,
        source_format=resolved_format,
        source_content=source.content,
    )
    return preset, StructureResponse.model_validate(document), structure.to(fmt="cif")


def _selected_table(
    request: GuidedRequest, result: Result, tables: dict[str, PseudoTable]
) -> PseudoTable:
    if request.pseudo_table_id is not None:
        try:
            return tables[request.pseudo_table_id]
        except KeyError as error:
            raise WorkbenchRequestError(
                "recommendation",
                f"Unknown pseudopotential table {request.pseudo_table_id!r}.",
            ) from error
    table_ids = {
        item.provenance.data_source
        for item in result.selection.pseudopotentials
        if item.provenance.data_source in tables
    }
    if len(table_ids) == 1:
        return tables[table_ids.pop()]
    return default_table(tables)


def _selected_pseudo(item: object) -> SelectedPseudoResponse:
    filepath = item.filepath
    filename = item.filename
    if filepath is None or filename is None:
        raise WorkbenchRequestError(
            "recommendation",
            f"Core did not resolve a pseudopotential for {item.element}.",
        )
    return SelectedPseudoResponse(
        element=item.element,
        filename=filename,
        sha256=_sha256_file(Path(filepath)),
        functional=item.functional,
        ecutwfc_ry=item.ecutwfc_ry,
        ecutrho_ry=item.ecutrho_ry,
        provenance=item.provenance.to_dict(),
        warnings=item.warnings,
    )


def _generated_file(file: object) -> GeneratedFileResponse:
    content = file.content
    return GeneratedFileResponse(
        path=file.path,
        role=file.role,
        content=content,
        sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )


def _browser_records(
    result: Result, selection: PseudoSelectionResponse
) -> dict[str, JsonValue]:
    return {
        record_type_id(type(result.analysis)): result.analysis.to_dict(),
        record_type_id(type(result.advice)): result.advice.to_dict(),
        record_type_id(type(result.k_points)): result.k_points.to_dict(),
        record_type_id(type(result.selection)): {
            "pseudopotentials": [
                item.model_dump(mode="json") for item in selection.files
            ],
            "warnings": list(selection.warnings),
        },
        "generated_files": [
            {
                "path": item.path,
                "role": item.role,
            }
            for item in result.generated_files
        ],
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _review_digest(response: RecommendationResponse) -> str:
    payload = response.model_dump(mode="json", exclude={"review_digest"})
    encoded = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _compute_review(service: Service, request: GuidedRequest) -> _ReviewComputation:
    preset, document, canonical_cif = _guided_preset(request, "recommendation")
    try:
        result = service.generate(preset)
    except (FileNotFoundError, ValueError) as error:
        raise WorkbenchRequestError("recommendation", str(error)) from error
    tables = load_tables(service.runtime.pseudo_registry_path)
    table = _selected_table(request, result, tables)
    files = tuple(_selected_pseudo(item) for item in result.selection.pseudopotentials)
    selection = PseudoSelectionResponse(
        table=_table_response(table),
        files=files,
        warnings=result.selection.warnings,
    )
    generated_files = tuple(_generated_file(item) for item in result.generated_files)
    response = RecommendationResponse(
        schema_version=1,
        review_digest="",
        structure=document,
        canonical_cif=canonical_cif,
        intent=IntentResponse.model_validate(result.intent),
        hints=HintsResponse.model_validate(preset.hints),
        records=_browser_records(result, selection),
        generated_files=generated_files,
        selection=selection,
        warnings=result.warnings,
    )
    return _ReviewComputation(
        response=response.model_copy(
            update={"review_digest": _review_digest(response)}
        ),
        result=result,
        table=table,
    )


def install_workbench_routes(
    app: FastAPI, service: Service, capacity: ComputationCapacity
) -> None:
    router = APIRouter(prefix="/api/workbench", tags=["workbench"])

    @app.exception_handler(WorkbenchRequestError)
    async def workbench_request_error_handler(
        request: Request, error: WorkbenchRequestError
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=error.status_code,
            content={
                "error": {
                    "kind": error.kind,
                    "message": str(error),
                    "retryable": error.retryable,
                    "details": {"operation": error.operation, **error.details},
                }
            },
        )

    @router.post(
        "/structure",
        operation_id="inspect_workbench_structure",
        response_model=StructureInspectionResponse,
    )
    def inspect_structure(
        request: StructureInspectionRequest,
    ) -> StructureInspectionResponse:
        source = request.source
        try:
            structure, resolved_format = parse_structure_content(
                source.content, source.format
            )
        except StructureInputError as error:
            raise WorkbenchRequestError("structure", str(error)) from error
        document = structure_document(
            structure,
            source_name=source.name,
            source_format=resolved_format,
            source_content=source.content,
        )
        tables = load_tables(service.runtime.pseudo_registry_path)
        return StructureInspectionResponse(
            structure=StructureResponse.model_validate(document),
            canonical_cif=structure.to(fmt="cif"),
            defaults=CalculationDefaults(
                intent=IntentResponse.model_validate(CalculationIntent()),
                hints=HintsResponse.model_validate(CalculationHints()),
            ),
            pseudo_tables=tuple(
                _table_response(table)
                for table in sorted(tables.values(), key=lambda item: item.id)
            ),
        )

    @router.post(
        "/recommendation",
        operation_id="review_workbench_recommendation",
        response_model=RecommendationResponse,
    )
    def recommend(request: GuidedRequest) -> RecommendationResponse:
        with capacity.acquire():
            return _compute_review(service, request).response

    @router.post(
        "/archive",
        operation_id="archive_workbench_recommendation",
        response_class=Response,
        responses={200: {"content": {"application/zip": {}}}},
    )
    def archive(request: ArchiveRequest) -> Response:
        with capacity.acquire():
            computation = _compute_review(service, request)
        current_digest = computation.response.review_digest
        if request.review_digest != current_digest:
            raise WorkbenchRequestError(
                "archive",
                "The reviewed recommendation is stale; recompute before archiving.",
                kind="stale_review",
                status_code=409,
                details={"current_review_digest": current_digest},
            )
        try:
            installed = service.runtime.asset_store.resolve(
                computation.table.asset.id, computation.table.asset.version
            )
            content = build_workbench_archive(
                WorkbenchArchive(
                    source_name=request.source.name,
                    source_content=request.source.content,
                    canonical_cif=computation.response.canonical_cif,
                    review=computation.response.model_dump(mode="json"),
                    result=computation.result,
                    table=computation.table,
                    licence_path=installed.root / "LICENSE.txt",
                )
            )
        except FileNotFoundError as error:
            raise WorkbenchRequestError(
                "archive",
                f"Required archive material is unavailable: {error}",
                kind="assets_unavailable",
                status_code=503,
                retryable=True,
            ) from error
        filename = f"goldilocks-{current_digest[:12]}.zip"
        return Response(
            content=content,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    app.include_router(router)
