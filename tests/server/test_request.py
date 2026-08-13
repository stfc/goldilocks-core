from __future__ import annotations

import pytest
from pymatgen.core import Structure

from goldilocks_core.contracts import (
    ParameterAdvice,
    PresetRequest,
    PseudoMetadata,
    QueryRequest,
    StructureAnalysisRecord,
)
from goldilocks_core.examples import structure
from goldilocks_core.server.request import RequestError, from_dict


def test_from_dict_parses_complete_preset_request(
    sample_structure_text: str,
) -> None:
    """Parse structure, intent, hints, and mode into a preset request."""
    request = from_dict(
        {
            "structure": sample_structure_text,
            "intent": {"functional": "PBEsol", "pseudo_mode": "efficiency"},
            "hints": {"k_grid": [3, 3, 3], "use_vdw": False},
            "mode": "generate",
        }
    )

    assert isinstance(request, PresetRequest)
    assert isinstance(request.structure, Structure)
    assert request.structure.reduced_formula == "Si"
    assert request.intent.functional == "PBEsol"
    assert request.hints.k_grid == (3, 3, 3)
    assert request.mode == "generate"
    assert request.output_dir is None
    assert request.pseudo_metadata == ()
    assert request.kmesh_model is None


def test_from_dict_resolves_installed_pseudos_by_default(
    monkeypatch: pytest.MonkeyPatch,
    sample_structure_text: str,
) -> None:
    """Resolve the installed table for every transport request."""
    installed = (
        PseudoMetadata(
            filepath="/pseudo/Si.UPF",
            filename="Si.UPF",
            header_format="attr",
            element="Si",
        ),
    )
    monkeypatch.setattr(
        "goldilocks_core.server.request.load_installed_pseudo_metadata",
        lambda: installed,
    )

    request = from_dict({"structure": sample_structure_text})

    assert request.pseudo_metadata == installed


def test_from_dict_resolves_output_record_names(sample_structure_text: str) -> None:
    """Resolve query output names through the shared contract catalogue."""
    request = from_dict(
        {
            "structure": sample_structure_text,
            "outputs": ["analysis", "advice"],
        }
    )

    assert isinstance(request, QueryRequest)
    assert request.outputs == (StructureAnalysisRecord, ParameterAdvice)


def test_from_dict_rejects_unknown_keys(sample_structure_text: str) -> None:
    """Do not silently discard unknown transport fields."""
    with pytest.raises(RequestError, match="Unknown request fields: surprise"):
        from_dict({"structure": sample_structure_text, "surprise": True})


@pytest.mark.parametrize(
    "field",
    ["output_dir", "pseudo_metadata", "pseudo_root", "kmesh_model"],
)
def test_from_dict_rejects_deployment_configuration(
    sample_structure_text: str, field: str
) -> None:
    """Deployment configuration is never request data on the transports."""
    body = {"structure": sample_structure_text, field: "anything"}

    with pytest.raises(RequestError, match=f"Unknown request fields: {field}"):
        from_dict(body)


def test_from_dict_rejects_path_form_structure(tmp_path) -> None:
    """A bare string names no server path; transports require inline content."""
    structure_path = str(structure("Si.cif"))
    assert "\n" not in structure_path

    with pytest.raises(RequestError, match="do not accept file paths"):
        from_dict({"structure": structure_path})


def test_from_dict_parses_inline_structure_string(sample_structure_text: str) -> None:
    """Parse a multi-line CIF passed directly as a string."""
    request = from_dict({"structure": sample_structure_text, "outputs": ["analysis"]})

    assert isinstance(request, QueryRequest)
    assert isinstance(request.structure, Structure)
    assert request.structure.reduced_formula == "Si"


def test_from_dict_parses_inline_structure_content_object(
    sample_structure_text: str,
) -> None:
    """Parse an inline structure content object with an explicit format."""
    request = from_dict(
        {
            "structure": {"content": sample_structure_text, "format": "cif"},
            "outputs": ["analysis"],
        }
    )

    assert isinstance(request, QueryRequest)
    assert isinstance(request.structure, Structure)
    assert request.structure.reduced_formula == "Si"


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
        PresetRequest(structure=structure_obj),
        QueryRequest(structure=structure_obj, outputs=(StructureAnalysisRecord,)),
    )
    transport_keys = {"structure", "intent", "hints", "mode", "outputs"}

    for request in requests:
        body = {
            key: value
            for key, value in request.to_dict().items()
            if key in transport_keys
        }
        parsed = from_dict(body)

        assert type(parsed) is type(request)
        assert isinstance(parsed.structure, Structure)
        assert parsed.structure == structure_obj
