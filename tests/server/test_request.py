from __future__ import annotations

import pytest
from pymatgen.core import Structure

from goldilocks_core.contracts import ParameterAdvice, StructureAnalysisRecord
from goldilocks_core.server.request import RequestError, from_dict


def test_from_dict_parses_complete_generate_request(
    sample_structure_text: str, pseudo_metadata: dict[str, object], tmp_path
) -> None:
    """Parse structure, intent, hints, metadata, mode, and output directory."""
    request = from_dict(
        {
            "structure": sample_structure_text,
            "intent": {"functional": "PBEsol", "pseudo_mode": "efficiency"},
            "hints": {"k_grid": [3, 3, 3], "use_vdw": False},
            "mode": "generate",
            "output_dir": str(tmp_path / "bundle"),
            "pseudo_metadata": [pseudo_metadata],
        }
    )

    assert isinstance(request.structure, Structure)
    assert request.structure.reduced_formula == "Si"
    assert request.intent.functional == "PBEsol"
    assert request.hints.k_grid == (3, 3, 3)
    assert request.mode == "generate"
    assert request.output_dir == str(tmp_path / "bundle")
    assert request.pseudo_metadata[0].element == "Si"


def test_from_dict_resolves_output_record_names(sample_structure_path: str) -> None:
    """Resolve query output names through the shared contract catalogue."""
    request = from_dict(
        {
            "structure": sample_structure_path,
            "outputs": ["StructureAnalysisRecord", "ParameterAdvice"],
        }
    )

    assert request.outputs == (StructureAnalysisRecord, ParameterAdvice)


def test_from_dict_rejects_unknown_keys(sample_structure_path: str) -> None:
    """Do not silently discard unknown transport fields."""
    with pytest.raises(RequestError, match="Unknown request fields: surprise"):
        from_dict({"structure": sample_structure_path, "surprise": True})


@pytest.mark.parametrize(
    "body",
    [
        {"structure": 42},
        {"structure": "Si.cif", "intent": []},
        {"structure": "Si.cif", "hints": {"use_vdw": "yes"}},
        {"structure": "Si.cif", "outputs": "ParameterAdvice"},
        {"structure": "Si.cif", "outputs": [3]},
        {"structure": "Si.cif", "mode": 3},
    ],
)
def test_from_dict_maps_bad_types_to_request_error(body: dict[str, object]) -> None:
    """Report malformed field types as RequestError."""
    with pytest.raises(RequestError):
        from_dict(body)


def test_from_dict_rejects_unknown_output_name(sample_structure_path: str) -> None:
    """Reject query record names outside the public output catalogue."""
    with pytest.raises(RequestError, match="Unknown output record type"):
        from_dict({"structure": sample_structure_path, "outputs": ["Unknown"]})


def test_from_dict_rejects_output_dir_outside_generate(
    sample_structure_path: str,
) -> None:
    """Keep bundle publication specific to generate requests."""
    with pytest.raises(RequestError, match="only valid for generate"):
        from_dict({"structure": sample_structure_path, "output_dir": "bundle"})
