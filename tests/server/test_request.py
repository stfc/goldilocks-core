from __future__ import annotations

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.contracts import CoreJobRequest
from goldilocks_core.server.request import RequestError, from_dict


def _si_structure() -> Structure:
    """Return a small Si structure."""
    return Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])


def test_from_dict_parses_path_string_structure() -> None:
    """A path string structure is stored on the request for stage-time loading."""
    request = from_dict({"structure": "Si.cif", "hints": {"k_grid": [3, 3, 3]}})

    assert isinstance(request, CoreJobRequest)
    assert request.structure == "Si.cif"
    assert request.hints.k_grid == (3, 3, 3)


def test_from_dict_parses_inline_cif_content(si_cif_text: str) -> None:
    """Inline CIF text is parsed into a Structure on the request."""
    request = from_dict({"structure": {"content": si_cif_text, "format": "cif"}})

    assert isinstance(request.structure, Structure)
    assert request.structure.reduced_formula == "Si"


def test_from_dict_applies_defaults_for_missing_sections(
    si_cif_text: str,
) -> None:
    """Omitted intent and hints default to their empty constructors."""
    request = from_dict({"structure": {"content": si_cif_text, "format": "cif"}})

    assert request.intent.code == "quantum_espresso"
    assert request.intent.task == "scf_single_point"
    assert request.hints.k_grid is None
    assert request.pseudo_metadata == ()
    assert request.mode == "recommend"
    assert request.output_dir is None
    assert request.kmesh_model is None


def test_from_dict_parses_intent_and_hints(si_cif_text: str) -> None:
    """Intent and hints are built through the shared constructors."""
    request = from_dict(
        {
            "structure": {"content": si_cif_text, "format": "cif"},
            "intent": {"functional": "PBEsol", "pseudo_mode": "precision"},
            "hints": {
                "k_grid": [4, 4, 4],
                "use_vdw": True,
                "vdw_method": "d3bj",
            },
        }
    )

    assert request.intent.functional == "PBEsol"
    assert request.intent.pseudo_mode == "precision"
    assert request.hints.k_grid == (4, 4, 4)
    assert request.hints.use_vdw is True
    assert request.hints.vdw_method == "d3bj"


def test_from_dict_parses_mode_and_output_dir(si_cif_text: str) -> None:
    """Mode and output_dir are parsed and passed through."""
    request = from_dict(
        {
            "structure": {"content": si_cif_text, "format": "cif"},
            "mode": "generate",
            "output_dir": "/tmp/run",
        }
    )

    assert request.mode == "generate"
    assert request.output_dir == "/tmp/run"


def test_from_dict_parses_pseudo_metadata(si_cif_text: str) -> None:
    """Per-request pseudo_metadata is parsed into PseudoMetadata tuples."""
    request = from_dict(
        {
            "structure": {"content": si_cif_text, "format": "cif"},
            "pseudo_metadata": [
                {
                    "filepath": "/p/Si.UPF",
                    "filename": "Si.UPF",
                    "header_format": "attr",
                    "element": "Si",
                    "pseudo_type": "NC",
                    "functional": "PBEsol",
                    "relativistic": "scalar",
                    "sssp_recommended_cutoff": {
                        "ecutwfc_ry": 30.0,
                        "ecutrho_ry": 120.0,
                    },
                }
            ],
        }
    )

    assert len(request.pseudo_metadata) == 1
    assert request.pseudo_metadata[0].filename == "Si.UPF"
    assert request.pseudo_metadata[0].element == "Si"


def test_from_dict_parses_kmesh_model(si_cif_text: str) -> None:
    """A kmesh_model dict is parsed into a ModelSpec."""
    request = from_dict(
        {
            "structure": {"content": si_cif_text, "format": "cif"},
            "kmesh_model": {
                "name": "test-model",
                "version": "1.0",
                "model_type": "random_forest",
                "target": "k_index",
                "feature_set": "cslr",
                "source": "local",
                "location": "/models/model.joblib",
            },
        }
    )

    assert request.kmesh_model is not None
    assert request.kmesh_model.name == "test-model"
    assert request.kmesh_model.location == "/models/model.joblib"


