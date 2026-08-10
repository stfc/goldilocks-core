"""Typed transport schemas driving useful OpenAPI for the Workbench.

These Pydantic models adapt the shared Core parser/delegation path
(``goldilocks_core.server.request.from_dict``) to the HTTP transport. They
document the request and response bodies so generated clients are typed, and
they never add client-controlled server paths to the Workbench surface.
"""

from __future__ import annotations

from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from goldilocks_core.contracts import SmearingType, VdwMethod
from goldilocks_core.contracts.outputs import OUTPUT_TYPES_BY_ID

_OutputName = Literal[*tuple(OUTPUT_TYPES_BY_ID)]
"""Stable record ids accepted by the compute operation.

Derived from the authoritative output-record registry so the HTTP transport
cannot drift from Core's record ids.
"""

StructureFormat = Literal["cif", "poscar"]
"""Inline structure formats the Workbench transport accepts."""


class StructureSource(BaseModel):
    """Inline structure content; never a client server path."""

    model_config = ConfigDict(extra="forbid")

    content: str
    format: StructureFormat | None = None


class StructureLatticeModel(BaseModel):
    """Canonical lattice vectors, parameters, and periodicity."""

    model_config = ConfigDict(extra="allow")

    matrix: list[list[float]]
    a: float
    b: float
    c: float
    alpha: float
    beta: float
    gamma: float
    volume: float
    pbc: list[bool]


class StructureSpeciesModel(BaseModel):
    """One element species on a site with its fractional occupancy."""

    model_config = ConfigDict(extra="allow")

    element: str
    occupancy: float


class StructureSiteModel(BaseModel):
    """One crystallographic site in a canonical Structure Document."""

    model_config = ConfigDict(extra="allow")

    label: str
    species: list[StructureSpeciesModel]
    abc: list[float]
    xyz: list[float]


class StructureSourceInfoModel(BaseModel):
    """Origin metadata for a parsed structure."""

    model_config = ConfigDict(extra="allow")

    format: str | None = None
    source: str = "inline"


class StructureDocumentModel(BaseModel):
    """Canonical, transport-safe representation of a parsed structure."""

    model_config = ConfigDict(extra="allow")

    formula: str
    reduced_formula: str
    lattice: StructureLatticeModel
    sites: list[StructureSiteModel]
    charge: float | None = None
    source: StructureSourceInfoModel


class Intent(BaseModel):
    """Calculation intent fields."""

    model_config = ConfigDict(extra="allow")

    code: str = "quantum_espresso"
    task: str = "scf_single_point"
    functional: str = "PBEsol"
    pseudo_mode: str = "efficiency"


class Hints(BaseModel):
    """Operator hint fields."""

    model_config = ConfigDict(extra="allow")

    k_spacing: float | None = None
    k_grid: list[int] | None = None
    smearing_type: SmearingType | None = None
    smearing_width_ry: float | None = None
    spin_polarized: bool | None = None
    spin_orbit_coupling: bool | None = None
    pseudo_mode: str | None = None
    pseudo_type: str | None = None
    relativistic_mode: str | None = None
    conv_thr: float | None = None
    mixing_beta: float | None = None
    electron_maxstep: int | None = None
    use_vdw: bool | None = None
    vdw_method: VdwMethod | None = None


class PseudoMetadata(BaseModel):
    """Pseudopotential metadata accepted over the Workbench surface.

    Identifies a configured pseudo by its library and filename rather than a
    server filesystem path; ``filepath`` is never accepted from a browser.
    """

    model_config = ConfigDict(extra="allow")

    filename: str | None = None
    header_format: str | None = None
    library: str | None = None
    source_set: str | None = None
    element: str | None = None
    pseudo_type: str | None = None
    functional: str | None = None
    relativistic: str | None = None
    z_valence: float | None = None
    pseudo_info: dict[str, Any] = Field(default_factory=dict)
    is_sssp: bool = False
    source_pseudopotential: str | None = None
    sssp_recommended_cutoff: dict[str, Any] | None = None


class ComputationRequest(BaseModel):
    """Request for the recommend or generate preset.

    The Workbench sends inline structure content and identifies pseudos by
    filename/library; it never supplies server paths. ``output_dir`` and
    ``pseudo_root`` are rejected at the HTTP boundary.
    """

    model_config = ConfigDict(extra="allow")

    structure: StructureSource
    intent: Intent | None = None
    hints: Hints | None = None
    mode: Literal["recommend", "generate"] | None = None
    pseudo_metadata: list[PseudoMetadata] | None = None


class RecordQuery(BaseModel):
    """Request selecting Core records to compute.

    ``outputs`` is structurally optional so the shared parser can reject a
    missing selection with a structured failure.
    """

    model_config = ConfigDict(extra="allow")

    structure: StructureSource
    outputs: list[_OutputName] | None = None
    intent: Intent | None = None
    hints: Hints | None = None
    pseudo_metadata: list[PseudoMetadata] | None = None


class ProvenanceModel(BaseModel):
    """Reason and source for a scientific recommendation or selection."""

    model_config = ConfigDict(extra="allow")

    source: str
    reason: str
    data_source: str | None = None
    confidence: float | None = None
    details: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)


class IntentModel(BaseModel):
    """Serialized CalculationIntent."""

    model_config = ConfigDict(extra="allow")

    code: str
    task: str
    functional: str
    pseudo_mode: str


