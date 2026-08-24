from __future__ import annotations

import pytest
from pymatgen.core import Structure

from goldilocks_core.contracts import (
    CalculationDraft,
    ComputeRequest,
    InlineStructureSource,
    InMemoryStructureSource,
    ParameterAdvice,
    PresetSelection,
    RecordSelection,
    StructureAnalysisRecord,
)
from goldilocks_core.examples import structure
from goldilocks_core.server.request import RequestError, from_dict


def body(structure, selection, **draft) -> dict[str, object]:
    return {
        "draft": {"structure": structure, **draft},
        "selection": selection,
    }


def test_from_dict_parses_complete_preset_computation(
    sample_structure_text: str,
    pseudo_metadata: dict[str, object],
) -> None:
    """Parse structure, intent, hints, and mode into a preset request."""
    request = from_dict(
        body(
            {
                "name": "Si.cif",
                "content": sample_structure_text,
                "format": "cif",
            },
            {"preset": "generate"},
            intent={"functional": "PBEsol", "pseudo_accuracy": "efficiency"},
            hints={"k_grid": [3, 3, 3], "use_vdw": False},
            pseudo_metadata=[pseudo_metadata],
        )
    )

    assert isinstance(request, ComputeRequest)
    assert request.selection == PresetSelection("generate")
    assert isinstance(request.draft.structure, InlineStructureSource)
    assert request.draft.structure.name == "Si.cif"
    assert request.draft.intent.functional == "PBEsol"
    assert request.draft.hints.k_grid == (3, 3, 3)
    assert request.draft.pseudo_metadata[0].element == "Si"


def test_from_dict_defers_pseudo_source_resolution(
    sample_structure_text: str,
) -> None:
    request = from_dict(body(sample_structure_path, {"preset": "recommend"}))

    assert request.draft.pseudo_metadata is None
    assert request.draft.pseudo_root is None
    assert request.draft.pseudo_table is None


def test_from_dict_resolves_output_record_names(sample_structure_text: str) -> None:
    """Resolve query output names through the shared contract catalogue."""
    request = from_dict(
        body(
            sample_structure_path,
            {"preset": "recommend"},
            pseudo_table="sssp-pbe-precision-sr",
        )
    )

    assert request.draft.pseudo_table == "sssp-pbe-precision-sr"
    assert request.draft.pseudo_metadata is None
    assert request.draft.pseudo_root is None


def test_from_dict_rejects_multiple_pseudopotential_sources(
    sample_structure_path: str,
    pseudo_metadata: dict[str, object],
) -> None:
    with pytest.raises(RequestError, match="accepts only one"):
        from_dict(
            body(
                sample_structure_path,
                {"preset": "recommend"},
                pseudo_metadata=[pseudo_metadata],
                pseudo_table="sssp-pbe-precision-sr",
            )
        )


def test_from_dict_resolves_selected_record_names(sample_structure_path: str) -> None:
    request = from_dict(
        body(
            sample_structure_path,
            {"records": ["analysis", "advice"]},
        )
    )

    assert request.selection == RecordSelection(
        (StructureAnalysisRecord, ParameterAdvice)
    )


def test_from_dict_rejects_unknown_root_keys(sample_structure_path: str) -> None:
    request = body(sample_structure_path, {"preset": "recommend"})
    request["surprise"] = True

    with pytest.raises(RequestError, match="Unknown request fields: surprise"):
        from_dict(request)


def test_from_dict_rejects_unknown_draft_keys(sample_structure_path: str) -> None:
    request = body(
        sample_structure_path,
        {"preset": "recommend"},
        surprise=True,
    )

    with pytest.raises(RequestError, match="Unknown draft fields: surprise"):
        from_dict(request)


@pytest.mark.parametrize(
    "document",
    [
        body(42, {"preset": "recommend"}),
        body("Si.cif", {"preset": "recommend"}, intent=[]),
        body("Si.cif", {"preset": "recommend"}, hints={"use_vdw": "yes"}),
        body("Si.cif", "recommend"),
        body("Si.cif", {"records": "advice"}),
        body("Si.cif", {"records": [3]}),
    ],
)
def test_from_dict_maps_bad_types_to_request_error(
    document: dict[str, object],
) -> None:
    with pytest.raises(RequestError):
        from_dict(document)


