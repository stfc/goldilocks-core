from pymatgen.core import Lattice, Structure

from goldilocks_core import (
    CalculationDraft,
    CalculationHints,
    ComputeRequest,
    InMemoryStructureSource,
    PresetSelection,
    RecordSelection,
    compute,
)
from goldilocks_core.contracts import (
    GeneratedFiles,
    KPointSelection,
    ParameterAdvice,
    PseudoCutoffs,
    PseudoMetadata,
    SelectionRecord,
    StructureAnalysisRecord,
)


def _make_si_structure() -> Structure:
    return Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])


def _make_si_metadata() -> PseudoMetadata:
    return PseudoMetadata(
        filepath="/pseudo/Si.UPF",
        filename="Si.UPF",
        header_format="attr",
        provider="sssp",
        accuracy="efficiency",
        element="Si",
        pseudo_type="NC",
        functional="PBEsol",
        relativistic="scalar",
        cutoffs=PseudoCutoffs(ecutwfc_ry=30, ecutrho_ry=120),
        source_identifier="synthetic/Si.UPF",
    )


def _request(selection) -> ComputeRequest:
    return ComputeRequest(
        draft=CalculationDraft(
            structure=InMemoryStructureSource(_make_si_structure()),
            hints=CalculationHints(k_grid=(3, 3, 3), pseudo_type="NC"),
            pseudo_metadata=(_make_si_metadata(),),
        ),
        selection=selection,
    )


def test_recommendation_preset_runs_staged_core_pipeline() -> None:
    result = compute(_request(PresetSelection("recommend")))

    assert result.records[StructureAnalysisRecord].reduced_formula == "Si"
    assert result.records[KPointSelection].grid == (3, 3, 3)
    assert result.records[SelectionRecord].pseudopotentials[0].filename == "Si.UPF"
    assert GeneratedFiles not in result.records


def test_generation_preset_runs_pipeline_through_generated_files() -> None:
    result = compute(_request(PresetSelection("generate")))

    assert result.records[GeneratedFiles][0].path == "inputs/qe.in"
    assert "3  3  3  0  0  0" in result.records[GeneratedFiles][0].content


def test_explicit_record_selection_returns_one_generic_result() -> None:
    result = compute(
        _request(RecordSelection((StructureAnalysisRecord, ParameterAdvice)))
    )

    assert tuple(result.records) == (StructureAnalysisRecord, ParameterAdvice)
    assert result.to_dict()["selection"] == {"records": ["analysis", "advice"]}


def test_computation_result_serializes_stable_record_ids() -> None:
    iodine = Structure(Lattice.cubic(4.0), ["I"], [[0.0, 0.0, 0.0]])
    result = compute(
        ComputeRequest(
            draft=CalculationDraft(
                structure=InMemoryStructureSource(iodine),
                hints=CalculationHints(k_grid=(8, 8, 8)),
                pseudo_metadata=(),
            ),
            selection=PresetSelection("recommend"),
        )
    )
    document = result.to_dict()

    assert document["records"]["analysis"]["heavy_elements"] == ["I"]
    assert document["records"]["advice"]["spin_orbit"]["consider"] is True
    assert document["records"]["k_points"]["grid"] == [8, 8, 8]
