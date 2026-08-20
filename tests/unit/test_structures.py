from pathlib import Path

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.io.structures import load_structure


def make_si_structure() -> Structure:
    return Structure(
        lattice=Lattice.cubic(3.5),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )


def test_load_structure_returns_structure_input() -> None:
    structure = make_si_structure()

    loaded = load_structure(structure)

    assert loaded is structure


def test_load_structure_loads_structure_file(tmp_path: Path) -> None:
    structure = make_si_structure()
    structure_path = tmp_path / "Si.cif"
    structure.to(filename=structure_path)

    loaded = load_structure(structure_path)

    assert loaded.composition.reduced_formula == "Si"
    assert len(loaded) == 1


def test_load_structure_raises_for_missing_file() -> None:
    with pytest.raises(FileNotFoundError):
        load_structure("missing_structure.cif")


def test_load_structure_raises_for_unsupported_xyz(tmp_path: Path) -> None:
    xyz_file = tmp_path / "test.xyz"
    xyz_file.write_text("1\ncomment\nH 0.0 0.0 0.0\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported structure file format"):
        load_structure(xyz_file)
