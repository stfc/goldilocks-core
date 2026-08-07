"""Callable stage signatures for the Core recommendation pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Sequence

from pymatgen.core import Structure

from goldilocks_core.contracts.records import (
    BundleRecord,
    CalculationHints,
    CalculationIntent,
    CoreResult,
    GeneratedFile,
    KPointAdvice,
    KPointSelection,
    ParameterAdvice,
    SelectionRecord,
    StructureAnalysisRecord,
)
from goldilocks_core.pseudo.pp_metadata import PseudoMetadata

AnalyzeStage = Callable[[Structure], StructureAnalysisRecord]
"""Analyze-stage backend signature."""

AdviseStage = Callable[
    [StructureAnalysisRecord, CalculationIntent, CalculationHints],
    ParameterAdvice,
]
"""Advise-stage backend signature."""

KMeshAdvisor = Callable[[Structure, CalculationHints, KPointAdvice], KPointSelection]
"""Kmesh-stage backend signature."""

SelectStage = Callable[
    [Structure, ParameterAdvice, KPointSelection, Sequence[PseudoMetadata]],
    SelectionRecord,
]
"""Select-stage backend signature."""

GenerateStage = Callable[
    [Structure, CalculationIntent, ParameterAdvice, SelectionRecord],
    tuple[GeneratedFile, ...],
]
"""Generate-stage backend signature."""

BundleStage = Callable[[CoreResult, str | Path], BundleRecord]
"""Bundle-stage backend signature."""