def test_from_dict_requires_a_calculation_draft() -> None:
    with pytest.raises(RequestError, match="requires 'draft'"):
        from_dict({"selection": {"preset": "recommend"}})


def test_from_dict_requires_a_computation_selection(
    sample_structure_path: str,
) -> None:
    with pytest.raises(RequestError, match="requires 'selection'"):
        from_dict({"draft": {"structure": sample_structure_path}})


def test_from_dict_requires_exactly_one_selection_variant(
    sample_structure_path: str,
) -> None:
    with pytest.raises(RequestError, match="exactly one"):
        from_dict(
            body(
                sample_structure_path,
                {"preset": "recommend", "records": ["analysis"]},
            )
        )


def test_from_dict_rejects_unknown_record_id(sample_structure_path: str) -> None:
    with pytest.raises(RequestError, match="Unknown output record type"):
        from_dict(body(sample_structure_path, {"records": ["Unknown"]}))


def test_from_dict_preserves_inline_structure_source(
    sample_structure_text: str,
) -> None:
    """Parse an inline structure content object with an explicit format."""
    request = from_dict(
        body(
            {
                "name": "Si.cif",
                "content": sample_structure_text,
                "format": "cif",
            },
            {"records": ["analysis"]},
        )
    )

    assert request.draft.structure == InlineStructureSource(
        name="Si.cif",
        content=sample_structure_text,
        format="cif",
    )


@pytest.mark.parametrize(
    "body",
    [
        {"structure": 42},
        {"structure": None},
    ],
)
def test_from_dict_maps_bad_structure_types_to_request_error(
    body: dict[str, object],
) -> None:
    """Report malformed structure types as RequestError."""
    with pytest.raises(RequestError):
        from_dict(body)


def test_from_dict_maps_bad_field_types_to_request_error(
    sample_structure_text: str,
) -> None:
    """Report malformed field types as RequestError."""
    bodies = (
        {"structure": sample_structure_text, "intent": []},
        {"structure": sample_structure_text, "hints": {"use_vdw": "yes"}},
        {"structure": sample_structure_text, "outputs": "advice"},
        {"structure": sample_structure_text, "outputs": [3]},
        {"structure": sample_structure_text, "mode": 3},
    )

    for body in bodies:
        with pytest.raises(RequestError):
            from_dict(body)


def test_from_dict_rejects_unknown_output_id(sample_structure_text: str) -> None:
    """Reject query record ids outside the public output catalogue."""
    with pytest.raises(RequestError, match="Unknown output record type"):
        from_dict({"structure": sample_structure_text, "outputs": ["Unknown"]})


def test_from_dict_rejects_empty_outputs(sample_structure_text: str) -> None:
    """Reject an empty outputs list."""
    with pytest.raises(RequestError, match="at least one record type id"):
        from_dict({"structure": sample_structure_text, "outputs": []})


def test_request_to_dict_round_trips_pymatgen_structure(
    sample_structure_path: str,
) -> None:
    """Deserialize the pymatgen structure form emitted by request to_dict."""
    structure_obj = Structure.from_file(sample_structure_path)
    requests = (
        ComputeRequest(
            CalculationDraft(InMemoryStructureSource(structure)),
            PresetSelection("recommend"),
        ),
        ComputeRequest(
            CalculationDraft(InMemoryStructureSource(structure)),
            RecordSelection((StructureAnalysisRecord,)),
        ),
    )
    transport_keys = {"structure", "intent", "hints", "mode", "outputs"}

    for request in requests:
        body = {
            key: value
            for key, value in request.to_dict().items()
            if key in transport_keys
        }
        parsed = from_dict(body)

        assert parsed.selection == request.selection
        assert isinstance(parsed.draft.structure, InMemoryStructureSource)
        assert parsed.draft.structure.structure == structure


def test_from_dict_rejects_empty_record_selection(
    sample_structure_path: str,
) -> None:
    with pytest.raises(RequestError, match="at least one record type id"):
        from_dict(body(sample_structure_path, {"records": []}))
