from __future__ import annotations

import pytest

from goldilocks_core.contracts import StructureAnalysisRecord
from goldilocks_core.examples import structure
from goldilocks_core.server.request import RequestError, from_dict


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


def test_from_dict_parses_inline_structure_content_object(
    sample_structure_text: str,
    test_service,
) -> None:
    """Parse an inline structure content object with an explicit format."""
    request = from_dict(
        {
            "structure": {"content": sample_structure_text, "format": "cif"},
            "outputs": ["analysis"],
        }
    )

    result = test_service.compute(request)
    assert result.records[StructureAnalysisRecord].reduced_formula == "Si"


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
