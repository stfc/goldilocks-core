import numpy as np
import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.advice import advise_parameters
from goldilocks_core.analysis import analyze_structure
from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    KmeshHints,
    ParameterAdvice,
    PseudoMetadata,
)
from goldilocks_core.kmesh import resolve_kpoints
from goldilocks_core.selection import (
    _metadata_matches_mode,
    _rank_pseudo_candidate,
    select_parameters,
)


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
    functional: str = "PBEsol",
    cutoffs: dict | None = None,
    library: str | None = "SSSP",
    is_sssp: bool = True,
    pseudo_type: str | None = "NC",
    relativistic: str | None = "scalar",
) -> PseudoMetadata:
    """Build synthetic pseudopotential metadata for selection tests."""
    return PseudoMetadata(
        filepath=f"/pseudo/{filename}",
        filename=filename,
        header_format="attr",
        library=library,
        source_set=source_set,
        element="Si",
        pseudo_type=pseudo_type,
        functional=functional,
        relativistic=relativistic,
        is_sssp=is_sssp,
        sssp_recommended_cutoff=(
            {"ecutwfc_ry": "30", "ecutrho_ry": 120} if cutoffs is None else cutoffs
        ),
    )


def select_from_advice(
    structure: Structure,
    advice: ParameterAdvice,
    *,
    metadata_list: list[PseudoMetadata] | None = None,
):
    """Run Select on advice without k-points (Select no longer takes them)."""
    return select_parameters(
        structure,
        advice,
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
        metadata_list=[make_metadata()],
    )

    pseudo = selection.pseudopotentials[0]
    assert pseudo.element == "Si"
    assert pseudo.filename == "Si.UPF"
    assert pseudo.filepath == "/pseudo/Si.UPF"
    assert pseudo.ecutwfc_ry == 30.0
    assert pseudo.ecutrho_ry == 120.0
    assert pseudo.provenance.source == "lookup"
    assert (
        pseudo.provenance.reason
        == "Select the highest-ranked deterministic pseudo matching advice."
    )
    assert pseudo.provenance.data_source == "SSSP"
    assert pseudo.provenance.warnings == pseudo.warnings
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
    assert pseudo.warnings == (
        f"Selected pseudopotential for Si has invalid cutoff metadata "
        f"(ecutwfc_ry={invalid_value!r}); replace it with finite positive values "
        "before generation.",
    )
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
    assert warnings == (
        "Selected pseudopotential for Si is missing cutoff metadata "
        "for ecutrho_ry; provide finite positive values before generation.",
    )


def test_select_parameters_keeps_explicit_grid_hint() -> None:
    """Use a Kmesh-stage explicit grid without recalculating spacing."""
    structure = make_structure()
    hints = KmeshHints(k_grid=(2, 2, 1))

    k_points = resolve_kpoints(structure, hints, lambda s: None)

    assert k_points.grid == (2, 2, 1)
    assert k_points.provenance.source == "user_hint"


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
        metadata_list=[make_metadata(functional="PBE")],
    )

    pseudo = selection.pseudopotentials[0]
    assert pseudo.element == "Si"
    assert pseudo.filename is None
    assert pseudo.filepath is None
    assert pseudo.ecutwfc_ry is None
    assert pseudo.ecutrho_ry is None
    assert pseudo.provenance.source == "fallback"
    assert pseudo.provenance.reason == "No matching pseudopotential was available."
    assert pseudo.provenance.warnings == pseudo.warnings
    assert pseudo.warnings == (
        "No pseudopotential metadata matched Si / PBEsol / scalar.",
    )


def test_select_parameters_filters_by_pseudo_type() -> None:
    """Exclude candidates whose pseudo type does not match advice."""
    structure = make_structure()
    advice = advise_parameters(
        analyze_structure(structure),
        hints=CalculationHints(pseudo_type="NC"),
    )

    selection = select_from_advice(
        structure,
        advice,
        metadata_list=[make_metadata(pseudo_type="PAW")],
    )

    pseudo = selection.pseudopotentials[0]
    assert pseudo.filename is None
    assert pseudo.provenance.source == "fallback"


def test_select_parameters_filters_by_relativistic_mode() -> None:
    """Exclude candidates whose relativistic mode does not match advice."""
    structure = make_structure()
    advice = advise_parameters(analyze_structure(structure))

    selection = select_from_advice(
        structure,
        advice,
        metadata_list=[make_metadata(relativistic="full")],
    )

    pseudo = selection.pseudopotentials[0]
    assert pseudo.filename is None
    assert pseudo.provenance.source == "fallback"


def test_select_parameters_warns_when_selected_pseudo_mismatches_mode() -> None:
    """Report an exact warning when the selected pseudo misses the mode."""
    structure = make_structure()
    advice = advise_parameters(
        analyze_structure(structure),
        hints=CalculationHints(pseudo_type="NC", pseudo_mode="precision"),
    )

    selection = select_from_advice(
        structure,
        advice,
        metadata_list=[make_metadata(source_set="SSSP_efficiency")],
    )

    pseudo = selection.pseudopotentials[0]
    assert pseudo.filename == "Si.UPF"
    assert pseudo.warnings == (
        "Selected pseudopotential for Si does not explicitly match "
        "pseudo mode 'precision'.",
    )
    assert pseudo.provenance.warnings == pseudo.warnings


