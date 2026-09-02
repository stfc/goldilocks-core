from __future__ import annotations

from goldilocks_core.advice.convergence import ConvergenceAdvice
from goldilocks_core.advice.magnetism import MagnetismAdvice
from goldilocks_core.advice.parameters import ParameterAdvice
from goldilocks_core.advice.pseudo import PseudopotentialRequirements
from goldilocks_core.advice.smearing import SmearingAdvice
from goldilocks_core.advice.soc import SpinOrbitAdvice
from goldilocks_core.advice.vdw import VdwAdvice
from goldilocks_core.analysis import StructureAnalysisRecord, SymmetryUnavailable
from goldilocks_core.calculation import CalculationHints, CalculationIntent
from goldilocks_core.generation.files import GeneratedFile, GeneratedFiles
from goldilocks_core.input_data import DftInputData
from goldilocks_core.io.structures import (
    InlineStructureSource,
    InMemoryStructureSource,
    PathStructureSource,
    StructureInspection,
    StructureSource,
)
from goldilocks_core.kmesh.resolve import KPointSelection
from goldilocks_core.ml.models import ModelSpec
from goldilocks_core.pseudo.metadata import PseudoCutoffs, PseudoMetadata
from goldilocks_core.publication import (
    ArchiveOutput,
    DirectoryOutput,
    OutputTarget,
    Publication,
)
from goldilocks_core.request import (
    CalculationDraft,
    ComputeRequest,
    PresetSelection,
    RecordSelection,
)
from goldilocks_core.result import ComputationResult, Records
from goldilocks_core.runtime.dispatch import (
    Dispatcher,
    UnavailableRecord,
    UnknownTask,
)
from goldilocks_core.runtime.graph import UnknownPreset
from goldilocks_core.runtime.jobs import compute
from goldilocks_core.runtime.models import KMeshService, Runtime
from goldilocks_core.runtime.service import Service
from goldilocks_core.selection import PseudopotentialSelection, SelectionRecord

__all__ = [
    "ArchiveOutput",
    "CalculationDraft",
    "CalculationHints",
    "CalculationIntent",
    "ComputationResult",
    "ComputeRequest",
    "ConvergenceAdvice",
    "DftInputData",
    "DirectoryOutput",
    "Dispatcher",
    "GeneratedFile",
    "GeneratedFiles",
    "InMemoryStructureSource",
    "InlineStructureSource",
    "KMeshService",
    "KPointSelection",
    "MagnetismAdvice",
    "ModelSpec",
    "OutputTarget",
    "ParameterAdvice",
    "PathStructureSource",
    "PresetSelection",
    "PseudoCutoffs",
    "PseudoMetadata",
    "PseudopotentialRequirements",
    "PseudopotentialSelection",
    "Publication",
    "RecordSelection",
    "Records",
    "Runtime",
    "Service",
    "SelectionRecord",
    "SmearingAdvice",
    "SpinOrbitAdvice",
    "StructureAnalysisRecord",
    "StructureInspection",
    "StructureSource",
    "SymmetryUnavailable",
    "UnavailableRecord",
    "UnknownPreset",
    "UnknownTask",
    "VdwAdvice",
    "compute",
]
