import numpy as np
import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.advice import advise_parameters
from goldilocks_core.analysis import analyze_structure
from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    ParameterAdvice,
)
from goldilocks_core.kmesh import resolve_kpoints_from_advice
from goldilocks_core.pseudo.pp_metadata import PseudoMetadata
from goldilocks_core.selection import select_parameters


def make_structure() -> Structure:
    """Build a simple cubic silicon structure."""
    return Structure(
        lattice=Lattice.cubic(4.0),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )


def make_metadata(
    *,
    filename: str = "Si.UPF",
    source_set: str | None = None,
    functional: str = "PBE",
    cutoffs: dict | None = None,
) -> PseudoMetadata:
    """Build synthetic pseudopotential metadata for selection tests."""
    return PseudoMetadata(
        filepath=f"/pseudo/{filename}",
        filename=filename,
        header_format="attr",
        library="SSSP",
        source_set=source_set,
        element="Si",
        pseudo_type="NC",
        functional=functional,
        relativistic="scalar",
        is_sssp=True,
        sssp_recommended_cutoff=(
            {"ecutwfc_ry": "30", "ecutrho_ry": 120} if cutoffs is None else cutoffs
        ),
    )


def select_from_advice(
    structure: Structure,
    advice: ParameterAdvice,
    *,
    hints: CalculationHints | None = None,
    metadata_list: list[PseudoMetadata] | None = None,
):
    """Resolve k-points through Kmesh before running Select."""
    hints = hints or CalculationHints()
    return select_parameters(
        structure,
        advice,
        resolve_kpoints_from_advice(structure, hints, advice.k_points),
        metadata_list=metadata_list,
    )


def test_select_parameters_resolves_pseudos_with_kmesh_selection() -> None:
    """Select concrete pseudo and cutoffs around a Kmesh-stage grid."""
    structure = make_structure()
    hints = CalculationHints(k_spacing=0.25, pseudo_type="NC")
    advice = advise_parameters(analyze_structure(structure), hints=hints)

    selection = select_from_advice(
        structure,
        advice,
        hints=hints,
        metadata_list=[make_metadata()],
    )

    assert selection.k_points.grid == (7, 7, 7)
    assert selection.k_points.shift == (0, 0, 0)
    assert selection.pseudopotentials[0].filename == "Si.UPF"
    assert selection.pseudopotentials[0].ecutwfc_ry == 30.0
    assert selection.pseudopotentials[0].ecutrho_ry == 120.0
    assert selection.warnings == ()


def test_select_parameters_matches_canonical_functional_labels() -> None:
    """Match Python PBEsol intent to equivalent metadata labels."""
    structure = make_structure()
    advice = advise_parameters(
        analyze_structure(structure),
        intent=CalculationIntent(functional="PBE_SOL"),
        hints=CalculationHints(pseudo_type="NC"),
    )

    selection = select_from_advice(
        structure,
        advice,
        metadata_list=[make_metadata(functional="PBESOL")],
    )

    assert advice.pseudopotentials.functional == "PBEsol"
    assert selection.pseudopotentials[0].filename == "Si.UPF"


def test_select_parameters_prefers_matching_pseudo_mode_and_cutoffs() -> None:
    """Rank pseudo candidates by requested mode before filename order."""
    structure = make_structure()
    advice = advise_parameters(
        analyze_structure(structure),
        hints=CalculationHints(pseudo_type="NC", pseudo_mode="precision"),
    )
    efficiency = make_metadata(
        filename="A-efficiency.UPF",
        source_set="SSSP_efficiency",
        cutoffs={"ecutwfc_ry": 30, "ecutrho_ry": 120},
    )
    precision = make_metadata(
        filename="Z-precision.UPF",
        source_set="SSSP_precision",
        cutoffs={"ecutwfc_ry": 60, "ecutrho_ry": 240},
    )

    selection = select_from_advice(
        structure,
        advice,
        metadata_list=[efficiency, precision],
    )

    assert selection.pseudopotentials[0].filename == "Z-precision.UPF"
    assert selection.pseudopotentials[0].ecutwfc_ry == 60.0
    assert selection.pseudopotentials[0].provenance.source == "lookup"
    assert "highest-ranked" in selection.pseudopotentials[0].provenance.reason


def test_select_parameters_prefers_complete_cutoff_metadata() -> None:
    """Rank candidates with complete cutoff metadata before incomplete ones."""
    structure = make_structure()
    advice = advise_parameters(
        analyze_structure(structure),
        hints=CalculationHints(pseudo_type="NC"),
    )
    incomplete = make_metadata(
        filename="A-incomplete.UPF",
        source_set="SSSP_efficiency",
        cutoffs={"ecutwfc_ry": 30},
    )
    complete = make_metadata(
        filename="Z-complete.UPF",
        source_set="SSSP_efficiency",
        cutoffs={"ecutwfc_ry": 35, "ecutrho_ry": 140},
    )

    selection = select_from_advice(
        structure,
        advice,
        metadata_list=[incomplete, complete],
    )

    assert selection.pseudopotentials[0].filename == "Z-complete.UPF"
    assert selection.warnings == ()


