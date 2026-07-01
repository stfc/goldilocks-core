"""Fixed Core job runner shared by Python, CLI, and future HTTP surfaces."""

from __future__ import annotations

from dataclasses import dataclass

from goldilocks_core.advice import advise_parameters
from goldilocks_core.analysis import analyze_structure
from goldilocks_core.bundle import write_bundle_directory
from goldilocks_core.contracts import (
    AdviseStage,
    AnalyzeStage,
    BundleRecord,
    BundleStage,
    CalculationHints,
    CalculationIntent,
    CoreJobRequest,
    CoreResult,
    GeneratedFile,
    GenerateStage,
    KMeshAdvisor,
    SelectStage,
    StageRecord,
    StructureInput,
)
from goldilocks_core.generation import generate_inputs
from goldilocks_core.io.structures import load_structure
from goldilocks_core.kmesh import resolve_kpoints_from_advice
from goldilocks_core.pseudo.pp_metadata import PseudoMetadata
from goldilocks_core.selection import select_parameters


@dataclass(frozen=True, slots=True)
class Pipeline:
    """Composable stage backends for the Core pipeline.

    Construct with no arguments for the default pipeline; override any
    field to swap that stage's backend. Backends are plain callables with
    the stage signature — no base class, no registry.

    Attributes:
        analyze: Analyze-stage backend.
        advise: Advise-stage backend.
        kmesh: Kmesh-stage backend that resolves concrete k-points.
        select: Select-stage backend that resolves concrete selections.
        generate: Generate-stage backend that writes target-code text.
        bundle: Bundle-stage backend that writes portable outputs.
    """

    analyze: AnalyzeStage = analyze_structure
    advise: AdviseStage = advise_parameters
    kmesh: KMeshAdvisor = resolve_kpoints_from_advice
    select: SelectStage = select_parameters
    generate: GenerateStage = generate_inputs
    bundle: BundleStage = write_bundle_directory


def run_core_job(
    request: CoreJobRequest,
    *,
    pipeline: Pipeline | None = None,
) -> CoreResult:
    """Run a Core job request through the configured staged pipeline.

    Args:
        request: Serializable job data: structure input, intent, hints,
            pseudopotential metadata, mode, and optional output directory.
        pipeline: Optional executable stage composition. When omitted,
            ``Pipeline()`` is used.

    Returns:
        A ``CoreResult`` containing the stage records, scientific records,
        generated files when requested, and bundle record for bundle mode.

    Raises:
        ValueError: If the job mode is unsupported, bundle mode lacks
            ``output_dir``, or a downstream stage rejects its inputs.
    """
    active_pipeline = pipeline or Pipeline()

    stages: list[StageRecord] = []
    structure = load_structure(request.structure)
    stages.append(StageRecord(name="load"))

    analysis = active_pipeline.analyze(structure)
    stages.append(
        StageRecord(
            name="analyze",
            warnings=(*analysis.disorder_warnings, *analysis.analysis_warnings),
        )
    )

    advice = active_pipeline.advise(analysis, request.intent, request.hints)
    stages.append(StageRecord(name="advise"))

    k_points = active_pipeline.kmesh(structure, request.hints, advice.k_points)
    stages.append(StageRecord(name="kmesh", warnings=k_points.provenance.warnings))

    selection = active_pipeline.select(
        structure,
        advice,
        k_points,
        tuple(request.pseudo_metadata),
    )
    stages.append(StageRecord(name="select", warnings=selection.warnings))

    warnings = (
        *analysis.disorder_warnings,
        *analysis.analysis_warnings,
        *k_points.provenance.warnings,
        *selection.warnings,
    )
    generated_files: tuple[GeneratedFile, ...] = ()
    bundle: BundleRecord | None = None

    if request.mode in {"generate", "bundle"}:
        generated_files = active_pipeline.generate(
            structure,
            request.intent,
            advice,
            selection,
        )
        stages.append(StageRecord(name="generate"))

    if request.mode == "bundle":
        if request.output_dir is None:
            raise ValueError("output_dir is required for bundle mode")
        bundle = active_pipeline.bundle(
            CoreResult(
                intent=request.intent,
                analysis=analysis,
                advice=advice,
                selection=selection,
                generated_files=generated_files,
                warnings=warnings,
            ),
            request.output_dir,
        )
        stages.append(StageRecord(name="bundle"))

    return CoreResult(
        intent=request.intent,
        analysis=analysis,
        advice=advice,
        selection=selection,
        generated_files=generated_files,
        warnings=warnings,
        bundle=bundle,
        stages=tuple(stages),
    )


def recommend(
    structure: StructureInput,
    *,
    intent: CalculationIntent | None = None,
    hints: CalculationHints | None = None,
    pseudo_metadata: list[PseudoMetadata] | None = None,
    pipeline: Pipeline | None = None,
) -> CoreResult:
    """Run Load → Analyze → Advise → Kmesh → Select.

    Args:
        structure: Structure object or structure file path.
        intent: Optional calculation intent.
        hints: Optional operator hints.
        pseudo_metadata: Available pseudopotential metadata.
        pipeline: Optional stage backend composition.

    Returns:
        ``CoreResult`` containing analysis, advice, selection, and warnings.
    """
    return run_core_job(
        CoreJobRequest(
            structure=structure,
            intent=intent or CalculationIntent(),
            hints=hints or CalculationHints(),
            mode="recommend",
            pseudo_metadata=tuple(pseudo_metadata or ()),
        ),
        pipeline=pipeline,
    )


def generate(
    structure: StructureInput,
    *,
    intent: CalculationIntent | None = None,
    hints: CalculationHints | None = None,
    pseudo_metadata: list[PseudoMetadata] | None = None,
    pipeline: Pipeline | None = None,
) -> CoreResult:
    """Run Load → Analyze → Advise → Kmesh → Select → Generate.

    Args:
        structure: Structure object or structure file path.
        intent: Optional calculation intent.
        hints: Optional operator hints.
        pseudo_metadata: Available pseudopotential metadata.
        pipeline: Optional stage backend composition.

    Returns:
        ``CoreResult`` with generated files attached.

    Raises:
        ValueError: If generation is requested with unsupported intent or
            incomplete selections.
    """
    return run_core_job(
        CoreJobRequest(
            structure=structure,
            intent=intent or CalculationIntent(),
            hints=hints or CalculationHints(),
            mode="generate",
            pseudo_metadata=tuple(pseudo_metadata or ()),
        ),
        pipeline=pipeline,
    )


def write_bundle(
    structure: StructureInput,
    output_dir: str,
    *,
    intent: CalculationIntent | None = None,
    hints: CalculationHints | None = None,
    pseudo_metadata: list[PseudoMetadata] | None = None,
    pipeline: Pipeline | None = None,
) -> CoreResult:
    """Run the full Core pipeline and write a portable bundle directory.

    Args:
        structure: Structure object or structure file path.
        output_dir: Bundle output directory.
        intent: Optional calculation intent.
        hints: Optional operator hints.
        pseudo_metadata: Available pseudopotential metadata.
        pipeline: Optional stage backend composition.

    Returns:
        ``CoreResult`` with generated files, bundle record, stages, and warnings.

    Raises:
        ValueError: If generation or bundle writing rejects its inputs.
    """
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
