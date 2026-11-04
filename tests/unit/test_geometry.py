from __future__ import annotations

import numpy as np
import pytest
from pymatgen.core import Lattice, Structure
from support import (
    carbon_chain,
    carbon_pair_in_a_box,
    graphene_monolayer,
    graphene_with_c_tilted,
    graphene_with_vacuum_along_a,
    graphene_with_vacuum_along_x,
    graphite,
    molybdenum_disulfide_monolayer,
    rotated_about_x,
    with_vacuum_along,
)

from goldilocks_core.analysis.geometry import (
    ab_in_xy_plane,
    c_along_z,
    geometry,
    slab_geometry,
    slab_layers,
    two_d_truncation_obstacles,
    vacuum_axes,
)


def test_geometry_resolves_3d_for_a_bulk_structure() -> None:
    # A real diamond-cubic cell (8 atoms, generated from the space group),
    # whose covalent Si-Si bonds JmolNN's cutoffs already find. A 1-atom
    # cubic Si cell would rank 3d too, bonded to its own images through
    # the nearest-neighbour shell, but it is not a real crystal.
    silicon = Structure.from_spacegroup(
        "Fd-3m", Lattice.cubic(5.431), ["Si"], [[0.0, 0.0, 0.0]]
    )

    state = geometry(silicon)

    assert state.ok
    assert state.value.dimensionality == "3d"
    assert state.value.low_dimensional is False


def _graphene(c: float) -> Structure:
    """A graphene sheet (C-C 1.42 A) in a cell ``c`` A tall."""
    return Structure(
        Lattice.hexagonal(2.46, c), ["C", "C"], [[0, 0, 0.5], [1 / 3, 2 / 3, 0.5]]
    )


def test_a_monolayer_has_vacuum_along_c_only() -> None:
    """The widest atom-free slab along a is 2/3 of the 2.13 A spacing of
    the (100) planes; along c it is the whole 15 A cell."""
    monolayer = _graphene(15.0)

    state = geometry(monolayer)

    assert state.value.vacuum_axes == ("c",)
    assert state.value.vacuum_widths_angstrom == (1.42, 1.42, 15.0)
    assert vacuum_axes(monolayer) == ("c",)


def test_a_molecule_in_a_box_has_vacuum_along_every_axis() -> None:
    """An Si2 dimer (bond 2.25 A, along [111]) in a 12 A cubic box leaves
    10.7 A of vacuum along each lattice vector."""
    offset = 2.25 / (12.0 * 3**0.5)
    dimer = Structure(
        Lattice.cubic(12.0), ["Si", "Si"], [[0, 0, 0], [offset, offset, offset]]
    )

    state = geometry(dimer)

    assert state.value.vacuum_axes == ("a", "b", "c")
    assert state.value.vacuum_widths_angstrom == (10.7, 10.7, 10.7)


def test_a_bulk_crystal_has_no_vacuum() -> None:
    silicon = Structure.from_spacegroup(
        "Fd-3m", Lattice.cubic(5.431), ["Si"], [[0.0, 0.0, 0.0]]
    )

    state = geometry(silicon)

    assert state.value.vacuum_axes == ()
    assert state.value.vacuum_widths_angstrom == (1.36, 1.36, 1.36)


def _unwrapped_bilayer() -> Structure:
    """AB-stacked graphene sheets 3.35 A apart in a 20 A cell, written with
    fractional z of -0.084 and 1.084 as an unwrapped trajectory frame would:
    the sheets sit at z = 1.675 A and 18.325 A, with 16.65 A of vacuum
    between them."""
    z = 3.35 / 40
    return Structure(
        Lattice.hexagonal(2.46, 20.0),
        ["C", "C", "C", "C"],
        [[0, 0, -z], [1 / 3, 2 / 3, -z], [0, 0, 1 + z], [2 / 3, 1 / 3, 1 + z]],
    )


def test_unwrapped_coordinates_are_wrapped_into_the_cell() -> None:
    bilayer = _unwrapped_bilayer()

    assert geometry(bilayer).value.vacuum_widths_angstrom[2] == 16.65
    assert vacuum_axes(bilayer) == ("c",)


@pytest.mark.parametrize(
    ("build", "center", "fraction"),
    [
        # S planes at z = 0.42075 and 0.57925: 16.83 A of vacuum across z = 0.
        (molybdenum_disulfide_monolayer, 0.0, 0.8415),
        # Sheets at z = 0.08375 and 0.91625: 16.65 A of vacuum around z = 0.5.
        (_unwrapped_bilayer, 0.5, 0.8325),
    ],
    ids=["across-the-origin", "mid-cell"],
)
def test_a_slab_records_where_its_vacuum_lies(
    build, center: float, fraction: float
) -> None:
    """``vacuum_center`` is the fractional coordinate of the middle of the
    widest atom-free slab along the vacuum axis and ``vacuum_fraction`` its
    share of the cell: its width over the spacing of the planes parallel to
    the other two vectors, here the 20 A height."""
    facts = geometry(build()).value

    assert facts.slab.vacuum_center == center
    assert facts.slab.vacuum_fraction == fraction
    assert facts.slab.vacuum_fraction * 20.0 == pytest.approx(
        facts.vacuum_widths_angstrom[2]
    )


