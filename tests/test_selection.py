from pymatgen.core import Lattice, Structure

from goldilocks_core.advice import advise_parameters
from goldilocks_core.analysis import analyze_structure
from goldilocks_core.contracts import CalculationHints, CalculationIntent
from goldilocks_core.pseudo.pp_metadata import PseudoMetadata
from goldilocks_core.selection import select_parameters


def make_structure() -> Structure:
    """Build a simple cubic silicon structure."""
    return Structure(
        lattice=Lattice.cubic(4.0),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )


def make_metadata() -> PseudoMetadata:
    """Build synthetic pseudopotential metadata for selection tests."""
    return PseudoMetadata(
        filepath="/pseudo/Si.UPF",
        filename="Si.UPF",
        header_format="attr",
        library="SSSP",
        element="Si",
        pseudo_type="NC",
        functional="PBE",
        relativistic="scalar",
        sssp_recommended_cutoff={"ecutwfc_ry": "30", "ecutrho_ry": 120},
    )


def test_select_parameters_resolves_k_spacing_and_pseudos() -> None:
    """Select concrete grid, pseudo, and cutoffs from staged advice."""
    structure = make_structure()
    advice = advise_parameters(
        analyze_structure(structure),
        hints=CalculationHints(k_spacing=0.25, pseudo_type="NC"),
    )

    selection = select_parameters(structure, advice, metadata_list=[make_metadata()])

    assert selection.k_points.grid == (7, 7, 7)
    assert selection.k_points.shift == (0, 0, 0)
    assert selection.pseudopotentials[0].filename == "Si.UPF"
    assert selection.pseudopotentials[0].ecutwfc_ry == 30.0
    assert selection.pseudopotentials[0].ecutrho_ry == 120.0
    assert selection.warnings == ()


def test_select_parameters_keeps_explicit_grid_hint() -> None:
    """Use an explicit grid hint without recalculating spacing."""
    structure = make_structure()
    advice = advise_parameters(
        analyze_structure(structure),
        hints=CalculationHints(k_grid=(2, 2, 1)),
    )

    selection = select_parameters(structure, advice)

    assert selection.k_points.grid == (2, 2, 1)
    assert selection.k_points.provenance.source == "user_hint"


def test_select_parameters_warns_when_pseudo_is_missing() -> None:
    """Surface missing pseudopotentials as structured selection warnings."""
    structure = make_structure()
    advice = advise_parameters(
        analyze_structure(structure),
        intent=CalculationIntent(functional="PBEsol"),
    )

    selection = select_parameters(structure, advice, metadata_list=[make_metadata()])

    assert selection.pseudopotentials[0].filename is None
    assert selection.pseudopotentials[0].provenance.source == "fallback"
    assert "No pseudopotential metadata matched" in selection.warnings[0]
