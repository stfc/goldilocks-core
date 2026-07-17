import pytest
from pymatgen.core import Lattice, Structure

import goldilocks_core.analysis as analysis_module
from goldilocks_core.advice import advise_parameters
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
    """Report disorder and skip unsupported CrystalNN dimensionality analysis."""
    structure = Structure(
        lattice=Lattice.cubic(4.0),
        species=[{"Fe": 0.5, "Mn": 0.5}],
        coords=[[0.0, 0.0, 0.0]],
    )

    analysis = analyze_structure(structure)

    assert analysis.disorder_warnings
    assert analysis.disordered_site_count == 1
    assert "partial occupancies" in analysis.disorder_warnings[0]
    assert analysis.dimensionality == "unknown"
    assert analysis.has_vacuum is False


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


def test_analyze_structure_falls_back_for_crystal_nn_value_error(
    monkeypatch,
) -> None:
    """Handle CrystalNN's documented operational ValueError conservatively."""

    def fail_crystal_nn():
        raise ValueError("No Voronoi neighbors found for site")

    monkeypatch.setattr(analysis_module, "CrystalNN", fail_crystal_nn)
    structure = Structure(
        lattice=Lattice.cubic(4.0),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )

    analysis = analyze_structure(structure)
    advice = advise_parameters(analysis)

    assert analysis.dimensionality == "unknown"
    assert analysis.has_vacuum is False
    assert any(
        "CalculationHints(use_vdw=True)" in warning
        for warning in analysis.analysis_warnings
    )
    assert advice.vdw.use_vdw is False


def test_analyze_structure_falls_back_for_larsen_runtime_error(monkeypatch) -> None:
    """Handle runtime failures from the CrystalNN/Larsen operations."""

    def fail_larsen(*_args):
        raise RuntimeError("pathological graph")

    monkeypatch.setattr(analysis_module, "get_dimensionality_larsen", fail_larsen)
    structure = Structure(
        lattice=Lattice.cubic(4.0),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )

    analysis = analyze_structure(structure)

    assert analysis.dimensionality == "unknown"
    assert analysis.has_vacuum is False


def test_analyze_structure_propagates_unexpected_dimensionality_assertion(
    monkeypatch,
) -> None:
    """Do not hide unexpected programming failures in dimensionality analysis."""

    def fail_larsen(*_args):
        raise AssertionError("invariant violation")

    monkeypatch.setattr(analysis_module, "get_dimensionality_larsen", fail_larsen)
    structure = Structure(
        lattice=Lattice.cubic(4.0),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )

    with pytest.raises(AssertionError, match="invariant violation"):
        analyze_structure(structure)


def test_analyze_structure_reports_3d_bulk_without_vacuum() -> None:
    """Classify a fully bonded bulk crystal as 3D without the heuristic flag."""
    structure = Structure(
        lattice=Lattice.cubic(3.61),
        species=["Cu", "Cu", "Cu", "Cu"],
        coords=[[0, 0, 0], [0.5, 0.5, 0], [0.5, 0, 0.5], [0, 0.5, 0.5]],
    )

    analysis = analyze_structure(structure)

    assert analysis.dimensionality == "3d"
    assert analysis.has_vacuum is False


def test_analyze_structure_reports_2d_slab_with_vacuum() -> None:
    """Set the low-dimensional/vacuum heuristic for a graphene sheet."""
    structure = Structure(
        lattice=Lattice.from_parameters(2.46, 2.46, 15.0, 90, 90, 120),
        species=["C", "C"],
        coords=[[0, 0, 0.5], [1 / 3, 2 / 3, 0.5]],
    )

    analysis = analyze_structure(structure)

    assert analysis.dimensionality == "2d"
    assert analysis.has_vacuum is True


def test_analyze_structure_reports_molecule_with_vacuum() -> None:
    """Set the low-dimensional/vacuum heuristic for an isolated molecule."""
    structure = Structure(
        lattice=Lattice.cubic(15.0),
        species=["H", "H"],
        coords=[[0.45, 0.5, 0.5], [0.55, 0.5, 0.5]],
    )

    analysis = analyze_structure(structure)

    assert analysis.dimensionality == "molecule"
    assert analysis.has_vacuum is True