@pytest.mark.parametrize("axis", ["a", "b"])
def test_a_slab_with_its_vacuum_along_a_or_b_is_measured_along_that_axis(
    axis: str,
) -> None:
    """The MoS2 sheet with its lattice vectors permuted so the vacuum vector
    is a or b: the vacuum, the frame and the layers follow the vacuum axis,
    with the same values as along c."""
    sheet = with_vacuum_along(molybdenum_disulfide_monolayer(), axis)

    slab = geometry(sheet).value.slab

    assert (slab.vacuum_axis, slab.xy_frame, slab.fits_2d_truncation) == (
        axis,
        False,
        False,
    )
    assert (slab.vacuum_center, slab.vacuum_fraction) == (0.0, 0.8415)
    assert slab_layers(sheet) == ((2,), (0,), (1,))


@pytest.mark.parametrize(("c", "axes"), [(4.99, ()), (5.0, ()), (5.01, ("c",))])
def test_a_gap_counts_as_vacuum_only_beyond_5_angstrom(
    c: float, axes: tuple[str, ...]
) -> None:
    assert vacuum_axes(_graphene(c)) == axes


def _tilted_monolayer() -> Structure:
    """The graphene monolayer rotated rigidly by 30 degrees about x, so the
    sheet and b leave the xy plane while the vacuum stays along c."""
    return rotated_about_x(graphene_monolayer(), 30.0)


def _graphene_in_an_11_angstrom_cell() -> Structure:
    return graphene_monolayer(c=11.0)


def _molybdenum_disulfide_in_a_12_angstrom_cell() -> Structure:
    return molybdenum_disulfide_monolayer(c=12.0)


@pytest.mark.parametrize(
    ("build", "frame"),
    [
        (graphene_monolayer, ("c", True, True)),
        (graphene_with_vacuum_along_a, ("a", False, False)),
        (graphene_with_vacuum_along_x, ("a", False, False)),
        (_tilted_monolayer, ("c", False, False)),
        (graphene_with_c_tilted, ("c", True, False)),
        (_graphene_in_an_11_angstrom_cell, ("c", True, False)),
        (_molybdenum_disulfide_in_a_12_angstrom_cell, ("c", True, False)),
    ],
    ids=lambda value: value.__name__.strip("_") if callable(value) else None,
)
def test_a_slab_is_in_the_xy_frame_only_with_vacuum_along_c_and_a_b_in_xy(
    build, frame: tuple[str, bool, bool]
) -> None:
    """QE's 2D cell constraints hold c and the z components of a and b
    fixed. graphene_with_vacuum_along_x has a and b in the xy plane but its
    vacuum along a; the tilted monolayer has its vacuum along c but b out of
    the plane. QE's 2D Coulomb truncation further needs c along z, which the
    monolayer with c leaning along x misses, a cell 21 bohr (11.11 A) high,
    which the 11 A cell misses, and vacuum 20 bohr (10.58 A) wider than the
    slab, which the 3.17 A MoS2 sheet misses in a 12 A cell."""
    structure = build()

    for slab in (slab_geometry(structure), geometry(structure).value.slab):
        assert (slab.vacuum_axis, slab.xy_frame, slab.fits_2d_truncation) == frame


@pytest.mark.parametrize(
    ("build", "found"),
    [
        (graphene_monolayer, ()),
        (graphene_with_c_tilted, ("c off the z axis",)),
        (
            lambda: graphene_monolayer(c=9.0),
            (
                "a height of 9.00 Å along z (at least 11.11 Å needed)",
                "9.00 Å of vacuum around a slab 0.00 Å thick (at least 10.58 Å needed)",
            ),
        ),
    ],
    ids=["room", "c-off-z", "short-cell"],
)
def test_the_2d_truncation_obstacles_name_what_the_cell_lacks(
    build, found: tuple[str, ...]
) -> None:
    assert two_d_truncation_obstacles(build()) == found


@pytest.mark.parametrize(
    "build",
    [graphite, carbon_chain, carbon_pair_in_a_box],
    ids=lambda build: build.__name__,
)
def test_a_cell_without_exactly_one_vacuum_axis_is_not_a_slab(build) -> None:
    """Bulk graphite has no vacuum, the chain two vacuum axes, the C pair
    three, so none has a bottom to count atomic layers up from."""
    structure = build()

    assert slab_geometry(structure) is None
    assert geometry(structure).value.slab is None
    assert slab_layers(structure) is None


