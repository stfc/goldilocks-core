from __future__ import annotations

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    CoreJobRequest,
)
from goldilocks_core.pseudo.pp_metadata import PseudoMetadata


def _si_structure() -> Structure:
    """Return a small Si structure."""
    return Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])


def _si_pseudo() -> PseudoMetadata:
    """Return a minimal Si pseudopotential metadata instance."""
    return PseudoMetadata(
        filepath="/pseudo/Si.UPF",
        filename="Si.UPF",
        header_format="attr",
        element="Si",
        pseudo_type="NC",
        functional="PBE",
        relativistic="scalar",
        sssp_recommended_cutoff={"ecutwfc_ry": 30.0, "ecutrho_ry": 120.0},
    )


def test_calculation_intent_from_dict_round_trips_to_dict() -> None:
    """from_dict is the exact inverse of to_dict for CalculationIntent."""
    intent = CalculationIntent(functional="PBEsol", pseudo_mode="precision")
    assert CalculationIntent.from_dict(intent.to_dict()) == intent


def test_calculation_hints_from_dict_round_trips_to_dict() -> None:
    """from_dict is the exact inverse of to_dict for CalculationHints."""
    hints = CalculationHints(k_grid=(2, 3, 4), use_vdw=True, vdw_method="d3bj")
    assert CalculationHints.from_dict(hints.to_dict()) == hints


def test_calculation_hints_from_dict_coerces_k_grid_list_to_tuple() -> None:
    """A JSON list for k_grid becomes an immutable tuple."""
    hints = CalculationHints.from_dict({"k_grid": [4, 4, 4]})
    assert hints.k_grid == (4, 4, 4)
    assert isinstance(hints.k_grid, tuple)


def test_pseudo_metadata_from_dict_round_trips_to_dict() -> None:
    """from_dict is the exact inverse of to_dict for PseudoMetadata."""
    pseudo = _si_pseudo()
    assert PseudoMetadata.from_dict(pseudo.to_dict()) == pseudo


def test_core_job_request_from_dict_round_trips_to_dict() -> None:
    """from_dict is the exact inverse of to_dict for a full CoreJobRequest."""
    request = CoreJobRequest(
        structure=_si_structure(),
        intent=CalculationIntent(functional="PBEsol"),
        hints=CalculationHints(k_grid=(3, 3, 3)),
        mode="recommend",
        pseudo_metadata=(_si_pseudo(),),
    )

    restored = CoreJobRequest.from_dict(request.to_dict())

    assert restored.mode == request.mode
    assert restored.structure.reduced_formula == "Si"
    assert restored.intent == request.intent
    assert restored.hints == request.hints
    assert restored.pseudo_metadata == request.pseudo_metadata


def test_core_job_request_from_dict_accepts_path_string_structure() -> None:
    """A path-string structure survives the round trip as a path input."""
    request = CoreJobRequest(structure="path/to/Si.cif", mode="recommend")
    restored = CoreJobRequest.from_dict(request.to_dict())
    assert restored.structure == "path/to/Si.cif"


@pytest.mark.parametrize(
    ("cls", "bad"),
    [
        (CalculationIntent, 1),
        (CalculationHints, "x"),
        (CoreJobRequest, []),
    ],
)
def test_from_dict_rejects_non_dict(cls: type, bad: object) -> None:
    """Non-dict input to from_dict raises ValueError."""
    with pytest.raises(ValueError, match="requires a JSON object"):
        cls.from_dict(bad)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("cls", "payload"),
    [
        (CalculationIntent, {"code": "quantum_espresso", "bogus": 1}),
        (CalculationHints, {"k_grid": [1, 1, 1], "bogus": 2}),
        (CoreJobRequest, {"structure": "Si.cif", "bogus": 3}),
    ],
)
def test_from_dict_rejects_unknown_keys(cls: type, payload: dict) -> None:
    """Unknown keys raise ValueError at the deserialization boundary."""
    with pytest.raises(ValueError, match="Unknown"):
        cls.from_dict(payload)


def test_core_job_request_from_dict_requires_structure() -> None:
    """A request dict without a structure field raises ValueError."""
    with pytest.raises(ValueError, match="'structure'"):
        CoreJobRequest.from_dict({"mode": "recommend"})


def test_core_job_request_from_dict_rejects_unparseable_structure() -> None:
    """A structure value that is neither dict, str, nor Structure raises ValueError."""
    with pytest.raises(ValueError, match="structure"):
        CoreJobRequest.from_dict({"structure": 42})


