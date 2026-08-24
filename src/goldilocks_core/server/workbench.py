from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib.metadata import version as package_version
from pathlib import Path, PurePath
from typing import Literal

from fastapi import APIRouter, FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, JsonValue, field_validator

from goldilocks_core.analysis import DimensionalityClassificationError
from goldilocks_core.assets import (
    AssetCorrupt,
    AssetNotInstalled,
    AssetSpec,
    AssetStore,
)
from goldilocks_core.contracts import (
    CalculationDraft,
    CalculationHints,
    CalculationIntent,
    ComputationResult,
    ComputeRequest,
    GeneratedFiles,
    KPointSelection,
    ParameterAdvice,
    PresetSelection,
    SelectionRecord,
    StructureAnalysisRecord,
    record_type_id,
)
from goldilocks_core.generation import GenerationError
from goldilocks_core.io.structures import (
    StructureInputError,
    parse_structure_content,
    structure_document,
)
from goldilocks_core.ml.model_registry import model_asset_specs
from goldilocks_core.pseudo.registry import (
    PseudoTable,
    load_tables,
)
from goldilocks_core.pseudo.source import (
    PseudoTableMismatch,
    is_table_eligible_for_elements,
)
from goldilocks_core.runtime import Service, UnknownTask
from goldilocks_core.server.archive import (
    RuntimeAssetLicence,
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


class WorkbenchErrorDetail(_Document):
    kind: str
    message: str
    retryable: bool
    details: dict[str, JsonValue]


class WorkbenchErrorResponse(_Document):
    error: WorkbenchErrorDetail


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
    relativistic: str | None
    ecutwfc_ry: float | None
    ecutrho_ry: float | None
    provenance: dict[str, JsonValue]
    warnings: tuple[str, ...]


class PseudoSelectionResponse(_Document):
    table: PseudoTableResponse
    files: tuple[SelectedPseudoResponse, ...]
    warnings: tuple[str, ...]


class RecommendationDecisions(_Document):
    k_grid: tuple[int, int, int]
    k_shift: tuple[int, int, int]
    k_mesh_type: str
    spin_polarized: bool
    spin_orbit_coupling: bool
    smearing_type: str | None
    smearing_width_ry: float | None
    use_vdw: bool
    pseudo_table_id: str
    pseudo_functional: str
    pseudo_accuracy: Literal["efficiency", "precision"]
    pseudo_relativistic: str


class RuntimeModelResponse(_Document):
    name: str | None
    version: str | None
    model_type: str | None
    target: str | None
    feature_set: str | None
    source: str | None
    revision: str | None


class RuntimeAssetFileResponse(_Document):
    role: str
    path: str
    sha256: str | None
    size_bytes: int | None


class RuntimeAssetResponse(_Document):
    id: str
    version: str
    files: tuple[RuntimeAssetFileResponse, ...]


class RuntimeProvenanceResponse(_Document):
    goldilocks_core_version: str
    models: tuple[RuntimeModelResponse, ...]
    model_assets: tuple[RuntimeAssetResponse, ...]


class RecommendationResponse(_Document):
    schema_version: int
    review_digest: str
    structure: StructureResponse
    canonical_cif: str
    intent: IntentResponse
    hints: HintsResponse
    decisions: RecommendationDecisions
    runtime: RuntimeProvenanceResponse
    records: dict[str, JsonValue]
    generated_files: tuple[GeneratedFileResponse, ...]
    selection: PseudoSelectionResponse
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ReviewComputation:
    response: RecommendationResponse
    result: ComputationResult
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


def _runtime_provenance(service: Service) -> RuntimeProvenanceResponse:
    model_fields = (
        "name",
        "version",
        "model_type",
        "target",
        "feature_set",
        "source",
        "revision",
    )
    models = tuple(
        RuntimeModelResponse(**{field: model.get(field) for field in model_fields})
        for model in service.runtime.describe_models()
    )
    assets = tuple(
        RuntimeAssetResponse(
            id=spec.id,
            version=spec.version,
            files=tuple(
                RuntimeAssetFileResponse(
                    role=file.role,
                    path=file.path,
                    sha256=(
                        file.checksum.removeprefix("sha256:")
                        if file.checksum is not None
                        else None
                    ),
                    size_bytes=file.size,
                )
                for file in spec.files
            ),
        )
        for spec in model_asset_specs(service.runtime.model_registry_path)
    )
    return RuntimeProvenanceResponse(
        goldilocks_core_version=package_version("goldilocks-core"),
        models=models,
        model_assets=assets,
    )


def _archive_licences(
    service: Service, table: PseudoTable
) -> tuple[Path, tuple[RuntimeAssetLicence, ...]]:
    store = service.runtime.asset_store
    pseudo_licence = _required_asset_file(store, table.asset, "LICENSE.txt")
    model_licences: list[RuntimeAssetLicence] = []
    for spec in model_asset_specs(service.runtime.model_registry_path):
        licence = next(file for file in spec.files if file.role == "licence")
        model_licences.append(
            RuntimeAssetLicence(
                asset_id=spec.id,
                version=spec.version,
                source_url=licence.url,
                path=_required_asset_file(store, spec, licence.path),
            )
        )
    return pseudo_licence, tuple(model_licences)


def _required_asset_file(
    store: AssetStore, spec: AssetSpec, relative_path: str
) -> Path:
    try:
        return store.resolve_spec(spec).path(relative_path)
    except (AssetCorrupt, AssetNotInstalled, FileNotFoundError, KeyError) as error:
        raise WorkbenchRequestError(
            "archive",
            f"Required licence material for runtime asset {spec.id!r} is unavailable.",
            kind="assets_unavailable",
            status_code=503,
            retryable=True,
            details={"asset_id": spec.id, "version": spec.version},
        ) from error


def _guided_preset(
    request: GuidedRequest, operation: str
) -> tuple[ComputeRequest, StructureResponse, str]:
    source = request.source
    try:
        structure, resolved_format = parse_structure_content(
            source.content, source.format
        )
        preset = ComputeRequest(
            draft=CalculationDraft(
                structure=structure,
                intent=CalculationIntent(**request.intent.model_dump()),
                hints=CalculationHints(**request.hints.model_dump()),
                pseudo_table=request.pseudo_table_id,
            ),
            selection=PresetSelection("generate"),
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
    request: GuidedRequest,
    result: ComputationResult,
    tables: dict[str, PseudoTable],
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
        for item in result.records[SelectionRecord].pseudopotentials
        if item.provenance.data_source in tables
    }
    if len(table_ids) != 1:
        raise WorkbenchRequestError(
            "recommendation",
            "Core did not report one pseudopotential table for this result.",
        )
    return tables[table_ids.pop()]


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
        relativistic=item.relativistic,
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
    result: ComputationResult, selection: PseudoSelectionResponse
) -> dict[str, JsonValue]:
    return {
        record_type_id(StructureAnalysisRecord): result.records[
            StructureAnalysisRecord
        ].to_dict(),
        record_type_id(ParameterAdvice): result.records[ParameterAdvice].to_dict(),
        record_type_id(KPointSelection): result.records[KPointSelection].to_dict(),
        record_type_id(SelectionRecord): {
            "pseudopotentials": [
                item.model_dump(mode="json") for item in selection.files
            ],
            "warnings": list(selection.warnings),
        },
        record_type_id(GeneratedFiles): [
            {
                "path": item.path,
                "role": item.role,
            }
            for item in result.records[GeneratedFiles]
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
        result = service.compute(preset)
    except AssetNotInstalled as error:
        reference = error.reference
        raise WorkbenchRequestError(
            "recommendation",
            f"Required runtime asset {reference.id}@{reference.version} "
            "is unavailable.",
            kind="assets_unavailable",
            status_code=503,
            details={"asset_id": reference.id, "version": reference.version},
        ) from error
    except (AssetCorrupt, FileNotFoundError) as error:
        raise WorkbenchRequestError(
            "recommendation",
            "A required runtime asset failed availability or integrity checks.",
            kind="assets_unavailable",
            status_code=503,
        ) from error
    except (
        DimensionalityClassificationError,
        GenerationError,
        PseudoTableMismatch,
        UnknownTask,
    ) as error:
        raise WorkbenchRequestError("recommendation", str(error)) from error
    tables = load_tables(service.runtime.pseudo_registry_path)
    table = _selected_table(request, result, tables)
    selection_record = result.records[SelectionRecord]
    files = tuple(_selected_pseudo(item) for item in selection_record.pseudopotentials)
    selection = PseudoSelectionResponse(
        table=_table_response(table),
        files=files,
        warnings=selection_record.warnings,
    )
    generated_files = tuple(
        _generated_file(item) for item in result.records[GeneratedFiles]
    )
    response = RecommendationResponse(
        schema_version=1,
        review_digest="",
        structure=document,
        canonical_cif=canonical_cif,
        intent=IntentResponse.model_validate(result.draft.intent),
        hints=HintsResponse.model_validate(result.draft.hints),
        decisions=RecommendationDecisions(
            k_grid=result.records[KPointSelection].grid,
            k_shift=result.records[KPointSelection].shift,
            k_mesh_type=result.records[KPointSelection].mesh_type,
            spin_polarized=result.records[ParameterAdvice].magnetism.spin_polarized,
            spin_orbit_coupling=result.records[ParameterAdvice].spin_orbit.enabled,
            smearing_type=result.records[ParameterAdvice].smearing.smearing_type,
            smearing_width_ry=result.records[ParameterAdvice].smearing.width_ry,
            use_vdw=result.records[ParameterAdvice].vdw.use_vdw,
            pseudo_table_id=table.id,
            pseudo_functional=table.functional,
            pseudo_accuracy=table.accuracy,
            pseudo_relativistic=table.relativistic,
        ),
        runtime=_runtime_provenance(service),
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

    @app.exception_handler(RequestValidationError)
    async def workbench_validation_error_handler(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        if not request.url.path.startswith("/api/workbench/"):
            return await request_validation_exception_handler(request, error)
        operation = request.url.path.rsplit("/", 1)[-1]
        details = {
            "operation": operation,
            "validation_errors": [
                {
                    "path": ".".join(str(part) for part in item["loc"]),
                    "message": item["msg"],
                    "type": item["type"],
                }
                for item in error.errors()
            ],
        }
        content = WorkbenchErrorResponse(
            error=WorkbenchErrorDetail(
                kind="invalid_request",
                message="The request does not match the Workbench contract.",
                retryable=False,
                details=details,
            )
        )
        return JSONResponse(status_code=422, content=content.model_dump(mode="json"))

    @router.post(
        "/structure",
        operation_id="inspect_workbench_structure",
        response_model=StructureInspectionResponse,
        responses={
            422: {"model": WorkbenchErrorResponse},
        },
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
        elements = {element.symbol for element in structure.composition.elements}
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
                if is_table_eligible_for_elements(table, elements)
            ),
        )

    @router.post(
        "/recommendation",
        operation_id="review_workbench_recommendation",
        response_model=RecommendationResponse,
        responses={
            422: {"model": WorkbenchErrorResponse},
            503: {"model": WorkbenchErrorResponse},
        },
    )
    def recommend(request: GuidedRequest) -> RecommendationResponse:
        with capacity.acquire():
            return _compute_review(service, request).response

    @router.post(
        "/archive",
        operation_id="archive_workbench_recommendation",
        response_class=Response,
        responses={
            200: {"content": {"application/zip": {}}},
            409: {"model": WorkbenchErrorResponse},
            422: {"model": WorkbenchErrorResponse},
            503: {"model": WorkbenchErrorResponse},
        },
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
        licence_path, runtime_licences = _archive_licences(service, computation.table)
        try:
            content = build_workbench_archive(
                WorkbenchArchive(
                    source_name=request.source.name,
                    source_content=request.source.content,
                    canonical_cif=computation.response.canonical_cif,
                    review=computation.response.model_dump(mode="json"),
                    result=computation.result,
                    table=computation.table,
                    licence_path=licence_path,
                    runtime_licences=runtime_licences,
                )
            )
        except (FileNotFoundError, KeyError) as error:
            raise WorkbenchRequestError(
                "archive",
                "Required runtime licence material became unavailable.",
                kind="assets_unavailable",
                status_code=503,
                retryable=True,
                details={"asset_role": "licence"},
            ) from error
        filename = f"goldilocks-{current_digest[:12]}.zip"
        return Response(
            content=content,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    app.include_router(router)
