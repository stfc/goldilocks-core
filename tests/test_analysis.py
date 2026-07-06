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


def test_analyze_structure_reports_3d_bulk_without_vacuum() -> None:
    """Classify a fully bonded bulk crystal as 3D with no vacuum."""
    structure = Structure(
        lattice=Lattice.cubic(3.61),
        species=["Cu", "Cu", "Cu", "Cu"],
        coords=[[0, 0, 0], [0.5, 0.5, 0], [0.5, 0, 0.5], [0, 0.5, 0.5]],
    )

    analysis = analyze_structure(structure)

    assert analysis.dimensionality == "3d"
    assert analysis.has_vacuum is False


def test_analyze_structure_reports_2d_slab_with_vacuum() -> None:
    """Classify a graphene sheet with vacuum as 2D with vacuum."""
    structure = Structure(
        lattice=Lattice.from_parameters(2.46, 2.46, 15.0, 90, 90, 120),
        species=["C", "C"],
        coords=[[0, 0, 0.5], [1 / 3, 2 / 3, 0.5]],
    )

    analysis = analyze_structure(structure)

    assert analysis.dimensionality == "2d"
    assert analysis.has_vacuum is True


def test_analyze_structure_reports_molecule_with_vacuum() -> None:
    """Classify an isolated molecule in a large box as molecular with vacuum."""
    structure = Structure(
        lattice=Lattice.cubic(15.0),
        species=["H", "H"],
        coords=[[0.45, 0.5, 0.5], [0.55, 0.5, 0.5]],
    )

    analysis = analyze_structure(structure)

    assert analysis.dimensionality == "molecule"
    assert analysis.has_vacuum is True
