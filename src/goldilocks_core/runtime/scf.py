from __future__ import annotations

from typing import Any

from pymatgen.core import Structure

from goldilocks_core.advice.parameters import ParameterAdvice, advise_parameters
from goldilocks_core.analysis import StructureAnalysisRecord, analyze_structure
from goldilocks_core.generation.files import GeneratedFiles
from goldilocks_core.generation.registry import generate_inputs
from goldilocks_core.input_data import (
    DftInputData,
    InputRecords,
    assemble_dft_input_data,
)
from goldilocks_core.kmesh.resolve import KPointSelection, resolve_kpoints
from goldilocks_core.request import CalculationResources
from goldilocks_core.runtime.dispatch import GraphHandler
from goldilocks_core.runtime.graph import Preset, Stage, TaskGraph
from goldilocks_core.selection import SelectionRecord

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
                structure, metallicity_classifier=ctx.models.metallicity_classifier
            ),
            id="analyze",
            name="Analyze",
            description="Report structure facts without parameter decisions.",
        ),
        Stage(
            output=KPointSelection,
            inputs=(Structure,),
            call=lambda structure, *, ctx: resolve_kpoints(
                structure, ctx.draft.hints, ctx.models.kmesh_advisor
            ),
            id="resolve_k_points",
            name="Resolve k-points",
            description="Choose the k-point grid from operator hints or a model.",
        ),
        Stage(
            output=ParameterAdvice,
            inputs=(StructureAnalysisRecord,),
            call=lambda analysis, *, ctx: advise_parameters(
                analysis, ctx.draft.intent, ctx.draft.hints
            ),
            id="advise",
            name="Advise",
            description="Recommend provenance-backed calculation parameters.",
        ),
        Stage(
            output=SelectionRecord,
            inputs=(Structure, ParameterAdvice),
            call=lambda structure, advice, *, ctx: ctx.pseudopotentials.select(
                structure, advice["pseudopotential_requirements"]
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
                structure, ctx.draft.intent, advice, selection, k_points
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
                    ctx.draft.intent,
                    ctx.draft.hints,
                    InputRecords(analysis, advice, k_points, selection, generated),
                    ctx.pseudopotentials.materialize(),
                    ctx.models.materialize(analysis, k_points),
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


def collect_scf_warnings(records: dict[type, Any]) -> tuple[str, ...]:
    groups: list[tuple[str, ...]] = []
    analysis = records.get(StructureAnalysisRecord)
    if analysis is not None:
        groups.extend((analysis["disorder_warnings"], analysis["analysis_warnings"]))
    advice = records.get(ParameterAdvice)
    if advice is not None:
        groups.append(_advice_warnings(advice))
    k_points = records.get(KPointSelection)
    if k_points is not None:
        groups.append(k_points["provenance"].warnings)
    selection = records.get(SelectionRecord)
    if selection is not None:
        groups.append(selection["warnings"])
    return _unique_warnings(*groups)


def _advice_warnings(advice: ParameterAdvice) -> tuple[str, ...]:
    return _unique_warnings(
        advice["smearing"]["provenance"].warnings,
        advice["magnetism"]["provenance"].warnings,
        advice["spin_orbit"]["provenance"].warnings,
        advice["pseudopotential_requirements"]["provenance"].warnings,
        advice["convergence"]["provenance"].warnings,
        advice["vdw"]["provenance"].warnings,
    )


def _unique_warnings(*groups: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(warning for group in groups for warning in group))


SCF_HANDLER = GraphHandler(
    spec=SCF_TASK,
    build_context=CalculationResources,
    collect_warnings=collect_scf_warnings,
)
