import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core import (
    CalculationDraft,
    CalculationHints,
    CalculationIntent,
    ComputationResult,
    ComputeRequest,
    InMemoryStructureSource,
    PathStructureSource,
    PresetSelection,
    Records,
    RecordSelection,
    Service,
    UnavailableRecord,
    UnknownPreset,
    UnknownTask,
    compute,
)
from goldilocks_core.advice.parameters import ParameterAdvice
from goldilocks_core.analysis import StructureAnalysisRecord
from goldilocks_core.generation.files import GeneratedFiles
from goldilocks_core.kmesh.resolve import KPointSelection
from goldilocks_core.ml.models import ModelSpec
from goldilocks_core.pseudo.metadata import PseudoMetadata
from goldilocks_core.selection import SelectionRecord
from goldilocks_core.serialization import to_portable


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
        cutoffs={"ecutwfc_ry": 35, "ecutrho_ry": 140},
        source_identifier="synthetic/Si.UPF",
    )


def test_preset_selection_serializes_one_named_preset() -> None:

    selection = PresetSelection("recommend")

    assert to_portable(selection) == {"preset": "recommend"}


def test_preset_selection_rejects_an_empty_name() -> None:

    with pytest.raises(ValueError, match="PresetSelection.preset"):
        PresetSelection("  ")


def test_record_selection_serializes_stable_record_ids() -> None:

    selection = RecordSelection((StructureAnalysisRecord, ParameterAdvice))

    assert to_portable(selection) == {"records": ["analysis", "advice"]}


def test_record_selection_owns_an_immutable_record_tuple() -> None:

    records = [StructureAnalysisRecord]
    selection = RecordSelection(records)
    records.clear()

    assert selection.records == (StructureAnalysisRecord,)


def test_record_selection_rejects_non_type_members() -> None:

    with pytest.raises(ValueError, match="RecordSelection.records must contain types"):
        RecordSelection(("analysis",))


def test_record_selection_rejects_an_empty_record_set() -> None:

    with pytest.raises(ValueError, match="RecordSelection.records"):
        RecordSelection(())


@pytest.mark.parametrize("filename", ("/tmp/Si.UPF", "../Si.UPF", r"C:\\Si.UPF"))
def test_pseudo_metadata_rejects_a_path_as_its_filename(filename: str) -> None:
    with pytest.raises(ValueError, match="filename must be one filename"):
        PseudoMetadata(
            filepath="/pseudo/Si.UPF",
            filename=filename,
            header_format="attr",
        )


def test_pseudo_metadata_serialization_is_a_payload_free_review_snapshot() -> None:
    metadata = make_metadata()
    object.__setattr__(
        metadata,
        "pseudo_info",
        {
            "licence": "Secret-Licence",
            "licence_text": "SECRET PSEUDO LEGAL PAYLOAD",
            "raw": b"SECRET PSEUDO BYTES",
        },
    )

    document = to_portable(metadata)

    assert document["filename"] == "Si.UPF"
    assert document["source_identifier"] == "synthetic/Si.UPF"
    assert document["functional"] == "PBEsol"
    assert "filepath" not in document
    assert "pseudo_info" not in document
    assert "SECRET" not in str(document)


def test_model_spec_serialization_is_a_payload_free_review_snapshot() -> None:
    model = ModelSpec(
        name="operator-model",
        version="2026.1",
        model_type="random_forest",
        target="k_index",
        feature_set="operator-features",
        source="local",
        location="/secret/host/operator.joblib",
        revision="model-revision",
        licence="Operator-Licence",
        licence_text="SECRET MODEL LEGAL PAYLOAD",
        citation="Stable model citation.",
    )

    document = to_portable(model)

    assert document == {
        "name": "operator-model",
        "version": "2026.1",
        "model_type": "random_forest",
        "target": "k_index",
        "feature_set": "operator-features",
        "source": "local",
        "revision": "model-revision",
        "licence": "Operator-Licence",
        "citation": "Stable model citation.",
    }
    assert "/secret/host" not in str(document)
    assert "SECRET" not in str(document)


