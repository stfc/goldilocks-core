from __future__ import annotations

from pymatgen.core import Lattice, Structure

from goldilocks_core.analysis import analyze_structure, heuristic_metallicity


def test_default_heuristic_marks_all_metal_as_likely_metal() -> None:
    """Default ``heuristic_metallicity`` flags an all-metal structure as likely."""
    structure = Structure(
        lattice=Lattice.cubic(2.9),
        species=["Fe"],
        coords=[[0.0, 0.0, 0.0]],
    )

    analysis = analyze_structure(structure)

    assert analysis.electronic_character == "likely_metal"
    assert analysis.electronic_character_source == "heuristic"
    assert analysis.electronic_character_confidence is None
    assert any(
        "treat metallicity as likely" in warning
        for warning in analysis.analysis_warnings
    )


def test_default_heuristic_marks_non_metal_as_unknown() -> None:
    """Default ``heuristic_metallicity`` reports unknown for a non-metal composition."""
    structure = Structure(
        lattice=Lattice.cubic(4.0),
        species=["Fe", "I"],
        coords=[[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
    )

    analysis = analyze_structure(structure)

    assert analysis.electronic_character == "unknown"
    assert analysis.electronic_character_source == "heuristic"
    assert analysis.electronic_character_confidence is None
    assert any("verify smearing" in warning for warning in analysis.analysis_warnings)


def test_analyze_structure_uses_runtime_metallicity_classifier() -> None:
    """Record the runtime classifier value, provenance, and confidence."""
    structure = Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])

    analysis = analyze_structure(
        structure,
        metallicity_classifier=lambda actual: ("insulator", "model", 0.87),
    )

    assert analysis.electronic_character == "insulator"
    assert analysis.electronic_character_source == "model"
    assert analysis.electronic_character_confidence == 0.87
    assert not any(
        "verify smearing" in warning for warning in analysis.analysis_warnings
    )


def test_heuristic_metallicity_classifies_all_metal_and_non_metal() -> None:
    """The default heuristic returns likely_metal for metals, unknown otherwise."""
    metal = Structure(Lattice.cubic(2.9), ["Fe"], [[0.0, 0.0, 0.0]])
    non_metal = Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])

    assert heuristic_metallicity(metal) == "likely_metal"
    assert heuristic_metallicity(non_metal) == "unknown"
