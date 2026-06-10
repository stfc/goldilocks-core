"""Orchestration for the staged Goldilocks Core pipeline."""

from __future__ import annotations

from pymatgen.core import Structure

from goldilocks_core.advice import advise_parameters
from goldilocks_core.analysis import analyze_structure
from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    CoreJobRequest,
    CoreJobResult,
    CoreRecommendation,
    JsonDict,
    KPointSelection,
    ParameterAdvice,
    Pipeline,
    SelectionRecord,
    StructureAnalysisRecord,
    StructureInput,
)
from goldilocks_core.io.structures import load_structure
from goldilocks_core.pseudo.pp_metadata import PseudoMetadata
from goldilocks_core.selection import select_parameters


def load(structure: StructureInput) -> Structure:
    """Load-stage wrapper for structure inputs."""
    return load_structure(structure)


def analyze(structure: Structure) -> StructureAnalysisRecord:
    """Analyze-stage wrapper for structure facts."""
    return analyze_structure(structure)


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
    k_points: KPointSelection,
    metadata_list: list[PseudoMetadata] | None = None,
) -> SelectionRecord:
    """Select-stage wrapper for concrete calculation choices."""
    return select_parameters(
        structure,
        advice,
        k_points,
        metadata_list=metadata_list,
    )


def recommend(
    structure: StructureInput,
    *,
    intent: CalculationIntent | None = None,
    hints: CalculationHints | None = None,
    pseudo_metadata: list[PseudoMetadata] | None = None,
    pipeline: Pipeline | None = None,
) -> CoreRecommendation:
    """Run Load → Analyze → Advise → Kmesh → Select."""
    from goldilocks_core.jobs import run_core_job

    result = run_core_job(
        CoreJobRequest(
            structure=structure,
            intent=intent or CalculationIntent(),
            hints=hints or CalculationHints(),
            mode="recommend",
            pseudo_metadata=tuple(pseudo_metadata or ()),
        ),
        pipeline=pipeline,
    )
    return result.recommendation


def generate(
    structure: StructureInput,
    *,
    intent: CalculationIntent | None = None,
    hints: CalculationHints | None = None,
    pseudo_metadata: list[PseudoMetadata] | None = None,
    pipeline: Pipeline | None = None,
) -> CoreRecommendation:
    """Run Load → Analyze → Advise → Kmesh → Select → Generate."""
    from goldilocks_core.jobs import run_core_job

    result = run_core_job(
        CoreJobRequest(
            structure=structure,
            intent=intent or CalculationIntent(),
            hints=hints or CalculationHints(),
            mode="generate",
            pseudo_metadata=tuple(pseudo_metadata or ()),
        ),
        pipeline=pipeline,
    )
    return result.recommendation


def write_bundle(
    structure: StructureInput,
    output_dir: str,
    *,
    intent: CalculationIntent | None = None,
    hints: CalculationHints | None = None,
    pseudo_metadata: list[PseudoMetadata] | None = None,
    pipeline: Pipeline | None = None,
) -> CoreJobResult:
    """Run the full Core pipeline and write a portable bundle directory."""
    from goldilocks_core.jobs import run_core_job

    return run_core_job(
        CoreJobRequest(
            structure=structure,
            intent=intent or CalculationIntent(),
            hints=hints or CalculationHints(),
            mode="bundle",
            pseudo_metadata=tuple(pseudo_metadata or ()),
            output_dir=output_dir,
        ),
        pipeline=pipeline,
    )


def bundle_recommendation(recommendation: CoreRecommendation) -> JsonDict:
    """Return a JSON-safe recommendation manifest dictionary."""
    return recommendation.to_dict()
