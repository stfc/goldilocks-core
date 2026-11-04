"""A6/A7 pitfall regression, v2 shape (v2 epic 9, #9).

v1's ``analyze_structure`` handled a classifier failure inconsistently:
a disordered structure or a dimensionality-classifier failure aborted
the whole call (uncaught exception), while an equivalent symmetry
-classifier failure degraded just that one field to ``None`` plus a
warning. v2's tri-state design (``analysis/geometry.py``,
``analysis/symmetry.py``) makes both cases behave the same way --
``Unavailable``, never a raise -- which is what these tests now confirm
directly against those two functions instead of v1's single combined
``analyze_structure`` entry point (deleted alongside the rest of v1's
tree at the end of this epic).

The composition heuristic behind ``is_metal`` (#164) is the third pitfall
here: it is what a run without the ML classifier reads, and it must not
call an ionic insulator a metal.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.analysis.geometry import geometry
from goldilocks_core.analysis.is_metal import is_metal
from goldilocks_core.analysis.symmetry import symmetry


def test_dimensionality_classifier_failure_degrades_instead_of_aborting() -> None:
    """A7 (half): v1's analyze_structure re-raised as
    DimensionalityClassificationError when CrystalNN/get_dimensionality_
    larsen raised on an *ordered* structure it could not classify --
    aborting the entire analysis, no record produced at all. v2's
    geometry() catches the same failure and degrades to Unavailable
    instead, matching symmetry()'s own handling below rather than being a
    second, inconsistent escape hatch. See stfc/goldilocks-core#133."""
    silicon = Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])

    with patch(
        "goldilocks_core.analysis.geometry.get_dimensionality_larsen",
        side_effect=ValueError("synthetic CrystalNN failure"),
    ):
        dimensionality = geometry(silicon)

    assert not dimensionality.ok
    assert "dimensionality classification failed" in dimensionality.reason


def test_symmetry_analyzer_failure_degrades_one_field_instead_of_aborting() -> None:
    """A7 (other half): the structurally identical failure -- an external
    classifier raising on a valid-but-awkward *ordered* structure -- was
    already caught and downgraded for symmetry in v1; v2 keeps that
    behavior (Unavailable, not a raise), now consistent with geometry()
    above instead of the odd one out."""
    silicon = Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])

    with patch(
        "goldilocks_core.analysis.symmetry.SpacegroupAnalyzer",
        side_effect=ValueError("synthetic spglib failure"),
    ):
        space_group = symmetry(silicon)

    assert not space_group.ok
    assert "symmetry analysis failed" in space_group.reason


def _rock_salt(cation: str, anion: str, a: float) -> Structure:
    return Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(a), [cation, anion], [[0, 0, 0], [0.5, 0.5, 0.5]]
    )


# Experimental lattice constants (Angstrom); wurtzite ZnO with u = 0.382.
_IONIC_INSULATORS = {
    "NaCl": _rock_salt("Na", "Cl", 5.640),
    "MgO": _rock_salt("Mg", "O", 4.212),
    "LiH": _rock_salt("Li", "H", 4.083),
    "ZnO": Structure.from_spacegroup(
        "P6_3mc",
        Lattice.hexagonal(3.250, 5.207),
        ["Zn", "O"],
        [[1 / 3, 2 / 3, 0], [1 / 3, 2 / 3, 0.382]],
    ),
}


@pytest.mark.parametrize("formula", sorted(_IONIC_INSULATORS))
def test_ionic_insulator_is_never_a_heuristic_metal(formula: str) -> None:
    """#164: with no ML classifier installed (the isolated asset root of
    every test), ``is_metal`` falls back to composition. Rock-salt NaCl,
    MgO and LiH and wurtzite ZnO have band gaps of several eV, yet the old
    rule stripped their anions and called them metals because Na, Mg, Li
    and Zn are metallic elements. Composition cannot classify them, so the
    heuristic leaves them ``Unavailable``."""
    state = is_metal(_IONIC_INSULATORS[formula])

    assert state.status == "unavailable"


def test_b2_intermetallic_is_still_a_heuristic_metal() -> None:
    """B2 NiAl (a = 2.887 Angstrom) contains only metallic elements, the one
    case where composition alone still asserts ``metal``."""
    nial = Structure.from_spacegroup(
        "Pm-3m", Lattice.cubic(2.887), ["Ni", "Al"], [[0, 0, 0], [0.5, 0.5, 0.5]]
    )

    state = is_metal(nial)

    assert state.ok
    assert state.value == "metal"
    assert state.source == "heuristic"
