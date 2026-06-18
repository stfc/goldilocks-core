"""Fixed Core job runner and entry points shared by Python, CLI, and HTTP surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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
)
from goldilocks_core.generation import generate_inputs
from goldilocks_core.io.structures import load_structure
from goldilocks_core.kmesh import resolve_kpoints_from_advice
from goldilocks_core.selection import select_parameters


@dataclass(frozen=True, slots=True)
class Pipeline:
    """Composable stage backends for the Core pipeline.

    Each field is a callable with a typed stage signature. Construct with no
    arguments for the default pipeline; override any field to swap that
    stage's backend. Backends are plain callables — no base class, no
    registry, no plugin loader.

    The request remains data-only and serializable; this record carries
    executable behavior describing how a request is computed.

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
        pipeline: Optional executable stage composition. When omitted, the
            default ``Pipeline()`` is used.

    Returns:
        A ``CoreResult`` accumulator carrying intent, analysis, advice,
        selection, generated files (in generate/bundle modes), the bundle
        record (in bundle mode), the stage execution trace, and aggregated
        warnings. The request is not echoed on the result; the caller already
        has it.

    Raises:
        ValueError: Only via ``CoreJobRequest.__post_init__`` (invalid mode or
            bundle mode without ``output_dir``) or when a downstream stage
            rejects its inputs.
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
        # output_dir is guaranteed non-None for bundle mode by
        # CoreJobRequest.__post_init__.
        in_progress = CoreResult(
            intent=request.intent,
            analysis=analysis,
            advice=advice,
            selection=selection,
            generated_files=generated_files,
            warnings=warnings,
        )
        bundle = active_pipeline.bundle(in_progress, request.output_dir)
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
    structure,
    *,
    intent: CalculationIntent | None = None,
    hints: CalculationHints | None = None,
    pseudo_metadata=None,
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
        ``CoreResult`` with analysis, advice, selection, warnings, and the
        stage execution trace.
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
    structure,
    *,
    intent: CalculationIntent | None = None,
    hints: CalculationHints | None = None,
    pseudo_metadata=None,
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
        ``CoreResult`` with generated input files attached.

    Raises:
        ValueError: If generation rejects its inputs (unsupported intent,
            incomplete selections, or disordered structures).
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
    structure,
    output_dir: str | Path,
    *,
    intent: CalculationIntent | None = None,
    hints: CalculationHints | None = None,
    pseudo_metadata=None,
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
        ``CoreResult`` with generated files, the bundle record (path +
        manifest), the stage execution trace, and warnings.

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
            output_dir=str(output_dir),
        ),
        pipeline=pipeline,
    )
