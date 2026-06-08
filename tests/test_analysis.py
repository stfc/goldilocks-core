from pymatgen.core import Lattice, Structure

from goldilocks_core.analysis import analyse_structure


def test_analyse_structure_reports_composition_and_element_facts() -> None:
    """Report structure facts without recommending parameters."""
    structure = Structure(
        lattice=Lattice.cubic(4.0),
        species=["Fe", "I"],
        coords=[[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
    )

    analysis = analyse_structure(structure)

    assert analysis.reduced_formula == "FeI"
    assert analysis.site_count == 2
    assert analysis.elements == ("Fe", "I")
    assert analysis.contains_transition_metals is True
    assert analysis.contains_heavy_elements is True
    assert analysis.magnetic_elements == ("Fe",)
    assert analysis.heavy_elements == ("I",)


def test_analyse_structure_reports_partial_occupancy_warnings() -> None:
    """Surface disordered sites as analysis warnings."""
    structure = Structure(
        lattice=Lattice.cubic(4.0),
        species=[{"Fe": 0.5, "Mn": 0.5}],
        coords=[[0.0, 0.0, 0.0]],
    )

    analysis = analyse_structure(structure)

    assert analysis.disorder_warnings
    assert "partial occupancies" in analysis.disorder_warnings[0]
