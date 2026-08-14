from __future__ import annotations

import pytest
from pymatgen.core import Structure

from goldilocks_core.contracts import (
    ParameterAdvice,
    PresetRequest,
    QueryRequest,
    StructureAnalysisRecord,
)
from goldilocks_core.server.request import RequestError, from_dict


def test_from_dict_parses_complete_generate_request(
    sample_structure_text: str, pseudo_metadata: dict[str, object], tmp_path
) -> None:
    """Parse structure, intent, hints, metadata, mode, and output directory."""
    request = from_dict(
        {
            "structure": sample_structure_text,
            "intent": {"functional": "PBEsol", "pseudo_accuracy": "efficiency"},
            "hints": {"k_grid": [3, 3, 3], "use_vdw": False},
            "mode": "generate",
            "output_dir": str(tmp_path / "bundle"),
            "pseudo_metadata": [pseudo_metadata],
        }
    )

    assert isinstance(request, PresetRequest)
    assert isinstance(request.structure, Structure)
    assert request.structure.reduced_formula == "Si"
    assert request.intent.functional == "PBEsol"
    assert request.hints.k_grid == (3, 3, 3)
    assert request.mode == "generate"
    assert request.output_dir == str(tmp_path / "bundle")
    assert request.pseudo_metadata[0].element == "Si"


def test_from_dict_defers_default_pseudo_source_resolution(
    sample_structure_path: str,
) -> None:
    """Request parsing performs no asset-store or local-root I/O."""
    request = from_dict({"structure": sample_structure_path})

    assert request.pseudo_metadata is None
    assert request.pseudo_root is None
    assert request.pseudo_table is None


def test_from_dict_preserves_exact_pseudopotential_table(
    sample_structure_path: str,
) -> None:
    """Carry the operator-selected table ID without resolving it during parse."""
    request = from_dict(
        {
            "structure": sample_structure_path,
            "pseudo_table": "sssp-pbe-precision-sr",
        }
    )

    assert request.pseudo_table == "sssp-pbe-precision-sr"
    assert request.pseudo_metadata is None
    assert request.pseudo_root is None


def test_from_dict_rejects_multiple_pseudopotential_sources(
    sample_structure_path: str,
    pseudo_metadata: dict[str, object],
) -> None:
    """Require one unambiguous metadata source at the request seam."""
    with pytest.raises(RequestError, match="accepts only one"):
        from_dict(
            {
                "structure": sample_structure_path,
                "pseudo_metadata": [pseudo_metadata],
                "pseudo_table": "sssp-pbe-precision-sr",
            }
        )


def test_from_dict_resolves_output_record_names(sample_structure_path: str) -> None:
    """Resolve query output names through the shared contract catalogue."""
    request = from_dict(
        {
            "structure": sample_structure_path,
            "outputs": ["analysis", "advice"],
        }
    )

    assert isinstance(request, QueryRequest)
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
        {"structure": "Si.cif", "outputs": "advice"},
        {"structure": "Si.cif", "outputs": [3]},
        {"structure": "Si.cif", "mode": 3},
    ],
)
def test_from_dict_maps_bad_types_to_request_error(body: dict[str, object]) -> None:
    """Report malformed field types as RequestError."""
    with pytest.raises(RequestError):
        from_dict(body)


def test_from_dict_rejects_unknown_output_id(sample_structure_path: str) -> None:
    """Reject query record ids outside the public output catalogue."""
    with pytest.raises(RequestError, match="Unknown output record type"):
        from_dict({"structure": sample_structure_path, "outputs": ["Unknown"]})


def test_from_dict_rejects_output_dir_outside_generate(
    sample_structure_path: str,
) -> None:
    """Keep bundle publication specific to generate requests."""
    with pytest.raises(RequestError, match="only valid for generate"):
        from_dict({"structure": sample_structure_path, "output_dir": "bundle"})


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


def test_request_to_dict_round_trips_pymatgen_structure(
    sample_structure_path: str,
) -> None:
    """Deserialize the canonical structure emitted by both request types."""
    structure = Structure.from_file(sample_structure_path)
    requests = (
        PresetRequest(structure=structure),
        QueryRequest(structure=structure, outputs=(StructureAnalysisRecord,)),
    )

    for request in requests:
        parsed = from_dict(request.to_dict())

        assert type(parsed) is type(request)
        assert isinstance(parsed.structure, Structure)
        assert parsed.structure == structure


def test_from_dict_rejects_empty_outputs(sample_structure_path: str) -> None:
    """Reject an empty outputs list."""
    with pytest.raises(RequestError, match="at least one record type id"):
        from_dict({"structure": sample_structure_path, "outputs": []})


def test_from_dict_rejects_empty_output_directory(
    sample_structure_path: str,
) -> None:
    """Reject an empty bundle destination before filesystem access."""
    with pytest.raises(RequestError, match="non-empty"):
        from_dict(
            {
                "structure": sample_structure_path,
                "mode": "generate",
                "output_dir": "",
            }
        )
