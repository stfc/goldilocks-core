"""Tests for the canonical StructureDocument contract and its builder."""

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.io.structures import structure_to_document


def make_si_structure() -> Structure:
    """Return a minimal ordered silicon structure."""
    return Structure(Lattice.cubic(3.5), ["Si"], [[0.0, 0.0, 0.0]])


def make_disordered_structure() -> Structure:
    """Return a structure with a mixed-occupancy site."""
    return Structure(
        Lattice.cubic(3.0),
        [{"Fe": 0.5, "Co": 0.5}, "O"],
        [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
    )


def test_structure_document_is_jsonable_and_transport_safe() -> None:
    """Serialize the document without pymatgen objects or class markers."""
    document = structure_to_document(
        make_si_structure(), source_format="poscar"
    ).to_dict()

    assert isinstance(document, dict)
    assert "@module" not in document
    assert "@class" not in document
    assert document["source"]["format"] == "poscar"


def test_structure_document_preserves_lattice_and_periodicity() -> None:
    """Record lattice vectors, parameters, volume, and periodicity."""
    document = structure_to_document(make_si_structure()).to_dict()

    lattice = document["lattice"]
    assert lattice["volume"] == pytest.approx(42.875)
    assert lattice["a"] == pytest.approx(3.5)
    assert lattice["pbc"] == [True, True, True]
    assert len(lattice["matrix"]) == 3
    assert all(len(row) == 3 for row in lattice["matrix"])
    assert document["reduced_formula"] == "Si"


def test_structure_document_preserves_all_species_and_occupancies() -> None:
    """Retain every element and its occupancy for disordered sites."""
    document = structure_to_document(make_disordered_structure()).to_dict()

    first = document["sites"][0]
    assert {s["element"] for s in first["species"]} == {"Fe", "Co"}
    by_element = {s["element"]: s["occupancy"] for s in first["species"]}
    assert by_element["Fe"] == pytest.approx(0.5)
    assert by_element["Co"] == pytest.approx(0.5)
    # The ordered oxygen site still records full occupancy.
    second = document["sites"][1]
    assert second["species"][0]["element"] == "O"
    assert second["species"][0]["occupancy"] == pytest.approx(1.0)


def test_structure_document_records_site_positions() -> None:
    """Record fractional and Cartesian coordinates for each site."""
    document = structure_to_document(make_si_structure()).to_dict()

    site = document["sites"][0]
    assert site["abc"] == [0.0, 0.0, 0.0]
    assert site["xyz"] == [0.0, 0.0, 0.0]
    assert site["label"] == "Si"