@pytest.mark.parametrize(
    "invalid_value",
    [
        "not-a-number",
        float("nan"),
        float("inf"),
        -float("inf"),
        0,
        -1,
        True,
        False,
        np.bool_(True),
        np.bool_(False),
    ],
)
def test_select_parameters_ranks_invalid_cutoffs_as_incomplete(
    invalid_value: object,
) -> None:
    """Prefer complete metadata over every class of invalid cutoff."""
    structure = make_structure()
    advice = advise_parameters(
        analyze_structure(structure),
        hints=CalculationHints(pseudo_type="NC"),
    )
    invalid = make_metadata(
        filename="A-invalid.UPF",
        source_set="SSSP_efficiency",
        cutoffs={"ecutwfc_ry": invalid_value, "ecutrho_ry": 120},
    )
    complete = make_metadata(
        filename="Z-complete.UPF",
        source_set="SSSP_efficiency",
        cutoffs={"ecutwfc_ry": 35, "ecutrho_ry": 140},
    )

    selection = select_from_advice(
        structure,
        advice,
        metadata_list=[invalid, complete],
    )

    assert selection.pseudopotentials[0].filename == "Z-complete.UPF"


@pytest.mark.parametrize(
    ("ecutwfc", "ecutrho"),
    [(np.int64(30), np.float32(120)), (np.float64(35), np.int32(140))],
)
def test_select_parameters_accepts_finite_numpy_numeric_cutoffs(
    ecutwfc: object,
    ecutrho: object,
) -> None:
    """Accept finite NumPy numeric scalars while rejecting NumPy booleans."""
    structure = make_structure()
    advice = advise_parameters(analyze_structure(structure))

    selection = select_from_advice(
        structure,
        advice,
        metadata_list=[
            make_metadata(cutoffs={"ecutwfc_ry": ecutwfc, "ecutrho_ry": ecutrho})
        ],
    )

    pseudo = selection.pseudopotentials[0]
    assert pseudo.ecutwfc_ry == float(ecutwfc)
    assert pseudo.ecutrho_ry == float(ecutrho)
    assert not any("cutoff metadata" in warning for warning in pseudo.warnings)


def test_select_parameters_ranks_missing_cutoffs_as_incomplete() -> None:
    """Prefer complete metadata over lexically earlier missing metadata."""
    structure = make_structure()
    advice = advise_parameters(
        analyze_structure(structure),
        hints=CalculationHints(pseudo_type="NC"),
    )
    missing = make_metadata(
        filename="A-missing.UPF",
        source_set="SSSP_efficiency",
        cutoffs={"ecutwfc_ry": 30},
    )
    complete = make_metadata(
        filename="Z-complete.UPF",
        source_set="SSSP_efficiency",
        cutoffs={"ecutwfc_ry": 35, "ecutrho_ry": 140},
    )

    selection = select_from_advice(
        structure,
        advice,
        metadata_list=[missing, complete],
    )

    assert selection.pseudopotentials[0].filename == "Z-complete.UPF"


@pytest.mark.parametrize(
    "invalid_value",
    [
        "not-a-number",
        float("nan"),
        float("inf"),
        -float("inf"),
        0,
        -1,
        True,
        False,
        np.bool_(True),
        np.bool_(False),
    ],
)
def test_select_parameters_warns_about_present_invalid_cutoffs(
    invalid_value: object,
) -> None:
    """Sanitize invalid metadata and explain that it must be replaced."""
    structure = make_structure()
    advice = advise_parameters(analyze_structure(structure))

    selection = select_from_advice(
        structure,
        advice,
        metadata_list=[
            make_metadata(cutoffs={"ecutwfc_ry": invalid_value, "ecutrho_ry": 120})
        ],
    )

    pseudo = selection.pseudopotentials[0]
    assert pseudo.ecutwfc_ry is None
    assert pseudo.ecutrho_ry == 120.0
    assert any("invalid cutoff metadata" in warning for warning in pseudo.warnings)
    assert any("finite positive" in warning for warning in pseudo.warnings)
    assert pseudo.provenance.warnings == pseudo.warnings


def test_select_parameters_distinguishes_missing_cutoff_warning() -> None:
    """Report absent cutoff metadata separately from malformed values."""
    structure = make_structure()
    advice = advise_parameters(analyze_structure(structure))

    selection = select_from_advice(
        structure,
        advice,
        metadata_list=[make_metadata(cutoffs={"ecutwfc_ry": 30})],
    )

    warnings = selection.pseudopotentials[0].warnings
    assert any("missing cutoff metadata" in warning for warning in warnings)
    assert not any("invalid cutoff metadata" in warning for warning in warnings)


def test_select_parameters_keeps_explicit_grid_hint() -> None:
    """Use a Kmesh-stage explicit grid without recalculating spacing."""
    structure = make_structure()
    hints = CalculationHints(k_grid=(2, 2, 1))
    advice = advise_parameters(analyze_structure(structure), hints=hints)

    selection = select_from_advice(structure, advice, hints=hints)

    assert selection.k_points.grid == (2, 2, 1)
    assert selection.k_points.provenance.source == "user_hint"


def test_select_parameters_warns_when_pseudo_is_missing() -> None:
    """Surface missing pseudopotentials as structured selection warnings."""
    structure = make_structure()
    advice = advise_parameters(
        analyze_structure(structure),
        intent=CalculationIntent(functional="PBEsol"),
    )

    selection = select_from_advice(
        structure,
        advice,
        metadata_list=[make_metadata()],
    )

    assert selection.pseudopotentials[0].filename is None
    assert selection.pseudopotentials[0].provenance.source == "fallback"
    assert "No pseudopotential metadata matched" in selection.warnings[0]
