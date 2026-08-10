"""The SCF task: run context, stage graph, and preset result assembly.

This is the one calculation task the runtime ships with. It owns the SCF
run context (request data plus the runtime services the SCF stages need), the
stage adapters that plug the pure stage functions into the generic graph, and
the assembly of a full ``CoreResult`` from a preset's records. New tasks
(nscf, phonons) bring their own context and stage graph; they do not edit the
generic executor or this module.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from pymatgen.core import Structure

from goldilocks_core.advice.parameters import advise_parameters
from goldilocks_core.analysis import analyze_structure
from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    CoreJobRequest,
    CoreRecords,
    CoreResult,
    ElectronicCharacter,
    GeneratedFiles,
    KMeshAdvisor,
    KPointSelection,
    ParameterAdvice,
    SelectionRecord,
    StructureAnalysisRecord,
    StructureInput,
)
from goldilocks_core.generation.registry import generate_inputs
from goldilocks_core.io.structures import load_structure
from goldilocks_core.kmesh.resolve import resolve_kpoints
from goldilocks_core.pseudo.pp_metadata import PseudoMetadata
from goldilocks_core.runtime.graph import Preset, StageSpec, TaskSpec
from goldilocks_core.selection import select_parameters


@dataclass(frozen=True, slots=True)
class ScfContext:
    """Request data and runtime services for the SCF task graph.

    Services (``kmesh_backend``, ``metallicity_classifier``) are required: the
    runtime always supplies them, so there is no silent default that hides a
    missing service. Request data carries the operator inputs.
    """

    structure_input: StructureInput
    kmesh_backend: KMeshAdvisor
    metallicity_classifier: Callable[
        [Structure], tuple[ElectronicCharacter, str, float | None]
    ]
    intent: CalculationIntent = field(default_factory=CalculationIntent)
    hints: CalculationHints = field(default_factory=CalculationHints)
    pseudo_metadata: tuple[PseudoMetadata, ...] = ()


SCF_TASK = TaskSpec(
    task="scf_single_point",
    stages=(
        StageSpec(
            output=Structure,
            inputs=(),
            call=lambda *, ctx: load_structure(ctx.structure_input),
        ),
        StageSpec(
            output=StructureAnalysisRecord,
            inputs=(Structure,),
            call=lambda structure, *, ctx: analyze_structure(
                structure, metallicity_classifier=ctx.metallicity_classifier
            ),
        ),
        StageSpec(
            output=KPointSelection,
            inputs=(Structure,),
            call=lambda structure, *, ctx: resolve_kpoints(
                structure, ctx.hints, ctx.kmesh_backend
            ),
        ),
        StageSpec(
            output=ParameterAdvice,
            inputs=(StructureAnalysisRecord,),
            call=lambda analysis, *, ctx: advise_parameters(
                analysis, ctx.intent, ctx.hints
            ),
        ),
        StageSpec(
            output=SelectionRecord,
            inputs=(Structure, ParameterAdvice),
            call=lambda structure, advice, *, ctx: select_parameters(
                structure, advice, ctx.pseudo_metadata
            ),
        ),
        StageSpec(
            output=GeneratedFiles,
            inputs=(Structure, ParameterAdvice, SelectionRecord, KPointSelection),
            call=lambda structure, advice, selection, k_points, *, ctx: generate_inputs(
                structure, ctx.intent, advice, selection, k_points
            ),
        ),
    ),
    presets=(
        Preset(
            name="recommend",
            outputs=(
                StructureAnalysisRecord,
                ParameterAdvice,
                KPointSelection,
                SelectionRecord,
            ),
        ),
        Preset(
            name="generate",
            outputs=(
                StructureAnalysisRecord,
                ParameterAdvice,
                KPointSelection,
                SelectionRecord,
                GeneratedFiles,
            ),
        ),
    ),
)


def assemble_core_result(
    request: CoreJobRequest,
    records: CoreRecords,
) -> CoreResult:
    """Assemble a full SCF preset result from type-keyed graph records."""
    analysis = records[StructureAnalysisRecord]
    advice = records[ParameterAdvice]
    k_points = records[KPointSelection]
    selection = records[SelectionRecord]
    warnings = _unique_warnings(
        analysis.disorder_warnings,
        analysis.analysis_warnings,
        _advice_warnings(advice),
        k_points.provenance.warnings,
        selection.warnings,
    )
    return CoreResult(
        intent=request.intent,
        analysis=analysis,
        advice=advice,
        k_points=k_points,
        selection=selection,
        generated_files=records.get(GeneratedFiles, ()),
        warnings=warnings,
    )


def _advice_warnings(advice: ParameterAdvice) -> tuple[str, ...]:
    """Return warnings from every advice decision."""
    return _unique_warnings(
        advice.smearing.provenance.warnings,
        advice.magnetism.provenance.warnings,
        advice.spin_orbit.provenance.warnings,
        advice.pseudopotentials.provenance.warnings,
        advice.convergence.provenance.warnings,
        advice.vdw.provenance.warnings,
    )


def _unique_warnings(*groups: tuple[str, ...]) -> tuple[str, ...]:
    """Return warnings in first-seen order without duplicates."""
    return tuple(dict.fromkeys(warning for group in groups for warning in group))
