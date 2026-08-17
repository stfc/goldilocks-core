"""Typed contracts for the staged Core recommendation pipeline."""

from __future__ import annotations

from goldilocks_core.contracts.advice import (
    ConvergenceAdvice,
    MagnetismAdvice,
    ParameterAdvice,
    PseudopotentialRequirements,
    SmearingAdvice,
    SpinOrbitAdvice,
    VdwAdvice,
)
from goldilocks_core.contracts.analysis import (
    StructureAnalysisRecord,
    SymmetryUnavailable,
)
from goldilocks_core.contracts.hints import (
    CalculationHints,
    CalculationIntent,
    ConvergenceHints,
    KmeshHints,
    PseudoHints,
    SmearingHints,
    SpinHints,
    VdwHints,
)
from goldilocks_core.contracts.kpoints import KMeshEntry, KPointSelection
from goldilocks_core.contracts.models import ModelSpec, StructureFeatureVector
from goldilocks_core.contracts.outputs import (
    OUTPUT_RECORD_TYPES,
    OUTPUT_TYPES_BY_ID,
    resolve_output_types,
)
from goldilocks_core.contracts.protocols import KMeshAdvisor, KMeshService
from goldilocks_core.contracts.provenance import Provenance
from goldilocks_core.contracts.registry import RECORD_TYPE_IDS, record_type_id
from goldilocks_core.contracts.requests import PresetRequest, QueryRequest
from goldilocks_core.contracts.result import (
    BundleRecord,
    GeneratedFile,
    GeneratedFiles,
    Records,
    Result,
)
from goldilocks_core.contracts.selection import (
    PseudoCutoffs,
    PseudoMetadata,
    PseudopotentialSelection,
    SelectionRecord,
)
from goldilocks_core.contracts.serial import to_jsonable
from goldilocks_core.contracts.types import (
    CalcTask,
    CodeName,
    Dimensionality,
    ElectronicCharacter,
    JobMode,
    JsonDict,
    KPointGrid,
    KPointShift,
    ModelSource,
    ModelType,
    PathLike,
    ProvenanceSource,
    PseudoAccuracy,
    PseudoType,
    RecordId,
    RelativisticTreatment,
    SmearingType,
    StageId,
    StructureInput,
    TaskId,
    VdwMethod,
)

__all__ = [
    "BundleRecord",
    "CalcTask",
    "CalculationHints",
    "CalculationIntent",
    "CodeName",
    "ConvergenceAdvice",
    "ConvergenceHints",
    "Records",
    "Result",
    "Dimensionality",
    "ElectronicCharacter",
    "GeneratedFile",
    "GeneratedFiles",
    "JobMode",
    "JsonDict",
    "KMeshAdvisor",
    "KMeshEntry",
    "KmeshHints",
    "KMeshService",
    "KPointGrid",
    "KPointSelection",
    "KPointShift",
    "MagnetismAdvice",
    "ModelSource",
    "ModelSpec",
    "ModelType",
    "OUTPUT_RECORD_TYPES",
    "OUTPUT_TYPES_BY_ID",
    "ParameterAdvice",
    "PathLike",
    "PresetRequest",
    "Provenance",
    "ProvenanceSource",
    "PseudoAccuracy",
    "PseudoCutoffs",
    "PseudoHints",
    "PseudoMetadata",
    "PseudoType",
    "PseudopotentialRequirements",
    "PseudopotentialSelection",
    "QueryRequest",
    "RECORD_TYPE_IDS",
    "RecordId",
    "RelativisticTreatment",
    "SelectionRecord",
    "SmearingAdvice",
    "SmearingHints",
    "SmearingType",
    "SpinHints",
    "SpinOrbitAdvice",
    "StageId",
    "StructureAnalysisRecord",
    "StructureFeatureVector",
    "StructureInput",
    "SymmetryUnavailable",
    "TaskId",
    "VdwAdvice",
    "VdwHints",
    "VdwMethod",
    "record_type_id",
    "resolve_output_types",
    "to_jsonable",
]
