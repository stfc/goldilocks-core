from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from pymatgen.core import Structure

from goldilocks_core.advice import ml_kmesh_advisor
from goldilocks_core.advice.parameters import ParameterAdvice, advise_parameters
from goldilocks_core.advice.pseudo import PseudopotentialRequirements
from goldilocks_core.analysis import StructureAnalysisRecord, analyze_structure
from goldilocks_core.calculation import CalculationHints, CalculationIntent
from goldilocks_core.generation.files import GeneratedFiles
from goldilocks_core.generation.registry import generate_inputs
from goldilocks_core.input_data import DftInputData, assemble_dft_input_data
from goldilocks_core.io.structures import NormalizedStructure
from goldilocks_core.kmesh.resolve import KMeshAdvisor, KPointSelection, resolve_kpoints
from goldilocks_core.ml.models import ModelSpec
from goldilocks_core.pseudo.metadata import PseudoMetadata
from goldilocks_core.pseudo.source import PseudoSource, source_for_draft
from goldilocks_core.request import ComputeRequest
from goldilocks_core.result import Records
from goldilocks_core.runtime.graph import Preset, Stage, TaskGraph
from goldilocks_core.runtime.models import Runtime
from goldilocks_core.runtime.task import GraphHandler
from goldilocks_core.selection import SelectionRecord, select_pseudopotentials
from goldilocks_core.types import ElectronicCharacter


@dataclass(frozen=True, slots=True)
class ScfContext:
    normalized_structure: NormalizedStructure
    kmesh_advisor: KMeshAdvisor
    metallicity_classifier: Callable[
        [Structure], tuple[ElectronicCharacter, str, float | None]
    ]
    pseudo_source: PseudoSource
    runtime: Runtime
    runtime_kmesh_model: ModelSpec | None = None
    uses_default_kmesh_model: bool = True
    runtime_metallicity_model: ModelSpec | None = None
    uses_default_metallicity_model: bool = True
    intent: CalculationIntent = field(default_factory=CalculationIntent)
    hints: CalculationHints = field(default_factory=CalculationHints)
    pseudo_cache: list[tuple[PseudoMetadata, ...]] = field(
        default_factory=list, repr=False, compare=False
    )

    def resolve_pseudos(
        self,
        structure: Structure,
        requirements: PseudopotentialRequirements,
    ) -> tuple[PseudoMetadata, ...]:
        if not self.pseudo_cache:
            self.pseudo_cache.append(self.pseudo_source(structure, requirements))
        return self.pseudo_cache[0]


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
        DftInputData,
    ),
    stages=(
        Stage(
            output=Structure,
            inputs=(),
            call=lambda *, ctx: ctx.normalized_structure.structure,
            id="load_structure",
            name="Load structure",
            description="Provide the normalized source as a Structure.",
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
                ctx.resolve_pseudos(structure, advice.pseudopotential_requirements),
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
        Stage(
            output=DftInputData,
            inputs=(
                StructureAnalysisRecord,
                ParameterAdvice,
                KPointSelection,
                SelectionRecord,
                GeneratedFiles,
            ),
            call=lambda analysis, advice, k_points, selection, generated, *, ctx: (
                assemble_dft_input_data(
                    ctx.normalized_structure,
                    ctx.intent,
                    ctx.hints,
                    analysis,
                    advice,
                    k_points,
                    selection,
                    generated,
                    tuple(ctx.pseudo_cache[0]),
                    asset_store=ctx.runtime.asset_store,
                    pseudo_registry_path=ctx.runtime.pseudo_registry_path,
                    model_registry_path=ctx.runtime.model_registry_path,
                    kmesh_model=ctx.runtime_kmesh_model,
                    uses_default_kmesh_model=ctx.uses_default_kmesh_model,
                    metallicity_model=ctx.runtime_metallicity_model,
                    uses_default_metallicity_model=(ctx.uses_default_metallicity_model),
                )
            ),
            id="assemble_dft_input_data",
            name="Assemble DFT Input Data",
            description="Assemble complete trusted calculation input data.",
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
                DftInputData,
            ),
        ),
    ),
)


def build_scf_context(
    request: ComputeRequest,
    normalized_structure: NormalizedStructure,
    runtime: Runtime,
) -> ScfContext:
    draft = request.draft
    backend: KMeshAdvisor = runtime.kmesh_service
    if draft.kmesh_model is not None:
        backend = ml_kmesh_advisor(draft.kmesh_model)
    return ScfContext(
        normalized_structure=normalized_structure,
        kmesh_advisor=backend,
        runtime=runtime,
        runtime_kmesh_model=draft.kmesh_model,
        uses_default_kmesh_model=runtime.uses_default_kmesh_model,
        runtime_metallicity_model=runtime.metallicity_model_spec,
        uses_default_metallicity_model=runtime.uses_default_metallicity_model,
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
