"""Orchestration for the staged Goldilocks Core pipeline."""

from __future__ import annotations

from pymatgen.core import Structure

from goldilocks_core.advice import advise_parameters
from goldilocks_core.analysis import analyse_structure
from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    CoreRecommendation,
    JsonDict,
    ParameterAdvice,
    SelectionRecord,
    StructureAnalysisRecord,
)
from goldilocks_core.io.structures import load_structure
from goldilocks_core.pseudo.pp_metadata import PseudoMetadata
from goldilocks_core.selection import select_parameters
from goldilocks_core.shared.types import StructureInput


def load(structure: StructureInput) -> Structure:
    """Load-stage wrapper for structure inputs."""
    return load_structure(structure)


def analyse(structure: Structure) -> StructureAnalysisRecord:
    """Analyse-stage wrapper for structure facts."""
    return analyse_structure(structure)


def advise(
    analysis: StructureAnalysisRecord,
    intent: CalculationIntent | None = None,
    hints: CalculationHints | None = None,
) -> ParameterAdvice:
    """Advise-stage wrapper for provenance-backed parameter advice."""
    return advise_parameters(analysis, intent=intent, hints=hints)


def select(
    structure: Structure,
    advice: ParameterAdvice,
    metadata_list: list[PseudoMetadata] | None = None,
) -> SelectionRecord:
    """Select-stage wrapper for concrete calculation choices."""
    return select_parameters(structure, advice, metadata_list=metadata_list)


def recommend(
    structure: StructureInput,
    *,
    intent: CalculationIntent | None = None,
    hints: CalculationHints | None = None,
    pseudo_metadata: list[PseudoMetadata] | None = None,
) -> CoreRecommendation:
    """Run Load → Analyse → Advise → Select and return structured output."""
    intent = intent or CalculationIntent()
    loaded_structure = load(structure)
    analysis = analyse(loaded_structure)
    advice = advise_parameters(analysis, intent=intent, hints=hints)
    selection = select_parameters(
        loaded_structure,
        advice,
        metadata_list=pseudo_metadata,
    )

    return CoreRecommendation(
        intent=intent,
        analysis=analysis,
        advice=advice,
        selection=selection,
        warnings=(*analysis.disorder_warnings, *selection.warnings),
    )


def bundle_recommendation(recommendation: CoreRecommendation) -> JsonDict:
    """Bundle-stage manifest for downstream tools and future file output."""
    return recommendation.to_dict()
