from __future__ import annotations

import pytest
from pymatgen.core import Lattice, Structure
from support import (
    graphite,
    janus_molybdenum_sulfide_selenide,
    molybdenum_disulfide_monolayer,
)

from goldilocks_core.analysis.symmetry import symmetry


def test_symmetry_resolves_space_group_for_a_simple_structure() -> None:
    silicon = Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])

    state = symmetry(silicon)

    assert state.ok
    assert state.value.space_group_number > 0
    assert state.value.crystal_system == "cubic"


def _tetrahedral_sheet() -> Structure:
    """A square SiO4-like sheet in a 20 A cell: one O pair 1 A above Si along
    a, the other 1 A below along b. It has neither inversion nor a mirror in
    the sheet (point group -42m), but its S4 axis along c and C2 axes in the
    sheet map c to -c."""
    c = 20.0
    return Structure(
        Lattice.tetragonal(4.0, c),
        ["Si", "O", "O", "O", "O"],
        [
            [0, 0, 0.5],
            [0.2, 0, 0.5 + 1 / c],
            [0.8, 0, 0.5 + 1 / c],
            [0, 0.2, 0.5 - 1 / c],
            [0, 0.8, 0.5 - 1 / c],
        ],
    )


@pytest.mark.parametrize(
    "build",
    [molybdenum_disulfide_monolayer, _tetrahedral_sheet, graphite],
    ids=lambda build: build.__name__.strip("_"),
)
def test_an_operation_that_maps_c_to_minus_c_makes_c_reversible(build) -> None:
    """A sheet cannot carry a dipole along a normal that one of its point
    operations reverses: the MoS2 sheet (P-6m2) has a mirror through Mo, the
    -42m sheet an S4 axis, graphite inversion. ``reversible_axes`` names each
    lattice vector whose plane normal (the normal to the other two) some
    operation maps to its negative."""
    state = symmetry(build())

    assert "c" in state.value.reversible_axes


def test_a_janus_sheet_is_polar_along_its_normal() -> None:
    """Janus MoSSe (P3m1) has S on one side of Mo and Se on the other: no
    operation maps c, or any other plane normal, to its negative."""
    state = symmetry(janus_molybdenum_sulfide_selenide())

    assert state.value.space_group_symbol == "P3m1"
    assert state.value.reversible_axes == ()


def test_reversible_axes_are_listed_in_a_b_c_order() -> None:
    """Inversion reverses every plane normal."""
    assert symmetry(graphite()).value.reversible_axes == ("a", "b", "c")


def test_symmetry_analyzer_failure_degrades_to_unavailable_not_a_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v2 epic 4 (#1): the same failure v1 downgraded to None fields + a
    warning is now Unavailable -- named the same way geometry.py's
    equivalent failure now is too (goldilocks-core-design.md:299-310's A7
    asymmetry, fixed for both instead of just this one)."""
    silicon = Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise ValueError("synthetic spglib failure")

    monkeypatch.setattr("goldilocks_core.analysis.symmetry.SpacegroupAnalyzer", _boom)

    state = symmetry(silicon)

    assert not state.ok
    assert state.status == "unavailable"
    assert "synthetic spglib failure" in state.reason