def test_select_parameters_warns_exact_missing_cutoff_text() -> None:
    """Report both missing cutoffs with exact joined text."""
    structure = make_structure()
    advice = advise_parameters(analyze_structure(structure))

    selection = select_from_advice(
        structure,
        advice,
        metadata_list=[make_metadata(cutoffs={})],
    )

    pseudo = selection.pseudopotentials[0]
    assert pseudo.ecutwfc_ry is None
    assert pseudo.ecutrho_ry is None
    assert pseudo.warnings == (
        "Selected pseudopotential for Si is missing cutoff metadata "
        "for ecutwfc_ry, ecutrho_ry; provide finite positive values before "
        "generation.",
    )
    assert pseudo.provenance.warnings == pseudo.warnings


def test_select_parameters_warns_exact_invalid_cutoff_text() -> None:
    """Report both invalid cutoffs with exact joined text."""
    structure = make_structure()
    advice = advise_parameters(analyze_structure(structure))

    selection = select_from_advice(
        structure,
        advice,
        metadata_list=[
            make_metadata(cutoffs={"ecutwfc_ry": "bad", "ecutrho_ry": "bad2"})
        ],
    )

    pseudo = selection.pseudopotentials[0]
    assert pseudo.ecutwfc_ry is None
    assert pseudo.ecutrho_ry is None
    assert pseudo.warnings == (
        "Selected pseudopotential for Si has invalid cutoff metadata "
        "(ecutwfc_ry='bad', ecutrho_ry='bad2'); replace it with finite positive "
        "values before generation.",
    )
    assert pseudo.provenance.warnings == pseudo.warnings


def test_rank_pseudo_candidate_exact_key_mode_matches() -> None:
    """Ranking key is an explicit deterministic tuple for a matching candidate."""
    metadata = make_metadata(
        filename="Si.UPF",
        source_set="SSSP_efficiency",
        cutoffs={"ecutwfc_ry": 30, "ecutrho_ry": 120},
    )
    assert _rank_pseudo_candidate(metadata, "efficiency") == (
        0,
        0,
        0,
        "SSSP_efficiency",
        "Si.UPF",
    )


def test_rank_pseudo_candidate_exact_key_mode_mismatch_and_incomplete() -> None:
    """Ranking key marks mode mismatch and incomplete cutoffs distinctly."""
    metadata = make_metadata(
        filename="Si.UPF",
        source_set="SSSP_efficiency",
        cutoffs={"ecutwfc_ry": 30},
    )
    assert _rank_pseudo_candidate(metadata, "precision") == (
        1,
        1,
        0,
        "SSSP_efficiency",
        "Si.UPF",
    )


def test_rank_pseudo_candidate_exact_key_non_sssp() -> None:
    """Ranking key marks non-SSSP candidates with a distinct sssp rank."""
    metadata = make_metadata(
        filename="Si.UPF",
        source_set="SSSP_efficiency",
        is_sssp=False,
        cutoffs={"ecutwfc_ry": 30, "ecutrho_ry": 120},
    )
    assert _rank_pseudo_candidate(metadata, "efficiency") == (
        0,
        0,
        1,
        "SSSP_efficiency",
        "Si.UPF",
    )


def test_rank_pseudo_candidate_exact_key_source_fallback() -> None:
    """Ranking key falls back to the library when source_set is absent."""
    metadata = make_metadata(
        filename="Si.UPF",
        source_set=None,
        library="SSSP",
        cutoffs={"ecutwfc_ry": 30, "ecutrho_ry": 120},
    )
    assert _rank_pseudo_candidate(metadata, "efficiency") == (
        0,
        0,
        0,
        "SSSP",
        "Si.UPF",
    )


def test_rank_pseudo_candidate_exact_key_no_source() -> None:
    """Ranking key uses an empty source when neither source is present."""
    metadata = make_metadata(
        filename="Si.UPF",
        source_set=None,
        library=None,
        cutoffs={"ecutwfc_ry": 30, "ecutrho_ry": 120},
    )
    assert _rank_pseudo_candidate(metadata, "efficiency") == (
        0,
        0,
        0,
        "",
        "Si.UPF",
    )


def test_metadata_matches_mode_crosses_field_boundary() -> None:
    """A multi-word mode matches across the joined field boundary."""
    metadata = make_metadata(library="SSSP", source_set="efficiency")
    assert _metadata_matches_mode(metadata, "SSSP efficiency") is True


def test_metadata_matches_mode_precision_source_returns_false_for_efficiency() -> None:
    """A precision source set does not match an efficiency mode."""
    metadata = make_metadata(source_set="SSSP_precision")
    assert _metadata_matches_mode(metadata, "efficiency") is False


def test_metadata_matches_mode_sssp_flag_wins_without_mode_words() -> None:
    """The SSSP flag alone matches when no mode word is present."""
    metadata = make_metadata(library="Other", source_set=None, is_sssp=True)
    assert _metadata_matches_mode(metadata, "efficiency") is True


@pytest.mark.parametrize("library", ["SSSP", "sssp"])
def test_metadata_matches_mode_library_sssp(library: str) -> None:
    """An SSSP library matches even when the SSSP flag is unset."""
    metadata = make_metadata(library=library, source_set=None, is_sssp=False)
    assert _metadata_matches_mode(metadata, "efficiency") is True