class AnalysisModel(BaseModel):
    """Serialized StructureAnalysisRecord."""

    model_config = ConfigDict(extra="allow")

    formula: str
    reduced_formula: str
    site_count: int
    elements: list[str]
    contains_transition_metals: bool
    contains_lanthanides: bool
    contains_actinides: bool
    contains_heavy_elements: bool
    magnetic_elements: list[str]
    heavy_elements: list[str]
    disorder_warnings: list[str] = Field(default_factory=list)
    disordered_site_count: int = 0
    space_group_symbol: str | int | dict[str, Any] | None = None
    space_group_number: str | int | dict[str, Any] | None = None
    crystal_system: str | int | dict[str, Any] | None = None
    dimensionality: str = "unknown"
    has_vacuum: bool = False
    electronic_character: str = "unknown"
    electronic_character_source: str = "heuristic"
    electronic_character_confidence: float | None = None
    analysis_warnings: list[str] = Field(default_factory=list)


class SmearingAdviceModel(BaseModel):
    """Serialized SmearingAdvice."""

    model_config = ConfigDict(extra="allow")

    smearing_type: str | None = None
    width_ry: float | None = None
    provenance: ProvenanceModel


class MagnetismAdviceModel(BaseModel):
    """Serialized MagnetismAdvice."""

    model_config = ConfigDict(extra="allow")

    spin_polarized: bool
    magnetic_elements: list[str]
    provenance: ProvenanceModel


class SpinOrbitAdviceModel(BaseModel):
    """Serialized SpinOrbitAdvice."""

    model_config = ConfigDict(extra="allow")

    enabled: bool
    consider: bool
    heavy_elements: list[str]
    provenance: ProvenanceModel


class PseudopotentialAdviceModel(BaseModel):
    """Serialized PseudopotentialAdvice."""

    model_config = ConfigDict(extra="allow")

    functional: str
    pseudo_mode: str
    pseudo_type: str | None = None
    relativistic_mode: str
    provenance: ProvenanceModel


class ConvergenceAdviceModel(BaseModel):
    """Serialized ConvergenceAdvice."""

    model_config = ConfigDict(extra="allow")

    conv_thr: float
    mixing_beta: float = 0.4
    electron_maxstep: int = 80
    provenance: ProvenanceModel


class VdwAdviceModel(BaseModel):
    """Serialized VdwAdvice."""

    model_config = ConfigDict(extra="allow")

    use_vdw: bool
    method: str | None = None
    provenance: ProvenanceModel


class AdviceModel(BaseModel):
    """Serialized ParameterAdvice."""

    model_config = ConfigDict(extra="allow")

    smearing: SmearingAdviceModel
    magnetism: MagnetismAdviceModel
    spin_orbit: SpinOrbitAdviceModel
    pseudopotentials: PseudopotentialAdviceModel
    convergence: ConvergenceAdviceModel
    vdw: VdwAdviceModel


class KPointSelectionModel(BaseModel):
    """Serialized KPointSelection."""

    model_config = ConfigDict(extra="allow")

    grid: list[int]
    shift: list[int]
    mesh_type: str
    provenance: ProvenanceModel


class PseudopotentialSelectionModel(BaseModel):
    """Serialized PseudopotentialSelection on the Workbench surface.

    ``filepath`` stays on the Python/CLI record and is deliberately stripped
    here: the browser must never encounter a server filesystem path.
    """

    model_config = ConfigDict(extra="allow")

    element: str
    filename: str | None = None
    ecutwfc_ry: float | None = None
    ecutrho_ry: float | None = None
    provenance: ProvenanceModel
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _strip_filepath(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            value = dict(value)
            value.pop("filepath", None)
        return value


class SelectionModel(BaseModel):
    """Serialized SelectionRecord."""

    model_config = ConfigDict(extra="allow")

    pseudopotentials: list[PseudopotentialSelectionModel] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class GeneratedFileModel(BaseModel):
    """Serialized GeneratedFile."""

    model_config = ConfigDict(extra="allow")

    path: str
    content: str
    role: str = "input"


class BundleModel(BaseModel):
    """Serialized BundleRecord."""

    model_config = ConfigDict(extra="allow")

    path: str
    manifest: dict[str, Any]


class CoreResultResponse(BaseModel):
    """Response of the recommend and generate presets."""

    model_config = ConfigDict(extra="allow")

    core_version: str
    intent: IntentModel
    analysis: AnalysisModel
    advice: AdviceModel
    k_points: KPointSelectionModel
    selection: SelectionModel
    generated_files: list[GeneratedFileModel] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    bundle: BundleModel | None = None


class RecordSetResponse(BaseModel):
    """Response of the compute operation, keyed by stable record ids."""

    model_config = ConfigDict(extra="allow")

    analysis: AnalysisModel | None = None
    advice: AdviceModel | None = None
    k_points: KPointSelectionModel | None = None
    selection: SelectionModel | None = None
    generated_files: list[GeneratedFileModel] | None = None


class ErrorDetail(BaseModel):
    """One structured transport failure."""

    model_config = ConfigDict(extra="allow")

    kind: str
    message: str
    status: int
    details: dict[str, Any] | list[Any] | str | int | float | bool | None = None


class ErrorResponse(BaseModel):
    """Structured failure envelope returned by the transport."""

    error: ErrorDetail


class StageDescriptionModel(BaseModel):
    """Transport-safe description of one graph stage."""

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    description: str
    input_record_ids: list[str]
    output_record_id: str


class PresetDescriptionModel(BaseModel):
    """Transport-safe description of one named output preset."""

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    output_record_ids: list[str]


class TaskGraphDescriptionModel(BaseModel):
    """Backend-owned, transport-safe description of one task."""

    model_config = ConfigDict(extra="allow")

    id: str
    revision: str
    name: str
    description: str
    stages: list[StageDescriptionModel]
    presets: list[PresetDescriptionModel]
    selectable_record_ids: list[str]


class TaskCatalogueModel(BaseModel):
    """Catalogue of every registered task description."""

    model_config = ConfigDict(extra="allow")

    tasks: list[TaskGraphDescriptionModel]