def test_compute_request_rejects_an_invalid_selection_type() -> None:

    with pytest.raises(ValueError, match="ComputeRequest.selection"):
        ComputeRequest(
            draft=CalculationDraft(InMemoryStructureSource(make_structure())),
            selection=object(),
        )


def test_compute_request_serializes_the_draft_and_selection() -> None:

    request = ComputeRequest(
        draft=CalculationDraft(
            structure=InMemoryStructureSource(make_structure()),
            hints=CalculationHints(k_grid=(2, 2, 1)),
        ),
        selection=PresetSelection("generate"),
    )

    data = to_portable(request)
    assert data["selection"] == {"preset": "generate"}
    assert data["draft"]["hints"]["k_grid"] == [2, 2, 1]


def test_result_retains_the_normalized_calculation_draft(tmp_path) -> None:

    source = tmp_path / "Si.cif"
    source.write_text(make_structure().to(fmt="cif"), encoding="utf-8")
    request = ComputeRequest(
        draft=CalculationDraft(
            structure=PathStructureSource(source),
            hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
            pseudo_metadata=(make_metadata(),),
        ),
        selection=PresetSelection("recommend"),
    )

    with Service() as service:
        result = service.compute(request)

    assert result.draft.structure["source"]["origin"] == "path"
    assert result.draft.structure["structure"]["reduced_formula"] == "Si"
    assert to_portable(result)["draft"]["structure"]["source"]["name"] == "Si.cif"
    assert str(tmp_path) not in str(to_portable(result))


def test_computation_result_serializes_records_without_scf_projection() -> None:

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
        draft=CalculationDraft(InMemoryStructureSource(make_structure())),
        task="scf_single_point",
        task_revision="1",
        selection=PresetSelection("recommend"),
        records=Records({StructureAnalysisRecord: analysis}),
        warnings=("Observed condition.",),
    )

    data = to_portable(result)
    assert data["schema_version"] == 1
    assert data["task"] == "scf_single_point"
    assert data["task_revision"] == "1"
    assert data["selection"] == {"preset": "recommend"}
    assert data["records"]["analysis"]["reduced_formula"] == "Si"
    assert data["warnings"] == ["Observed condition."]
    assert data["publication"] is None
    assert "analysis" not in data


def test_service_computes_the_recommendation_preset_as_records() -> None:

    request = ComputeRequest(
        draft=CalculationDraft(
            structure=InMemoryStructureSource(make_structure()),
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

    request = ComputeRequest(
        draft=CalculationDraft(
            structure=InMemoryStructureSource(make_structure()),
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

    request = ComputeRequest(
        draft=CalculationDraft(
            structure=InMemoryStructureSource(make_structure()),
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

    request = ComputeRequest(
        draft=CalculationDraft(
            structure=InMemoryStructureSource(make_structure()),
            hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
            pseudo_metadata=(make_metadata(),),
        ),
        selection=PresetSelection("recommend"),
    )

    with Service() as service:
        result = service.compute(request)

    assert all("verify smearing" not in warning.lower() for warning in result.warnings)


def test_compute_rejects_an_unknown_preset_at_the_task_seam() -> None:

    request = ComputeRequest(
        draft=CalculationDraft(InMemoryStructureSource(make_structure())),
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

    request = ComputeRequest(
        draft=CalculationDraft(
            InMemoryStructureSource(make_structure()),
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

    class FirstUnsupportedRecord:
        pass

    class SecondUnsupportedRecord:
        pass

    request = ComputeRequest(
        draft=CalculationDraft(InMemoryStructureSource(make_structure())),
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

    result = compute(
        ComputeRequest(
            draft=CalculationDraft(
                structure=InMemoryStructureSource(make_structure()),
                hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
                pseudo_metadata=(make_metadata(),),
            ),
            selection=PresetSelection("recommend"),
        ),
        output=None,
    )

    assert result.records[KPointSelection].grid == (2, 2, 1)
