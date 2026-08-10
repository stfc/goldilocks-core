"""Convenience entrypoints for Core jobs."""

from __future__ import annotations

from pathlib import Path

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
    """Dispatch a Core job mode through a fresh or caller-owned runtime."""
    if runtime is None:
        with CoreRuntime() as owned_runtime:
            return _run_with_runtime(request, owned_runtime)
    return _run_with_runtime(request, runtime)


def _run_with_runtime(request: CoreJobRequest, runtime: CoreRuntime) -> CoreResult:
    """Dispatch ``request`` without taking ownership of ``runtime``."""
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
