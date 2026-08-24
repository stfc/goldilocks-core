import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core import (
    CalculationDraft,
    CalculationHints,
    CalculationIntent,
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


def make_structure() -> Structure:
    return Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])


def make_metadata() -> PseudoMetadata:
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
        cutoffs=PseudoCutoffs(ecutwfc_ry=35, ecutrho_ry=140),
        source_identifier="synthetic/Si.UPF",
    )


def test_preset_selection_serializes_one_named_preset() -> None:
    from goldilocks_core import PresetSelection

    selection = PresetSelection("recommend")

    assert selection.to_dict() == {"preset": "recommend"}


def test_preset_selection_rejects_an_empty_name() -> None:
    from goldilocks_core import PresetSelection

    with pytest.raises(ValueError, match="PresetSelection.preset"):
        PresetSelection("  ")


def test_record_selection_serializes_stable_record_ids() -> None:
    from goldilocks_core import RecordSelection

    selection = RecordSelection((StructureAnalysisRecord, ParameterAdvice))

    assert selection.to_dict() == {"records": ["analysis", "advice"]}


def test_record_selection_owns_an_immutable_record_tuple() -> None:
    from goldilocks_core import RecordSelection

    records = [StructureAnalysisRecord]
    selection = RecordSelection(records)
    records.clear()

    assert selection.records == (StructureAnalysisRecord,)


def test_record_selection_rejects_non_type_members() -> None:
    from goldilocks_core import RecordSelection

    with pytest.raises(ValueError, match="RecordSelection.records must contain types"):
        RecordSelection(("analysis",))


def test_record_selection_rejects_an_empty_record_set() -> None:
    from goldilocks_core import RecordSelection

    with pytest.raises(ValueError, match="RecordSelection.records"):
        RecordSelection(())


def test_compute_request_rejects_an_invalid_selection_type() -> None:
    from goldilocks_core import ComputeRequest

    with pytest.raises(ValueError, match="ComputeRequest.selection"):
        ComputeRequest(
            draft=CalculationDraft(make_structure()),
            selection=object(),
        )


def test_compute_request_has_one_selection_and_no_execution_mode() -> None:
    from goldilocks_core import ComputeRequest, PresetSelection

    request = ComputeRequest(
        draft=CalculationDraft(
            structure=make_structure(),
            hints=CalculationHints(k_grid=(2, 2, 1)),
        ),
        selection=PresetSelection("generate"),
    )

    data = request.to_dict()
    assert data["selection"] == {"preset": "generate"}
    assert data["draft"]["hints"]["k_grid"] == [2, 2, 1]
    assert "mode" not in data
    assert "output_dir" not in data


def test_result_retains_the_normalized_calculation_draft(tmp_path) -> None:
    from goldilocks_core import (
        CalculationDraft,
        ComputeRequest,
        PresetSelection,
        Service,
    )

    source = tmp_path / "Si.cif"
    source.write_text(make_structure().to(fmt="cif"), encoding="utf-8")
    request = ComputeRequest(
        draft=CalculationDraft(
            structure=source,
            hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
            pseudo_metadata=(make_metadata(),),
        ),
        selection=PresetSelection("recommend"),
    )

    with Service() as service:
        result = service.compute(request)

    assert isinstance(result.draft.structure, Structure)
    assert result.draft.structure.reduced_formula == "Si"
    assert result.to_dict()["draft"]["structure"]["@class"] == "Structure"


def test_computation_result_serializes_records_without_scf_projection() -> None:
    from goldilocks_core import ComputationResult, PresetSelection, Records

    analysis = StructureAnalysisRecord(
        formula="Si1",
        reduced_formula="Si",
        site_count=1,
        elements=("Si",),
        contains_transition_metals=False,
        contains_lanthanides=False,
        contains_actinides=False,
        contains_heavy_elements=False,
        magnetic_elements=(),
        heavy_elements=(),
    )
    result = ComputationResult(
        draft=CalculationDraft(make_structure()),
        task="scf_single_point",
        task_revision="1",
        selection=PresetSelection("recommend"),
        records=Records({StructureAnalysisRecord: analysis}),
        warnings=("Observed condition.",),
    )

    data = result.to_dict()
    assert data["schema_version"] == 1
    assert data["task"] == "scf_single_point"
    assert data["task_revision"] == "1"
    assert data["selection"] == {"preset": "recommend"}
    assert data["records"]["analysis"]["reduced_formula"] == "Si"
    assert data["warnings"] == ["Observed condition."]
    assert data["publication"] is None
    assert "analysis" not in data


def test_service_computes_the_recommendation_preset_as_records() -> None:
    from goldilocks_core import (
        ComputationResult,
        ComputeRequest,
        PresetSelection,
        Service,
    )

    request = ComputeRequest(
        draft=CalculationDraft(
            structure=make_structure(),
            hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
            pseudo_metadata=(make_metadata(),),
        ),
        selection=PresetSelection("recommend"),
    )

    with Service() as service:
        result = service.compute(request)

    assert isinstance(result, ComputationResult)
    assert tuple(result.records) == (
        StructureAnalysisRecord,
        ParameterAdvice,
        KPointSelection,
        SelectionRecord,
    )
    assert result.records[KPointSelection].grid == (2, 2, 1)
    assert result.selection == PresetSelection("recommend")
    assert result.task == "scf_single_point"
    assert result.task_revision == "1"