def test_from_dict_accepts_the_exact_field_set_with_defaults() -> None:
    """from_dict accepts an empty object, filling constructor defaults."""
    assert CalculationIntent.from_dict({}) == CalculationIntent()
    assert CalculationHints.from_dict({}) == CalculationHints()


def test_pseudo_metadata_from_dict_requires_core_fields() -> None:
    """Missing required PseudoMetadata fields raise ValueError."""
    with pytest.raises(ValueError, match="requires fields"):
        PseudoMetadata.from_dict({"filepath": "/p/Si.UPF"})


def test_pseudo_metadata_from_dict_rejects_unknown_keys() -> None:
    """Unknown PseudoMetadata keys raise ValueError."""
    with pytest.raises(ValueError, match="Unknown"):
        PseudoMetadata.from_dict(
            {
                "filepath": "/p/Si.UPF",
                "filename": "Si.UPF",
                "header_format": "attr",
                "bogus": 1,
            }
        )


def test_calculation_intent_from_dict_rejects_unsupported_code() -> None:
    """An unsupported code at the boundary raises ValueError, not silent acceptance."""
    with pytest.raises(ValueError, match="intent.code"):
        CalculationIntent.from_dict({"code": "vasp"})


def test_calculation_intent_from_dict_rejects_non_string_functional() -> None:
    """A non-string functional raises ValueError rather than being coerced."""
    with pytest.raises(ValueError, match="functional"):
        CalculationIntent.from_dict({"functional": 3})


@pytest.mark.parametrize("bad", [3, "3", [[1, 1, 1]], [[1, 2, 3]]])
def test_calculation_hints_from_dict_rejects_malformed_k_grid(bad: object) -> None:
    """A non-grid k_grid raises ValueError (422), never a TypeError from tuple()."""
    with pytest.raises(ValueError):
        CalculationHints.from_dict({"k_grid": bad})


def test_pseudo_metadata_from_dict_rejects_non_bool_is_sssp() -> None:
    """A truthy non-bool is_sssp is rejected rather than silently coerced."""
    payload = _si_pseudo().to_dict()
    payload["is_sssp"] = "yes"
    with pytest.raises(ValueError, match="is_sssp"):
        PseudoMetadata.from_dict(payload)


def test_pseudo_metadata_from_dict_rejects_non_object_pseudo_info() -> None:
    """A null/non-dict pseudo_info raises ValueError, not a TypeError from dict()."""
    payload = _si_pseudo().to_dict()
    payload["pseudo_info"] = None
    with pytest.raises(ValueError, match="pseudo_info"):
        PseudoMetadata.from_dict(payload)


def test_pseudo_metadata_from_dict_rejects_non_number_z_valence() -> None:
    """A non-numeric z_valence raises ValueError rather than being stored."""
    payload = _si_pseudo().to_dict()
    payload["z_valence"] = "four"
    with pytest.raises(ValueError, match="z_valence"):
        PseudoMetadata.from_dict(payload)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_pseudo_metadata_from_dict_rejects_non_finite_z_valence(bad: float) -> None:
    """A non-finite z_valence raises ValueError at deserialization."""
    payload = _si_pseudo().to_dict()
    payload["z_valence"] = bad
    with pytest.raises(ValueError, match="finite"):
        PseudoMetadata.from_dict(payload)


def test_core_job_request_from_dict_rejects_non_string_output_dir() -> None:
    """A non-string output_dir raises ValueError rather than being stored as-is."""
    with pytest.raises(ValueError, match="output_dir"):
        CoreJobRequest.from_dict({"structure": "Si.cif", "output_dir": 3})


def test_core_job_request_from_dict_rejects_non_list_pseudo_metadata() -> None:
    """A non-list pseudo_metadata raises ValueError, not a TypeError from tuple()."""
    with pytest.raises(ValueError, match="pseudo_metadata"):
        CoreJobRequest.from_dict({"structure": "Si.cif", "pseudo_metadata": None})


@pytest.mark.parametrize("bad", ["recommend ", ["recommend"], 1, None])
def test_core_job_request_from_dict_rejects_malformed_mode(bad: object) -> None:
    """A malformed mode raises ValueError, never an unhashable-type TypeError."""
    with pytest.raises(ValueError, match="mode"):
        CoreJobRequest.from_dict({"structure": "Si.cif", "mode": bad})


def test_core_import_does_not_require_or_import_http_dependencies() -> None:
    """Importing the core package does not import HTTP dependencies or the server."""
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import goldilocks_core; "
            "print('fastapi' in sys.modules, 'uvicorn' in sys.modules, "
            "'starlette' in sys.modules, 'goldilocks_core.server' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    imported = result.stdout.strip()
    assert imported == "False False False False", imported
