"""Typed contracts for the staged Core recommendation pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pymatgen.core import Structure

from goldilocks_core.pseudo.pp_metadata import PseudoMetadata

ProvenanceSource = Literal[
    "analysis",
    "user_hint",
    "default",
    "model",
    "lookup",
    "fallback",
]


JsonDict = dict[str, Any]
PathLike = str | Path
StructureInput = Structure | PathLike

CodeName = Literal["quantum_espresso"]
CalcTask = Literal["scf_single_point"]
AccuracyLevel = Literal["low", "standard", "high"]
ModelSource = Literal["huggingface", "local"]
ModelType = Literal["random_forest", "cgcnn", "xgboost"]
KPointGrid = tuple[int, int, int]
KPointShift = tuple[int, int, int]
StageName = Literal["load", "analyze", "advise", "select", "generate", "bundle"]
JobMode = Literal["recommend", "generate", "bundle"]
StageStatus = Literal["completed"]
Dimensionality = Literal["3d", "2d", "1d", "molecule", "unknown"]
ElectronicCharacter = Literal["metal", "insulator", "likely_metal", "unknown"]


@dataclass(slots=True)
class StructureFeatureVector:
    """Named numerical feature vector extracted from a structure."""

    values: np.ndarray
    feature_names: list[str]

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(slots=True)
class ModelSpec:
    """Metadata describing a trained model used by the package."""

    name: str
    version: str
    model_type: ModelType
    target: str
    feature_set: str
    source: ModelSource
    location: str
    revision: str | None = None


@dataclass(frozen=True, slots=True)
class KMeshEntry:
    """One indexed k-mesh entry produced from a structure scan."""

    k_index: int
    mesh: KPointGrid
    k_distance_interval: tuple[float, float]
    k_line_density_interval: tuple[float, float] | None
    k_pra: float
    n_reduced_kpoints: int


@dataclass(frozen=True, slots=True)
class Provenance:
    """Reason and source for a scientific recommendation or selection."""

    source: ProvenanceSource
    reason: str
    data_source: str | None = None
    confidence: float | None = None
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class CalculationIntent:
    """Operator intent for a Core recommendation."""

    code: CodeName = "quantum_espresso"
    task: CalcTask = "scf_single_point"
    functional: str = "PBE"
    accuracy_level: AccuracyLevel = "standard"
    pseudo_mode: str = "efficiency"

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class CalculationHints:
    """Optional operator overrides for values Core can otherwise decide."""

    k_spacing: float | None = None
    k_grid: KPointGrid | None = None
    smearing_type: str | None = None
    smearing_width_ry: float | None = None
    spin_polarized: bool | None = None
    spin_orbit_coupling: bool | None = None
    pseudo_mode: str | None = None
    pseudo_type: str | None = None
    relativistic_mode: str | None = None
    conv_thr: float | None = None
    mixing_beta: float | None = None
    electron_maxstep: int | None = None

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class StructureAnalysisRecord:
    """Facts reported by the Analyze stage without parameter decisions."""

    formula: str
    reduced_formula: str
    site_count: int
    elements: tuple[str, ...]
    contains_transition_metals: bool
    contains_lanthanides: bool
    contains_actinides: bool
    contains_heavy_elements: bool
    magnetic_elements: tuple[str, ...]
    heavy_elements: tuple[str, ...]
    disorder_warnings: tuple[str, ...] = ()
    disordered_site_count: int = 0
    space_group_symbol: str | None = None
    space_group_number: int | None = None
    crystal_system: str | None = None
    dimensionality: Dimensionality = "unknown"
    electronic_character: ElectronicCharacter = "unknown"
    analysis_warnings: tuple[str, ...] = ()

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class KPointAdvice:
    """Advised reciprocal-space sampling intent."""

    spacing: float | None
    explicit_grid: KPointGrid | None
    mesh_type: str
    provenance: Provenance

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class SmearingAdvice:
    """Advised occupation smearing settings."""

    smearing_type: str | None
    width_ry: float | None
    provenance: Provenance

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class MagnetismAdvice:
    """Advised spin-polarization setting."""

    spin_polarized: bool
    magnetic_elements: tuple[str, ...]
    provenance: Provenance

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class SpinOrbitAdvice:
    """Advised spin-orbit setting and SOC relevance facts."""

    enabled: bool
    consider: bool
    heavy_elements: tuple[str, ...]
    provenance: Provenance

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class PseudopotentialAdvice:
    """Advised pseudopotential family and treatment intent."""

    functional: str
    pseudo_mode: str
    pseudo_type: str | None
    relativistic_mode: str
    provenance: Provenance

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class ConvergenceAdvice:
    """Advised convergence defaults for the calculation."""

    conv_thr: float
    provenance: Provenance
    mixing_beta: float = 0.4
    electron_maxstep: int = 80

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class ParameterAdvice:
    """Complete Advise-stage output."""

    k_points: KPointAdvice
    smearing: SmearingAdvice
    magnetism: MagnetismAdvice
    spin_orbit: SpinOrbitAdvice
    pseudopotentials: PseudopotentialAdvice
    convergence: ConvergenceAdvice

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class KPointSelection:
    """Concrete k-point grid selected from advice."""

    grid: KPointGrid
    shift: KPointShift
    mesh_type: str
    provenance: Provenance

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class PseudopotentialSelection:
    """Concrete pseudopotential selected for one element."""

    element: str
    filename: str | None
    filepath: str | None
    ecutwfc_ry: float | None
    ecutrho_ry: float | None
    provenance: Provenance
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class SelectionRecord:
    """Complete Select-stage output."""

    k_points: KPointSelection
    pseudopotentials: tuple[PseudopotentialSelection, ...]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class GeneratedFile:
    """Generated text file content for a target DFT code."""

    path: str
    content: str
    role: str = "input"

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class CoreRecommendation:
    """Structured output from the staged Core pipeline."""

    intent: CalculationIntent
    analysis: StructureAnalysisRecord
    advice: ParameterAdvice
    selection: SelectionRecord
    generated_files: tuple[GeneratedFile, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class CoreJobRequest:
    """Request for running the fixed Core stage graph."""

    structure: StructureInput
    intent: CalculationIntent = field(default_factory=CalculationIntent)
    hints: CalculationHints = field(default_factory=CalculationHints)
    mode: JobMode = "recommend"
    pseudo_metadata: tuple[PseudoMetadata, ...] = ()
    output_dir: str | None = None

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class StageRecord:
    """Observable execution record for one fixed Core pipeline stage."""

    name: StageName
    status: StageStatus = "completed"
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class CoreJobResult:
    """Result from running a Core job request through the fixed stage graph."""

    request: CoreJobRequest
    recommendation: CoreRecommendation
    stages: tuple[StageRecord, ...]
    generated_files: tuple[GeneratedFile, ...] = ()
    bundle_path: str | None = None
    manifest: JsonDict | None = None
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


def to_jsonable(value: Any) -> Any:
    """Convert staged pipeline values into JSON-safe Python objects."""
    if is_dataclass(value):
        if not hasattr(value, "__dataclass_fields__"):
            return asdict(value)
        return {
            field.name: to_jsonable(getattr(value, field.name))
            for field in fields(value)
        }

    if isinstance(value, tuple | list):
        return [to_jsonable(item) for item in value]

    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, Structure):
        return value.as_dict()

    if isinstance(value, np.ndarray):
        return value.tolist()

    if isinstance(value, np.generic):
        return value.item()

    return value