def test_from_dict_rejects_unknown_top_level_key(si_cif_text: str) -> None:
    """Unknown top-level keys are rejected, not silently dropped."""
    with pytest.raises(RequestError, match="Unknown request fields"):
        from_dict(
            {
                "structure": {"content": si_cif_text, "format": "cif"},
                "bogus_field": 1,
            }
        )


def test_from_dict_rejects_missing_structure() -> None:
    """A body without a structure field is rejected."""
    with pytest.raises(RequestError, match="requires 'structure'"):
        from_dict({"hints": {"k_grid": [3, 3, 3]}})


def test_from_dict_rejects_null_structure() -> None:
    """An explicit null structure is rejected."""
    with pytest.raises(RequestError, match="requires 'structure'"):
        from_dict({"structure": None})


def test_from_dict_rejects_bad_structure_type() -> None:
    """A non-string, non-dict structure is rejected."""
    with pytest.raises(RequestError, match="must be a path string"):
        from_dict({"structure": 42})


def test_from_dict_rejects_unknown_intent_key(si_cif_text: str) -> None:
    """Unknown keys in the intent section are rejected."""
    with pytest.raises(RequestError, match="Unknown request fields"):
        from_dict(
            {
                "structure": {"content": si_cif_text, "format": "cif"},
                "intent": {"bogus": 1},
            }
        )


def test_from_dict_rejects_unknown_hints_key(si_cif_text: str) -> None:
    """Unknown keys in the hints section are rejected."""
    with pytest.raises(RequestError, match="Unknown request fields"):
        from_dict(
            {
                "structure": {"content": si_cif_text, "format": "cif"},
                "hints": {"bogus": 1},
            }
        )


def test_from_dict_rejects_bad_hints_type(si_cif_text: str) -> None:
    """A non-object hints value is rejected."""
    with pytest.raises(RequestError, match="must be a JSON object"):
        from_dict(
            {
                "structure": {"content": si_cif_text, "format": "cif"},
                "hints": "not an object",
            }
        )


def test_from_dict_rejects_bad_mode(si_cif_text: str) -> None:
    """An invalid mode string is rejected."""
    with pytest.raises(RequestError, match="must be one of"):
        from_dict(
            {
                "structure": {"content": si_cif_text, "format": "cif"},
                "mode": "bundle",
            }
        )


def test_from_dict_rejects_bad_k_grid_length(si_cif_text: str) -> None:
    """A k_grid with the wrong number of entries is rejected."""
    with pytest.raises(RequestError, match="exactly three"):
        from_dict(
            {
                "structure": {"content": si_cif_text, "format": "cif"},
                "hints": {"k_grid": [2, 2]},
            }
        )


def test_from_dict_rejects_non_dict_body() -> None:
    """A non-object body is rejected."""
    with pytest.raises(RequestError, match="must be a JSON object"):
        from_dict([1, 2, 3])  # type: ignore[arg-type]


def test_from_dict_rejects_kmesh_model_missing_keys(
    si_cif_text: str,
) -> None:
    """A kmesh_model dict missing required keys is rejected."""
    with pytest.raises(RequestError, match="missing required keys"):
        from_dict(
            {
                "structure": {"content": si_cif_text, "format": "cif"},
                "kmesh_model": {"name": "x"},
            }
        )


def test_from_dict_rejects_inline_structure_without_content() -> None:
    """An inline structure dict without content is rejected."""
    with pytest.raises(RequestError, match="requires a 'content' string"):
        from_dict({"structure": {"format": "cif"}})


def test_from_dict_rejects_unparseable_inline_content() -> None:
    """Garbage inline content is rejected as invalid_request."""
    with pytest.raises(RequestError, match="Could not parse"):
        from_dict({"structure": {"content": "not a structure", "format": "cif"}})
