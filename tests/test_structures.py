from pathlib import Path

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.io.structures import analyze_structure, load_structure


def make_si_structure() -> Structure:
    """Build a minimal silicon structure for tests."""
    return Structure(
        lattice=Lattice.cubic(3.5),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )


def test_load_structure_returns_structure_input() -> None:
    """Return the input unchanged when it is already a Structure."""
    structure = make_si_structure()

    loaded = load_structure(structure)

    assert loaded is structure


def test_load_structure_loads_structure_file(tmp_path: Path) -> None:
    """Load a structure from a portable temporary CIF file."""
    structure = make_si_structure()
    structure_path = tmp_path / "Si.cif"
    structure.to(filename=structure_path)

    loaded = load_structure(structure_path)

    assert loaded.composition.reduced_formula == "Si"
    assert len(loaded) == 1


def test_load_structure_raises_for_missing_file() -> None:
    """Raise FileNotFoundError when the structure file does not exist."""
    with pytest.raises(FileNotFoundError):
        load_structure("missing_structure.cif")


def test_load_structure_raises_for_unsupported_xyz(tmp_path: Path) -> None:
    """Raise ValueError for unsupported XYZ structure files."""
    xyz_file = tmp_path / "test.xyz"
    xyz_file.write_text("1\ncomment\nH 0.0 0.0 0.0\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported structure file format"):
        load_structure(xyz_file)


def test_analyze_structure_flags_transition_metal() -> None:
    """Report transition-metal content in structure analysis."""
    structure = Structure(
        lattice=Lattice.cubic(3.5),
        species=["Fe"],
        coords=[[0.0, 0.0, 0.0]],
    )

    analysis = analyze_structure(structure)

    assert analysis.contains_transition_metals is True
    assert analysis.contains_lanthanides is False
    assert analysis.contains_heavy_elements is False


def test_analyze_structure_flags_period_five_element_as_heavy() -> None:
    """Report period-five elements as heavy for SOC consideration."""
    structure = Structure(
        lattice=Lattice.cubic(4.0),
        species=["I"],
        coords=[[0.0, 0.0, 0.0]],
    )

    analysis = analyze_structure(structure)

    assert analysis.contains_transition_metals is False
    assert analysis.contains_lanthanides is False
    assert analysis.contains_heavy_elements is True


def test_analyze_structure_flags_lanthanide_as_heavy_element() -> None:
    """Report lanthanide and heavy-element content in analysis."""
    structure = Structure(
        lattice=Lattice.cubic(4.0),
        species=["Ce"],
        coords=[[0.0, 0.0, 0.0]],
    )

    analysis = analyze_structure(structure)

    assert analysis.contains_transition_metals is False
    assert analysis.contains_lanthanides is True
    assert analysis.contains_heavy_elements is True
