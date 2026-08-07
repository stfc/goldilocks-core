"""Core job runner: dispatch a CoreJobRequest to a calculation path."""

from __future__ import annotations

from collections.abc import Callable

from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    CoreJobRequest,
    CoreResult,
    StructureInput,
)
from goldilocks_core.pseudo.pp_metadata import PseudoMetadata
from goldilocks_core.runtime import CoreRuntime


def run_core_job(
    request: CoreJobRequest,
    *,
    runtime: CoreRuntime | None = None,
) -> CoreResult:
    """Run a Core job request by dispatching on ``intent.task``.

    When ``runtime`` is ``None`` a fresh :class:`CoreRuntime` is created for
    this call and closed when it finishes (today's "fresh per call"
    behaviour). When ``runtime`` is given it is reused and its lifetime is
    left to the caller.

    Args:
        request: Serializable job data: structure input, intent, hints,
            pseudopotential metadata, mode, optional k-index model, and
            optional output directory.
        runtime: Optional pre-owned runtime whose model state is reused
            across calls.

    Returns:
        A ``CoreResult`` containing scientific records, generated files when
        requested, and a bundle record when ``generate`` writes a bundle.

    Raises:
        ValueError: If no path is registered for ``intent.task`` or a
            downstream stage rejects its inputs.
    """
    try:
        path = _PATHS[request.intent.task]
    except KeyError:
        available = ", ".join(sorted(_PATHS))
        raise ValueError(
            f"No Core path registered for task={request.intent.task!r}. "
            f"Available: {available}"
        ) from None

    if runtime is None:
        with CoreRuntime() as rt:
            return path(rt, request)
    return path(runtime, request)


def _run_scf(
    runtime: CoreRuntime,
    request: CoreJobRequest,
) -> CoreResult:
    """Dispatch an SCF request on mode to the runtime's composed entrypoints."""
    if request.mode == "recommend":
        return runtime.recommend(request)
    return runtime.generate(request, output_dir=request.output_dir)


_PATHS: dict[str, Callable[[CoreRuntime, CoreJobRequest], CoreResult]] = {
    "scf_single_point": _run_scf,
}


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
        ``CoreResult`` containing analysis, advice, k-points, selection, and
        warnings.
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
) -> CoreResult:
    """Run Load → Analyse → Advise → Kmesh → Select → Generate.

    Args:
        structure: Structure object or structure file path.
        intent: Optional calculation intent.
        hints: Optional operator hints.
        pseudo_metadata: Available pseudopotential metadata.

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
        )
    )
