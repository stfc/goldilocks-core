from pymatgen.core import Lattice, Structure

from goldilocks_core.analysis import analyze_structure


def test_analyze_structure_reports_composition_and_element_facts() -> None:
    """Report structure facts without recommending parameters."""
    structure = Structure(
        lattice=Lattice.cubic(4.0),
        species=["Fe", "I"],
        coords=[[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
    )

    analysis = analyze_structure(structure)

    assert analysis.reduced_formula == "FeI"
    assert analysis.site_count == 2
    assert analysis.elements == ("Fe", "I")
    assert analysis.contains_transition_metals is True
    assert analysis.contains_heavy_elements is True
    assert analysis.magnetic_elements == ("Fe",)
    assert analysis.heavy_elements == ("I",)
    assert analysis.space_group_number is not None
    assert analysis.crystal_system is not None
    assert analysis.electronic_character == "unknown"
    assert analysis.analysis_warnings


def test_analyze_structure_reports_partial_occupancy_warnings() -> None:
    """Surface disordered sites as analysis warnings."""
    structure = Structure(
        lattice=Lattice.cubic(4.0),
        species=[{"Fe": 0.5, "Mn": 0.5}],
        coords=[[0.0, 0.0, 0.0]],
    )

    analysis = analyze_structure(structure)

    assert analysis.disorder_warnings
    assert analysis.disordered_site_count == 1
    assert "partial occupancies" in analysis.disorder_warnings[0]


def test_analyze_structure_marks_all_metal_compositions_as_likely_metal() -> None:
    """Classify all-metal compositions conservatively as likely metallic."""
    structure = Structure(
        lattice=Lattice.cubic(2.9),
        species=["Fe"],
        coords=[[0.0, 0.0, 0.0]],
    )

    analysis = analyze_structure(structure)

    assert analysis.electronic_character == "likely_metal"
    assert "likely" in analysis.analysis_warnings[0]
