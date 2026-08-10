"""Core job runner: dispatch a CoreJobRequest to a calculation path."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from goldilocks_core.advice import advise_parameters
from goldilocks_core.advisors import default_kmesh_advisor, ml_kmesh_advisor
from goldilocks_core.analysis import analyze_structure
from goldilocks_core.bundle import write_bundle_directory
from goldilocks_core.contracts import (
    BundleRecord,
    CalculationHints,
    CalculationIntent,
    CoreJobRequest,
    CoreResult,
    GeneratedFile,
    KMeshAdvisor,
    ModelSpec,
    ParameterAdvice,
    StructureInput,
)
from goldilocks_core.generation import generate_inputs
from goldilocks_core.io.structures import load_structure
from goldilocks_core.kmesh import resolve_kpoints
from goldilocks_core.pseudo.pp_metadata import PseudoMetadata
from goldilocks_core.selection import select_parameters


def run_core_job(request: CoreJobRequest) -> CoreResult:
    """Run a Core job request by dispatching on ``intent.task``.

    Args:
        request: Serializable job data: structure input, intent, hints,
            pseudopotential metadata, mode, optional k-index model, and
            optional output directory.

    Returns:
        A ``CoreResult`` containing scientific records, generated files when
        requested, and a bundle record when generate publishes an output directory.

    Raises:
        ValueError: If the job mode is unsupported, no path is registered for
            ``intent.task``, or a downstream stage rejects its inputs.
    """
    try:
        path = _PATHS[request.intent.task]
    except KeyError:
        available = ", ".join(sorted(_PATHS))
        raise ValueError(
            f"No Core path registered for task={request.intent.task!r}. "
            f"Available: {available}"
        ) from None
    return path(request)


def run_scf(request: CoreJobRequest) -> CoreResult:
    """Run the SCF single-point path.

    Load → Analyse → Advise → Kmesh → Select, then Generate according to
    ``request.mode`` and publish a bundle when ``output_dir`` is set.
    """
    structure = load_structure(request.structure)
    analysis = analyze_structure(structure)
    advice = advise_parameters(analysis, request.intent, request.hints)
    k_points = resolve_kpoints(
        structure, request.hints, _kmesh_backend(request.kmesh_model)
    )
    selection = select_parameters(structure, advice, tuple(request.pseudo_metadata))

    warnings = _unique_warnings(
        analysis.disorder_warnings,
        analysis.analysis_warnings,
        _advice_warnings(advice),
        k_points.provenance.warnings,
        selection.warnings,
    )

    generated_files: tuple[GeneratedFile, ...] = ()
    bundle: BundleRecord | None = None

    if request.mode == "generate":
        generated_files = generate_inputs(
            structure, request.intent, advice, selection, k_points
        )

    if request.mode == "generate" and request.output_dir is not None:
        in_progress = CoreResult(
            intent=request.intent,
            analysis=analysis,
            advice=advice,
            k_points=k_points,
            selection=selection,
            generated_files=generated_files,
            warnings=warnings,
        )
        bundle = write_bundle_directory(in_progress, request.output_dir)

    return CoreResult(
        intent=request.intent,
        analysis=analysis,
        advice=advice,
        k_points=k_points,
        selection=selection,
        generated_files=generated_files,
        warnings=warnings,
        bundle=bundle,
    )


_PATHS: dict[str, Callable[[CoreJobRequest], CoreResult]] = {
    "scf_single_point": run_scf,
}


def _kmesh_backend(kmesh_model: ModelSpec | None) -> KMeshAdvisor:
    """Return the k-point backend: local k-index model when given, else QRF default."""
    if kmesh_model is not None:
        return ml_kmesh_advisor(kmesh_model)
    return default_kmesh_advisor()


def _advice_warnings(advice: ParameterAdvice) -> tuple[str, ...]:
    """Return actionable warnings from every Advise sub-decision."""
    return _unique_warnings(
        advice.smearing.provenance.warnings,
        advice.magnetism.provenance.warnings,
        advice.spin_orbit.provenance.warnings,
        advice.pseudopotentials.provenance.warnings,
        advice.convergence.provenance.warnings,
        advice.vdw.provenance.warnings,
    )


def _unique_warnings(*groups: tuple[str, ...]) -> tuple[str, ...]:
    """Return warnings in first-seen order without duplicate messages."""
    return tuple(dict.fromkeys(warning for group in groups for warning in group))


def recommend(
    structure: StructureInput,
    *,
    intent: CalculationIntent | None = None,
    hints: CalculationHints | None = None,
    pseudo_metadata: list[PseudoMetadata] | None = None,
) -> CoreResult:
    """Run Load → Analyse → Advise → Kmesh → Select.

    Args:
        structure: Structure object or structure file path.
        intent: Optional calculation intent.
        hints: Optional operator hints.
        pseudo_metadata: Available pseudopotential metadata.

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
        )
    )


def generate(
    structure: StructureInput,
    *,
    intent: CalculationIntent | None = None,
    hints: CalculationHints | None = None,
    pseudo_metadata: list[PseudoMetadata] | None = None,
    output_dir: str | Path | None = None,
) -> CoreResult:
    """Run Load → Analyse → Advise → Kmesh → Select → Generate.

    Args:
        structure: Structure object or structure file path.
        intent: Optional calculation intent.
        hints: Optional operator hints.
        pseudo_metadata: Available pseudopotential metadata.
        output_dir: Optional directory in which to publish a portable bundle.

    Returns:
        ``CoreResult`` with generated files and an optional bundle record.

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
            output_dir=str(output_dir) if output_dir is not None else None,
        )
    )