def test_computation_result_collects_factual_task_warnings() -> None:
    from goldilocks_core import ComputeRequest, PresetSelection, Service

    request = ComputeRequest(
        draft=CalculationDraft(
            structure=make_structure(),
            hints=CalculationHints(
                k_grid=(2, 2, 1),
                k_spacing=0.2,
                pseudo_type="NC",
            ),
            pseudo_metadata=(make_metadata(),),
        ),
        selection=PresetSelection("recommend"),
    )

    with Service() as service:
        result = service.compute(request)

    assert (
        "Both k_grid and k_spacing were provided; explicit grid wins."
        in result.warnings
    )


def test_explicit_records_collect_warnings_from_executed_dependencies() -> None:
    from goldilocks_core import ComputeRequest, RecordSelection, Service

    request = ComputeRequest(
        draft=CalculationDraft(
            structure=make_structure(),
            hints=CalculationHints(
                k_grid=(2, 2, 1),
                k_spacing=0.2,
                pseudo_type="NC",
            ),
            pseudo_metadata=(make_metadata(),),
        ),
        selection=RecordSelection((GeneratedFiles,)),
    )

    with Service() as service:
        result = service.compute(request)

    assert (
        "Both k_grid and k_spacing were provided; explicit grid wins."
        in result.warnings
    )


def test_computation_omits_generic_scientific_reminders() -> None:
    from goldilocks_core import ComputeRequest, PresetSelection, Service

    request = ComputeRequest(
        draft=CalculationDraft(
            structure=make_structure(),
            hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
            pseudo_metadata=(make_metadata(),),
        ),
        selection=PresetSelection("recommend"),
    )

    with Service() as service:
        result = service.compute(request)

    assert all("verify smearing" not in warning.lower() for warning in result.warnings)


def test_compute_rejects_an_unknown_preset_at_the_task_seam() -> None:
    from goldilocks_core import ComputeRequest, PresetSelection, Service, UnknownPreset

    request = ComputeRequest(
        draft=CalculationDraft(make_structure()),
        selection=PresetSelection("missing"),
    )

    with (
        Service() as service,
        pytest.raises(
            UnknownPreset,
            match="Unknown preset 'missing' for task 'scf_single_point'",
        ),
    ):
        service.compute(request)


def test_compute_rejects_an_unknown_calculation_task() -> None:
    from goldilocks_core import (
        ComputeRequest,
        PresetSelection,
        Service,
        UnknownTask,
    )

    request = ComputeRequest(
        draft=CalculationDraft(
            make_structure(),
            intent=CalculationIntent(task="magnetic_nscf"),
        ),
        selection=PresetSelection("recommend"),
    )

    with (
        Service() as service,
        pytest.raises(
            UnknownTask,
            match="No Core task registered for task='magnetic_nscf'",
        ),
    ):
        service.compute(request)


def test_compute_rejects_a_record_not_selectable_for_the_task() -> None:
    from goldilocks_core import (
        ComputeRequest,
        RecordSelection,
        Service,
        UnavailableRecord,
    )

    class FirstUnsupportedRecord:
        pass

    class SecondUnsupportedRecord:
        pass

    request = ComputeRequest(
        draft=CalculationDraft(make_structure()),
        selection=RecordSelection((FirstUnsupportedRecord, SecondUnsupportedRecord)),
    )

    with (
        Service() as service,
        pytest.raises(
            UnavailableRecord,
            match=("FirstUnsupportedRecord, SecondUnsupportedRecord.*scf_single_point"),
        ),
    ):
        service.compute(request)


def test_one_call_compute_uses_the_same_result_contract() -> None:
    from goldilocks_core import ComputeRequest, PresetSelection, compute

    result = compute(
        ComputeRequest(
            draft=CalculationDraft(
                structure=make_structure(),
                hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
                pseudo_metadata=(make_metadata(),),
            ),
            selection=PresetSelection("recommend"),
        ),
        output=None,
    )

    assert result.records[KPointSelection].grid == (2, 2, 1)


def test_service_exposes_one_scientific_execution_method() -> None:
    from goldilocks_core import Service

    with Service() as service:
        assert not hasattr(service, "recommend")
        assert not hasattr(service, "generate")
        assert not hasattr(service, "run_preset")


def test_root_package_has_one_request_result_and_convenience_path() -> None:
    import goldilocks_core

    removed = (
        "PresetRequest",
        "QueryRequest",
        "Result",
        "run_core_job",
        "query_records",
    )

    assert all(not hasattr(goldilocks_core, name) for name in removed)


def test_contract_package_has_no_legacy_request_or_result_types() -> None:
    import goldilocks_core.contracts as contracts

    removed = ("PresetRequest", "QueryRequest", "Result")

    assert all(not hasattr(contracts, name) for name in removed)
