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
    """Load a structure input for stage-by-stage use.

    Args:
        structure: A pymatgen ``Structure`` or path readable by pymatgen.

    Returns:
        Loaded ``Structure``.
    """
    return load_structure(structure)


def analyze(structure: Structure) -> StructureAnalysisRecord:
    """Analyze a loaded structure for stage-by-stage use.

    Args:
        structure: Loaded pymatgen structure.

    Returns:
        Structure facts used by later stages.
    """
    return analyze_structure(structure)


def advise(
    analysis: StructureAnalysisRecord,
    intent: CalculationIntent | None = None,
    hints: CalculationHints | None = None,
) -> ParameterAdvice:
    """Build provenance-backed parameter advice for stage-by-stage use.

    Args:
        analysis: Structure facts from ``analyze``.
        intent: Optional calculation intent. Defaults to ``CalculationIntent()``.
        hints: Optional operator hints. Defaults to ``CalculationHints()``.

    Returns:
        Complete parameter advice record.
    """
    return advise_parameters(analysis, intent=intent, hints=hints)


def select(
    structure: Structure,
    advice: ParameterAdvice,
    k_points: KPointSelection,
    metadata_list: list[PseudoMetadata] | None = None,
) -> SelectionRecord:
    """Resolve concrete calculation choices for stage-by-stage use.

    Args:
        structure: Loaded structure.
        advice: Parameter advice.
        k_points: Concrete k-point selection from the Kmesh stage.
        metadata_list: Available pseudopotential metadata.

    Returns:
        Concrete selection record.
    """
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
    """Run Load → Analyze → Advise → Kmesh → Select.

    Args:
        structure: Structure object or structure file path.
        intent: Optional calculation intent.
        hints: Optional operator hints.
        pseudo_metadata: Available pseudopotential metadata.
        pipeline: Optional stage backend composition.

    Returns:
        Recommendation containing analysis, advice, selection, and warnings.
    """
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
    """Run Load → Analyze → Advise → Kmesh → Select → Generate.

    Args:
        structure: Structure object or structure file path.
        intent: Optional calculation intent.
        hints: Optional operator hints.
        pseudo_metadata: Available pseudopotential metadata.
        pipeline: Optional stage backend composition.

    Returns:
        Recommendation with generated files attached.

    Raises:
        ValueError: If generation is requested with unsupported intent or
            incomplete selections.
    """
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
    """Run the full Core pipeline and write a portable bundle directory.

    Args:
        structure: Structure object or structure file path.
        output_dir: Bundle output directory.
        intent: Optional calculation intent.
        hints: Optional operator hints.
        pseudo_metadata: Available pseudopotential metadata.
        pipeline: Optional stage backend composition.

    Returns:
        Job result with generated files, bundle path, manifest, stages, and
        warnings.

    Raises:
        ValueError: If generation or bundle writing rejects its inputs.
    """
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
    """Return a JSON-safe recommendation dictionary.

    Args:
        recommendation: Recommendation to serialize.

    Returns:
        ``recommendation.to_dict()``.
    """
    return recommendation.to_dict()
