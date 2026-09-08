from dataclasses import replace

import pytest
from pymatgen.core import Structure

from goldilocks_core import (
    CalculationDraft,
    CalculationHints,
    CalculationIntent,
    ComputeRequest,
    InMemoryStructureSource,
    PathStructureSource,
    PresetSelection,
    RecordSelection,
    Service,
    UnavailableRecord,
    UnknownPreset,
    UnknownTask,
    compute,
)
from goldilocks_core.contracts import (
    GeneratedFiles,
    KPointSelection,
    ModelSpec,
    ParameterAdvice,
    PseudoMetadata,
    SelectionRecord,
    StructureAnalysisRecord,
)


@pytest.fixture
def draft(silicon_structure, pseudo_metadata_factory):
    return CalculationDraft(
        structure=InMemoryStructureSource(silicon_structure),
        hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
        pseudo_metadata=(pseudo_metadata_factory("Si"),),
    )


@pytest.mark.parametrize(
    "constructor,value",
    [
        (PresetSelection, "  "),
        (RecordSelection, ()),
        (RecordSelection, ("analysis",)),
    ],
)
def test_selection_rejects_invalid_operator_input(constructor, value) -> None:
    with pytest.raises(ValueError):
        constructor(value)


def test_record_selection_retains_stable_ids_after_caller_mutation() -> None:
    records = [StructureAnalysisRecord, ParameterAdvice]
    selection = RecordSelection(records)
    records.clear()
    assert selection.to_dict() == {"records": ["analysis", "advice"]}


@pytest.mark.parametrize("filename", ("/tmp/Si.UPF", "../Si.UPF", r"C:\Si.UPF"))
def test_pseudo_metadata_rejects_a_path_as_its_filename(filename: str) -> None:
    with pytest.raises(ValueError):
        PseudoMetadata(
            filepath="/pseudo/Si.UPF", filename=filename, header_format="attr"
        )


def test_pseudo_metadata_review_excludes_local_paths_and_payloads(
    pseudo_metadata_factory,
) -> None:
    metadata = replace(
        pseudo_metadata_factory("Si"),
        pseudo_info={
            "licence_text": "SECRET PSEUDO LEGAL PAYLOAD",
            "raw": b"SECRET PSEUDO BYTES",
        },
    )
    document = metadata.to_dict()
    assert document["source_identifier"] == "synthetic/Si.UPF"
    assert "filepath" not in document
    assert "pseudo_info" not in document
    assert "SECRET" not in str(document)


def test_model_review_retains_citation_without_local_paths_or_payloads() -> None:
    model = ModelSpec(
        name="operator-model",
        version="2026.1",
        model_type="random_forest",
        target="k_index",
        feature_set="operator-features",
        source="local",
        location="/secret/host/operator.joblib",
        licence="Operator-Licence",
        licence_text="SECRET MODEL LEGAL PAYLOAD",
        citation="Stable model citation.",
    )
    document = model.to_dict()
    assert document["citation"] == "Stable model citation."
    assert document["licence"] == "Operator-Licence"
    assert "location" not in document
    assert "licence_text" not in document
    assert "/secret/host" not in str(document)
    assert "SECRET" not in str(document)


def test_compute_request_rejects_an_invalid_selection_type(draft) -> None:
    with pytest.raises(ValueError):
        ComputeRequest(draft=draft, selection=object())


def test_recommendation_retains_normalized_input_and_selected_records(
    tmp_path, draft, silicon_structure
) -> None:
    source = tmp_path / "Si.cif"
    source.write_text(silicon_structure.to(fmt="cif"), encoding="utf-8")
    request = ComputeRequest(
        replace(draft, structure=PathStructureSource(source)),
        PresetSelection("recommend"),
    )
    with Service() as service:
        result = service.compute(request)

    assert set(result.records) == {
        StructureAnalysisRecord,
        ParameterAdvice,
        KPointSelection,
        SelectionRecord,
    }
    assert result.records[KPointSelection].grid == (2, 2, 1)
    assert result.draft.structure.source.origin == "path"
    document = result.to_dict()
    assert set(document["records"]) == {"analysis", "advice", "k_points", "selection"}
    assert document["draft"]["structure"]["source"]["name"] == "Si.cif"
    assert str(tmp_path) not in str(document)


def test_selected_record_keeps_warnings_from_executed_dependencies(draft) -> None:
    draft = replace(draft, hints=replace(draft.hints, k_spacing=0.2))
    with Service() as service:
        full = service.compute(ComputeRequest(draft, PresetSelection("recommend")))
        selected = service.compute(
            ComputeRequest(draft, RecordSelection((GeneratedFiles,)))
        )

    k_points = full.records[KPointSelection]
    assert k_points.grid == (2, 2, 1)
    assert set(selected.records) == {GeneratedFiles}
    assert set(k_points.provenance.warnings).issubset(selected.warnings)
    assert selected.warnings == full.warnings


@pytest.mark.parametrize(
    "selection,intent,error",
    [
        (PresetSelection("missing"), CalculationIntent(), UnknownPreset),
        (
            PresetSelection("recommend"),
            CalculationIntent(task="magnetic_nscf"),
            UnknownTask,
        ),
        (RecordSelection((Structure,)), CalculationIntent(), UnavailableRecord),
    ],
)
def test_compute_rejects_unavailable_operator_choices(
    draft, selection, intent, error
) -> None:
    request = ComputeRequest(replace(draft, intent=intent), selection)
    with Service() as service, pytest.raises(error):
        service.compute(request)


def test_one_call_compute_uses_the_same_result_contract(draft) -> None:
    result = compute(ComputeRequest(draft, PresetSelection("recommend")), output=None)
    assert result.records[KPointSelection].grid == (2, 2, 1)
