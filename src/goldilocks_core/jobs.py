"""Convenience entrypoints for Core jobs."""

from __future__ import annotations

from pathlib import Path

from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    CoreJobRequest,
    CoreRecords,
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
    """Run a Core preset (recommend/generate) and return a full result.

    Use :func:`query_records` for an explicit record subset.
    """
    if request.outputs is not None:
        raise ValueError(
            "run_core_job runs presets; pass request.outputs to query_records "
            "for an explicit record query."
        )
    if runtime is None:
        with CoreRuntime() as owned_runtime:
            return _run_preset(request, owned_runtime)
    return _run_preset(request, runtime)


def query_records(
    request: CoreJobRequest,
    *,
    runtime: CoreRuntime | None = None,
) -> CoreRecords:
    """Compute the explicit record types in ``request.outputs``.

    Use :func:`run_core_job` to run a named preset instead.
    """
    if request.outputs is None:
        raise ValueError(
            "query_records requires request.outputs; use run_core_job to run a preset."
        )
    if runtime is None:
        with CoreRuntime() as owned_runtime:
            return owned_runtime.compute(request.outputs, request)
    return runtime.compute(request.outputs, request)


def _run_preset(
    request: CoreJobRequest,
    runtime: CoreRuntime,
) -> CoreResult:
    """Run the preset selected by ``request.mode`` without owning ``runtime``."""
    if request.mode == "recommend":
        return runtime.recommend(request)
    if request.mode == "generate":
        return runtime.generate(request, output_dir=request.output_dir)
    raise ValueError(f"Unsupported Core job mode: {request.mode}")


def recommend(
    structure: StructureInput,
    *,
    intent: CalculationIntent | None = None,
    hints: CalculationHints | None = None,
    pseudo_metadata: list[PseudoMetadata] | None = None,
) -> CoreResult:
    """Recommend SCF parameters without generating input files."""
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
    """Generate SCF inputs and optionally publish a bundle directory."""
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