def test_a_cell_holding_two_slabs_has_no_layers() -> None:
    """The MoS2 sheet doubled along c, as an antiferromagnetic supercell can
    double a monolayer: two sheets with 16.83 A of vacuum between them on
    either side. Its one vacuum axis still gives it a slab frame, but the
    bottom layer of one sheet is not the bottom of the other."""
    stack = molybdenum_disulfide_monolayer() * (1, 1, 2)

    assert vacuum_axes(stack) == ("c",)
    assert slab_geometry(stack) is not None
    assert slab_layers(stack) is None


def test_slab_layers_count_up_from_the_vacuum() -> None:
    """The MoS2 sheet's three atomic layers, bottom first: the S plane below
    Mo (site 2), Mo (site 0), then the S plane above (site 1)."""
    assert slab_layers(molybdenum_disulfide_monolayer()) == ((2,), (0,), (1,))


def test_slab_layers_do_not_depend_on_where_the_cell_origin_lies() -> None:
    """Shifted by half a cell, the sheet straddles z = 0: counting from
    fractional 0 would start at its top S plane, but the layers are counted
    up from the upper edge of the vacuum."""
    sheet = molybdenum_disulfide_monolayer()
    shifted = Structure(
        sheet.lattice,
        sheet.species,
        np.mod(sheet.frac_coords + np.array([0, 0, 0.5]), 1.0),
    )

    assert slab_layers(shifted) == ((2,), (0,), (1,))


@pytest.mark.parametrize(("buckling", "layers"), [(0.45, 1), (0.55, 2)])
def test_atoms_within_half_an_angstrom_share_a_layer(
    buckling: float, layers: int
) -> None:
    """A buckled sheet (silicene's buckling is about 0.45 A) is one layer;
    beyond 0.5 A along the normal the raised atoms form a layer of their
    own."""
    sheet = Structure(
        Lattice.hexagonal(3.87, 20.0),
        ["Si", "Si"],
        [[0, 0, 0.5], [1 / 3, 2 / 3, 0.5 + buckling / 20.0]],
    )

    assert len(slab_layers(sheet)) == layers


@pytest.mark.parametrize(("z", "in_plane"), [(0.5e-8, True), (2e-8, False)])
def test_a_and_b_lie_in_the_xy_plane_to_qe_tolerance(z: float, in_plane: bool) -> None:
    """QE 7.3 tests |a_z| and |b_z| against 1e-8 in units of alat, which is
    |a| for CELL_PARAMETERS in angstrom (PW/src/Coul_cut_2D.f90:72-74)."""
    a = 2.46
    tilted_a = Lattice([[a, 0, z * a], [-a / 2, a * 3**0.5 / 2, 0], [0, 0, 20]])
    tilted_b = Lattice([[a, 0, 0], [-a / 2, a * 3**0.5 / 2, z * a], [0, 0, 20]])

    assert ab_in_xy_plane(tilted_a) is in_plane
    assert ab_in_xy_plane(tilted_b) is in_plane


@pytest.mark.parametrize(("xy", "along"), [(0.5e-8, True), (2e-8, False)])
def test_c_lies_along_z_to_the_same_tolerance(xy: float, along: bool) -> None:
    """c's x and y components, against 1e-8 times |a| like a_z and b_z."""
    a = 2.46
    in_plane = [[a, 0, 0], [-a / 2, a * 3**0.5 / 2, 0]]
    tilted_x = Lattice([*in_plane, [xy * a, 0, 20]])
    tilted_y = Lattice([*in_plane, [0, xy * a, 20]])

    assert c_along_z(tilted_x) is along
    assert c_along_z(tilted_y) is along


def test_dimensionality_classifier_failure_degrades_to_unavailable_not_a_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v2 epic 4 (#1), closing stfc/goldilocks-core#133: v1's equivalent
    failure here raised DimensionalityClassificationError uncaught and
    aborted the whole analyze_structure call, unlike the symmetry case
    (goldilocks-core-design.md:299-310's A7 asymmetry). Now both are
    Unavailable the same way -- and geometry.py no longer even depends on
    CrystalNN, the thing that used to fail here."""
    silicon = Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise ValueError("synthetic dimensionality failure")

    monkeypatch.setattr(
        "goldilocks_core.analysis.geometry.get_dimensionality_larsen", _boom
    )

    state = geometry(silicon)

    assert not state.ok
    assert state.status == "unavailable"
    assert "synthetic dimensionality failure" in state.reason
