"""Fixed Core job runner shared by Python, CLI, and future HTTP surfaces."""

from __future__ import annotations

from dataclasses import replace

from goldilocks_core.advice import advise_parameters
from goldilocks_core.analysis import analyze_structure
from goldilocks_core.bundle import write_bundle_directory
from goldilocks_core.contracts import (
    CoreJobRequest,
    CoreJobResult,
    CoreRecommendation,
    Pipeline,
    StageRecord,
)
from goldilocks_core.generation import generate_inputs
from goldilocks_core.io.structures import load_structure
from goldilocks_core.kmesh import resolve_kpoints_from_advice
from goldilocks_core.selection import select_parameters


def default_pipeline() -> Pipeline:
    """Return the built-in Core stage backend composition.

    Returns:
        A ``Pipeline`` wired to the package's default Analyze, Advise, Kmesh,
        Select, Generate, and Bundle implementations.
    """
    return Pipeline(
        analyze=analyze_structure,
        advise=advise_parameters,
        kmesh=resolve_kpoints_from_advice,
        select=select_parameters,
        generate=generate_inputs,
        bundle=write_bundle_directory,
    )


def run_core_job(
    request: CoreJobRequest,
    *,
    pipeline: Pipeline | None = None,
) -> CoreJobResult:
    """Run a Core job request through the configured staged pipeline.

    Args:
        request: Serializable job data: structure input, intent, hints,
            pseudopotential metadata, mode, and optional output directory.
        pipeline: Optional executable stage composition. When omitted,
            ``default_pipeline()`` is used.

    Returns:
        A ``CoreJobResult`` containing the request, recommendation, stage
        records, generated files when requested, bundle path/manifest for bundle
        mode, and aggregated warnings.

    Raises:
        ValueError: If the job mode is unsupported, bundle mode lacks
            ``output_dir``, or a downstream stage rejects its inputs.
    """
    _validate_request(request)
    active_pipeline = pipeline or default_pipeline()

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

    recommendation = CoreRecommendation(
        intent=request.intent,
        analysis=analysis,
        advice=advice,
        selection=selection,
        warnings=(
            *analysis.disorder_warnings,
            *analysis.analysis_warnings,
            *k_points.provenance.warnings,
            *selection.warnings,
        ),
    )
    generated_files = recommendation.generated_files
    manifest = None
    bundle_path = None

    if request.mode in {"generate", "bundle"}:
        generated_files = active_pipeline.generate(
            structure,
            request.intent,
            advice,
            selection,
        )
        recommendation = replace(recommendation, generated_files=generated_files)
        stages.append(StageRecord(name="generate"))

    if request.mode == "bundle":
        if request.output_dir is None:
            raise ValueError("output_dir is required for bundle mode")
        manifest = active_pipeline.bundle(recommendation, request.output_dir)
        bundle_path = request.output_dir
        stages.append(StageRecord(name="bundle"))

    return CoreJobResult(
        request=request,
        recommendation=recommendation,
        stages=tuple(stages),
        generated_files=generated_files,
        bundle_path=bundle_path,
        manifest=manifest,
        warnings=recommendation.warnings,
    )


def _validate_request(request: CoreJobRequest) -> None:
    """Validate job-level inputs before running stages."""
    if request.mode not in {"recommend", "generate", "bundle"}:
        raise ValueError(f"Unsupported Core job mode: {request.mode}")

    if request.mode == "bundle" and request.output_dir is None:
        raise ValueError("output_dir is required for bundle mode")
