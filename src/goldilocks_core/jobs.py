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
    StageRecord,
)
from goldilocks_core.generation import generate_inputs
from goldilocks_core.io.structures import load_structure
from goldilocks_core.selection import select_parameters


def run_core_job(request: CoreJobRequest) -> CoreJobResult:
    """Run a Core job request through the fixed staged pipeline."""
    _validate_request(request)

    stages: list[StageRecord] = []
    structure = load_structure(request.structure)
    stages.append(StageRecord(name="load"))

    analysis = analyze_structure(structure)
    stages.append(
        StageRecord(
            name="analyze",
            warnings=(*analysis.disorder_warnings, *analysis.analysis_warnings),
        )
    )

    advice = advise_parameters(analysis, intent=request.intent, hints=request.hints)
    stages.append(StageRecord(name="advise"))

    selection = select_parameters(
        structure,
        advice,
        metadata_list=list(request.pseudo_metadata),
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
            *selection.warnings,
        ),
    )
    generated_files = recommendation.generated_files
    manifest = None
    bundle_path = None

    if request.mode in {"generate", "bundle"}:
        generated_files = generate_inputs(
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
        manifest = write_bundle_directory(recommendation, request.output_dir)
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
