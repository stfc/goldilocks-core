from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from pymatgen.core import Structure

from goldilocks_core.advice import ml_kmesh_advisor
from goldilocks_core.advice.parameters import advise_parameters
from goldilocks_core.analysis import analyze_structure
from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    ComputeRequest,
    ElectronicCharacter,
    GeneratedFiles,
    KMeshAdvisor,
    KPointSelection,
    ParameterAdvice,
    Records,
    SelectionRecord,
    StructureAnalysisRecord,
    StructureInput,
)
from goldilocks_core.generation.registry import generate_inputs
from goldilocks_core.io.structures import load_structure
from goldilocks_core.kmesh.resolve import resolve_kpoints
from goldilocks_core.pseudo.source import PseudoSource, source_for_draft
from goldilocks_core.runtime.graph import Preset, Stage, TaskGraph
from goldilocks_core.runtime.models import Runtime
from goldilocks_core.runtime.task import GraphHandler
from goldilocks_core.selection import select_pseudopotentials


@dataclass(frozen=True, slots=True)
class ScfContext:
    structure_input: StructureInput
    kmesh_advisor: KMeshAdvisor
    metallicity_classifier: Callable[
        [Structure], tuple[ElectronicCharacter, str, float | None]
    ]
    pseudo_source: PseudoSource
    intent: CalculationIntent = field(default_factory=CalculationIntent)
    hints: CalculationHints = field(default_factory=CalculationHints)


SCF_TASK = TaskGraph(
    task="scf_single_point",
    name="Single-point SCF",
    description=("Recommend and generate inputs for a single-point SCF calculation."),
    selectable_outputs=(
        StructureAnalysisRecord,
        ParameterAdvice,
        KPointSelection,
        SelectionRecord,
        GeneratedFiles,
    ),
    stages=(
        Stage(
            output=Structure,
            inputs=(),
            call=lambda *, ctx: load_structure(ctx.structure_input),
            id="load_structure",
            name="Load structure",
            description="Parse and validate the source into a Structure.",
        ),
        Stage(
            output=StructureAnalysisRecord,
            inputs=(Structure,),
            call=lambda structure, *, ctx: analyze_structure(
                structure, metallicity_classifier=ctx.metallicity_classifier
            ),
            id="analyze",
            name="Analyze",
            description="Report structure facts without parameter decisions.",
        ),
        Stage(
            output=KPointSelection,
            inputs=(Structure,),
            call=lambda structure, *, ctx: resolve_kpoints(
                structure, ctx.hints.kmesh, ctx.kmesh_advisor
            ),
            id="resolve_k_points",
            name="Resolve k-points",
            description="Choose the k-point grid from operator hints or a model.",
        ),
        Stage(
            output=ParameterAdvice,
            inputs=(StructureAnalysisRecord,),
            call=lambda analysis, *, ctx: advise_parameters(
                analysis, ctx.intent, ctx.hints
            ),
            id="advise",
            name="Advise",
            description="Recommend provenance-backed calculation parameters.",
        ),
        Stage(
            output=SelectionRecord,
            inputs=(Structure, ParameterAdvice),
            call=lambda structure, advice, *, ctx: select_pseudopotentials(
                structure,
                advice.pseudopotential_requirements,
                ctx.pseudo_source(structure, advice.pseudopotential_requirements),
            ),
            id="select_pseudopotentials",
            name="Select pseudopotentials",
            description=(
                "Resolve the configured source, then select a concrete "
                "pseudopotential for each element."
            ),
        ),
        Stage(
            output=GeneratedFiles,
            inputs=(Structure, ParameterAdvice, SelectionRecord, KPointSelection),
            call=lambda structure, advice, selection, k_points, *, ctx: generate_inputs(
                structure, ctx.intent, advice, selection, k_points
            ),
            id="generate_inputs",
            name="Generate inputs",
            description="Produce target-code input files.",
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


def build_scf_context(
    request: ComputeRequest,
    runtime: Runtime,
) -> ScfContext:
    draft = request.draft
    backend: KMeshAdvisor = runtime.kmesh_service
    if draft.kmesh_model is not None:
        backend = ml_kmesh_advisor(draft.kmesh_model)
    return ScfContext(
        structure_input=draft.structure,
        kmesh_advisor=backend,
        pseudo_source=source_for_draft(
            draft,
            store=runtime.asset_store,
            registry_path=runtime.pseudo_registry_path,
        ),
        metallicity_classifier=runtime.metallicity,
        intent=draft.intent,
        hints=draft.hints,
    )


def collect_scf_warnings(records: Records) -> tuple[str, ...]:
    groups: list[tuple[str, ...]] = []
    analysis = records.get(StructureAnalysisRecord)
    if analysis is not None:
        groups.extend((analysis.disorder_warnings, analysis.analysis_warnings))
    advice = records.get(ParameterAdvice)
    if advice is not None:
        groups.append(_advice_warnings(advice))
    k_points = records.get(KPointSelection)
    if k_points is not None:
        groups.append(k_points.provenance.warnings)
    selection = records.get(SelectionRecord)
    if selection is not None:
        groups.append(selection.warnings)
    return _unique_warnings(*groups)


def _advice_warnings(advice: ParameterAdvice) -> tuple[str, ...]:
    return _unique_warnings(
        advice.smearing.provenance.warnings,
        advice.magnetism.provenance.warnings,
        advice.spin_orbit.provenance.warnings,
        advice.pseudopotential_requirements.provenance.warnings,
        advice.convergence.provenance.warnings,
        advice.vdw.provenance.warnings,
    )


def _unique_warnings(*groups: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(warning for group in groups for warning in group))


SCF_HANDLER = GraphHandler(
    spec=SCF_TASK,
    build_context=build_scf_context,
    collect_warnings=collect_scf_warnings,
)
