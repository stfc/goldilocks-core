"""pw.x's symmetry rules and the frame the cell is written in (#140).

pw.x tests 32 fixed Cartesian rotations against the cell as written, so a
cell in pymatgen's frame (c along z, a in the xz plane) shows it only part of
its point group. The counts below are pw.x 7.5's own on the 2026-10-19
decks, run on SCARF ("Sym. Ops." and "number of k points"), for the MC3D,
MC2D and Materials Project cells those decks were written from.
"""

from __future__ import annotations

import numpy as np
import pytest
import spglib
from pymatgen.core import Lattice, Structure
from pymatgen.core.surface import SlabGenerator
from support import (
    alpha_uranium,
    graphene_with_vacuum_along_x,
    mc3d_42058_silicon,
    molybdenum_disulfide_monolayer,
    uranium_nitride,
)

from goldilocks_core.advisors.k_sampling import KSamplingDecision
from goldilocks_core.advisors.magnetic_config import (
    MagneticConfigHumanInput,
    framed_cell,
    magnetic_cell,
    magnetic_config,
)
from goldilocks_core.advisors.n_irr_k import n_irr_k
from goldilocks_core.analysis.geometry import (
    ab_in_xy_plane,
    slab_layers,
    two_d_truncation_obstacles,
    vacuum_axes,
)
from goldilocks_core.pw_symmetry import (
    FRAME_TOLERANCE,
    irreducible_kpoint_count,
    pw_frame,
    pw_rotations,
)
from goldilocks_core.resolution import Provenance, Resolved

pytestmark = pytest.mark.physics


def _cif(atoms: str, a: float, b: float, c: float, angles: tuple[float, ...]) -> str:
    alpha, beta, gamma = angles
    return f"""data_0
loop_
  _atom_site_label
  _atom_site_fract_x
  _atom_site_fract_y
  _atom_site_fract_z
  _atom_site_type_symbol
{atoms}
_cell_angle_alpha {alpha}
_cell_angle_beta {beta}
_cell_angle_gamma {gamma}
_cell_length_a {a}
_cell_length_b {b}
_cell_length_c {c}
loop_
  _symmetry_equiv_pos_as_xyz
  'x, y, z'
_symmetry_int_tables_number 1
_symmetry_space_group_name_H-M 'P 1'
"""


def _structure(atoms: str, a: float, b: float, c: float, angles) -> Structure:
    return Structure.from_str(_cif(atoms, a, b, c, angles), fmt="cif")


def aluminium() -> Structure:
    """fcc Al, MC3D mc3d-29639: the 1-atom primitive cell."""
    return _structure(
        "Al1 0.0 0.0 0.0 Al",
        2.837880560624691,
        2.837880560624691,
        2.837880560624691,
        (60.00000000000001,) * 3,
    )


def bcc_iron() -> Structure:
    """bcc Fe, MC3D mc3d-17673: the 1-atom primitive cell."""
    return _structure(
        "Fe1 0.0 0.0 0.0 Fe",
        2.4152274710117276,
        2.4152274710117276,
        2.4152274710117276,
        (109.47122063449069,) * 3,
    )


def nickel_oxide() -> Structure:
    """Rock-salt NiO, MC3D mc3d-29856: the 2-atom primitive cell."""
    return _structure(
        "Ni1 0.0 0.0 0.0 Ni\nO1 0.5 0.5 0.5 O",
        2.89336877724759,
        2.89336877724759,
        2.89336877724759,
        (60.00000000000001,) * 3,
    )


def sodium_chloride() -> Structure:
    """Rock-salt NaCl, MC3D mc3d-76777: the 2-atom primitive cell."""
    return _structure(
        "Na1 0.0 0.0 0.0 Na\nCl1 0.5000000000000007 0.49999999999999994 0.5 Cl",
        3.967170699345385,
        3.967170699345385,
        3.967170699345385,
        (59.99999999999999,) * 3,
    )


def lithium_cobalt_oxide() -> Structure:
    """Layered LiCoO2 (R-3m), MC3D mc3d-75346: the 4-atom rhombohedral
    primitive cell, whose default vc-relax deck pw.x stopped in stres_hub
    with 2 of 12 operations found."""
    return _structure(
        "Li1 0.5000000000036504 0.5000000000036505 0.5000000000036442 Li\n"
        "Co1 0.0 2.947014717736719e-37 2.9470147176790594e-37 Co\n"
        "O1 0.2609211198294755 0.2609211198294755 0.26092111982947225 O\n"
        "O2 0.7390788801778199 0.7390788801778199 0.7390788801778232 O",
        4.878348587190128,
        4.878348587190128,
        4.878348587192624,
        (33.50763848382354, 33.50763848382354, 33.507638483673276),
    )


def hematite() -> Structure:
    """Corundum Fe2O3 (R-3c), MC3D mc3d-44692: the 10-atom rhombohedral
    primitive cell."""
    return _structure(
        "Fe1 0.34530564941301856 0.34530564941301845 0.34530564941301856 Fe\n"
        "Fe2 0.8453056494130209 0.8453056494130208 0.8453056494130208 Fe\n"
        "Fe3 0.15469435057944336 0.15469435057944325 0.1546943505794432 Fe\n"
        "Fe4 0.6546943505794469 0.6546943505794471 0.654694350579447 Fe\n"
        "O1 0.5641274494279094 0.9358725505645584 0.2499999999962339 O\n"
        "O2 0.06412744943449145 0.7500000000027944 0.43587255057401253 O\n"
        "O3 0.2499999999952607 0.5641274494269362 0.9358725505665049 O\n"
        "O4 0.43587255059337443 0.06412744941415768 0.7500000000037661 O\n"
        "O5 0.9358725505778195 0.2500000000094736 0.5641274494014087 O\n"
        "O6 0.7500000000047441 0.4358725505730474 0.06412744943350669 O",
        5.182511666683269,
        5.182511666683269,
        5.182511666693951,
        (53.96289398235206, 53.96289398235206, 53.96289398197406),
    )


def lanthanum_cuprate() -> Structure:
    """T-La2CuO4 (I4/mmm), Materials Project mp-19735: the 7-atom
    body-centred primitive cell."""
    return _structure(
        "La0 0.36089300 0.36089300 0.72178600 La\n"
        "La1 0.63910700 0.63910700 0.27821400 La\n"
        "Cu2 0.00000000 0.00000000 0.00000000 Cu\n"
        "O3 0.00000000 0.50000000 0.00000000 O\n"
        "O4 0.50000000 0.00000000 0.00000000 O\n"
        "O5 0.18622600 0.18622600 0.37245200 O\n"
        "O6 0.81377400 0.81377400 0.62754800 O",
        3.81380400,
        3.81380400,
        7.14122249,
        (105.48745549, 105.48745549, 90.0),
    )


def manganese_thiophosphate_monolayer() -> Structure:
    """MnPS3 monolayer, MC2D mc2d-9ffd1741: its lattice misses the ideal
    one by 1.2e-5 A and its atoms by up to 1e-4 A, so pw.x keeps only the
    identity of its four operations."""
    return _structure(
        "P0 0.66306111 -0.00000032 0.45296354 P\n"
        "S1 0.02624365 0.99999955 0.44023695 S\n"
        "S2 0.66528178 0.64273171 0.43589274 S\n"
        "S3 0.30801345 0.35726818 0.43589239 S\n"
        "Mn4 0.33795819 0.64540778 0.50000020 Mn\n"
        "Mn5 0.98337329 0.35459231 0.50000006 Mn\n"
        "P6 0.65827057 1.00000031 0.54703642 P\n"
        "S7 0.29508767 1.00000040 0.55976288 S\n"
        "S8 0.65604996 0.35726852 0.56410724 S\n"
        "S9 0.01331841 0.64273157 0.56410758 S",
        5.65873239,
        5.82194909,
        22.94442368,
        (90.0, 90.0, 60.92326590),
    )


def cerium_telluride_monolayer() -> Structure:
    """CeTe3 monolayer, MC2D mc2d-381db876: its mirrors and glides sit off
    the cell origin, so their fractional translations are ones pw.x
    rejects until the origin moves."""
    return _structure(
        "Ce0 0.57912723 0.75000000 0.57229140 Ce\n"
        "Te1 0.57912805 0.75000000 0.45959249 Te\n"
        "Te2 0.57912257 0.25000000 0.34343102 Te\n"
        "Ce3 0.07912723 0.25000000 0.42770860 Ce\n"
        "Te4 0.07912805 0.25000000 0.54040751 Te\n"
        "Te5 0.07912257 0.75000000 0.65656898 Te\n"
        "Te6 0.57912215 0.25000000 0.65656881 Te\n"
        "Te7 0.07912215 0.75000000 0.34343119 Te",
        4.42072251,
        4.42072327,
        29.26327220,
        (90.0, 90.0, 90.0),
    )


def _point_group_order(structure: Structure) -> int:
    """The number of distinct rotations of the space group spglib finds in
    ``structure`` at ``FRAME_TOLERANCE``, its sites typed by element."""
    types = [site.specie.Z for site in structure]
    dataset = spglib.get_symmetry_dataset(
        (structure.lattice.matrix, structure.frac_coords, types),
        symprec=FRAME_TOLERANCE,
    )
    return len({rotation.tobytes() for rotation in dataset.rotations})


@pytest.mark.parametrize(
    ("build", "mesh", "operations", "kpoints"),
    [
        (mc3d_42058_silicon, (10, 10, 10), 4, 282),
        (aluminium, (13, 13, 13), 4, 595),
        (nickel_oxide, (11, 11, 11), 4, 366),
        (bcc_iron, (12, 12, 12), 12, 189),
        (uranium_nitride, (9, 9, 9), 4, 205),
        (sodium_chloride, (4, 4, 4), 4, 24),
        (alpha_uranium, (11, 10, 6), 8, 224),
        (alpha_uranium, (11, 11, 6), 8, 144),
    ],
    ids=lambda value: value.__name__ if callable(value) else None,
)
def test_counts_what_pw_x_ran_on_the_cells_as_generated(
    build, mesh: tuple[int, int, int], operations: int, kpoints: int
) -> None:
    """pw.x 7.5 on SCARF: the operations it found and the k-points it ran
    on each deck as generated, before the cell was framed. spglib's full
    group counted 47 k-points for Si, 84 for Al, 56 for NiO, 72 for bcc Fe
    and 35 for UN, which sized npool for the smaller number."""
    rotations = pw_rotations(build())

    assert len(rotations) == operations
    assert irreducible_kpoint_count(rotations, mesh, (0, 0, 0)) == kpoints


@pytest.mark.parametrize(
    ("build", "before", "after"),
    [
        (mc3d_42058_silicon, 4, 48),
        (aluminium, 4, 48),
        (bcc_iron, 12, 48),
        (nickel_oxide, 4, 48),
        (lithium_cobalt_oxide, 2, 12),
        (hematite, 2, 12),
        (alpha_uranium, 8, 8),
        (lanthanum_cuprate, 2, 16),
        (manganese_thiophosphate_monolayer, 1, 4),
        (cerium_telluride_monolayer, 4, 16),
    ],
    ids=lambda value: value.__name__ if callable(value) else None,
)
def test_the_framed_cell_shows_pw_x_its_whole_point_group(
    build, before: int, after: int
) -> None:
    structure = build()

    framed, frame = pw_frame(structure)

    assert len(pw_rotations(structure)) == before
    assert len(pw_rotations(framed)) == frame.operations == after
    assert after == _point_group_order(structure)


def test_framed_silicon_counts_the_k_points_of_its_whole_group() -> None:
    framed, frame = pw_frame(mc3d_42058_silicon())

    assert frame.rotated
    assert irreducible_kpoint_count(pw_rotations(framed), (10, 10, 10), (0, 0, 0)) == 47


def _distances(structure: Structure) -> np.ndarray:
    return structure.distance_matrix


@pytest.mark.parametrize(
    "build",
    [
        mc3d_42058_silicon,
        bcc_iron,
        lithium_cobalt_oxide,
        hematite,
        lanthanum_cuprate,
        manganese_thiophosphate_monolayer,
        cerium_telluride_monolayer,
    ],
    ids=lambda build: build.__name__,
)
def test_the_frame_is_a_rigid_motion_within_the_idealization(build) -> None:
    """Lengths, angles and interatomic distances agree within 1e-3 A (the
    idealization moves nothing further), and fractional coordinates are
    the uploaded ones up to the origin shift; species and labels stay."""
    structure = build()

    framed, frame = pw_frame(structure)

    assert np.allclose(framed.lattice.abc, structure.lattice.abc, atol=1e-3)
    assert np.allclose(framed.lattice.angles, structure.lattice.angles, atol=1e-3)
    assert np.allclose(_distances(framed), _distances(structure), atol=1e-3)
    offsets = framed.frac_coords - np.array(frame.origin_shift) - structure.frac_coords
    assert np.allclose(offsets - np.rint(offsets), 0.0, atol=1e-4)
    assert framed.labels == structure.labels
    assert framed.species == structure.species
    assert frame.max_displacement_angstrom < 1e-3


@pytest.mark.parametrize(
    "build",
    [manganese_thiophosphate_monolayer, cerium_telluride_monolayer],
    ids=lambda build: build.__name__,
)
def test_a_monolayer_in_the_xy_frame_keeps_its_orientation(build) -> None:
    """MnPS3 gains its group by idealization, CeTe3 by an in-plane origin
    shift; neither is turned, and the sheet stays in the xy plane with its
    vacuum along c."""
    structure = build()

    framed, frame = pw_frame(structure)

    assert not frame.rotated
    assert frame.origin_shift[2] == 0.0
    assert ab_in_xy_plane(framed.lattice)
    assert vacuum_axes(framed) == ("c",)


@pytest.mark.parametrize(
    "build",
    [mc3d_42058_silicon, lithium_cobalt_oxide, cerium_telluride_monolayer],
    ids=lambda build: build.__name__,
)
def test_pw_frame_is_idempotent(build) -> None:
    framed, _ = pw_frame(build())

    again, frame = pw_frame(framed)

    assert not frame.rotated
    assert frame.origin_shift == (0.0, 0.0, 0.0)
    assert frame.max_displacement_angstrom == 0.0
    assert np.array_equal(again.lattice.matrix, framed.lattice.matrix)
    assert np.array_equal(again.frac_coords, framed.frac_coords)


def _turned_about_z(structure: Structure, degrees: float) -> Structure:
    angle = np.radians(degrees)
    rotation = np.array(
        [
            [np.cos(angle), -np.sin(angle), 0],
            [np.sin(angle), np.cos(angle), 0],
            [0, 0, 1],
        ]
    )
    return Structure(
        Lattice(structure.lattice.matrix @ rotation.T),
        structure.species,
        structure.frac_coords,
    )


def test_a_monolayer_turned_about_its_normal_is_turned_back() -> None:
    """A MoS2 sheet whose a points 15 degrees off x: pw.x keeps only the
    identity (its hexagonal rotations are fixed about z with a along x).
    The frame turns it about its normal alone, putting a along +x and a x b
    along +z exactly, which QE's 2D methods and the 2D gates need."""
    turned = _turned_about_z(molybdenum_disulfide_monolayer(), 15.0)

    framed, frame = pw_frame(turned)

    a, b, c = framed.lattice.matrix
    rotation = np.array(frame.rotation)
    assert len(pw_rotations(turned)) == 1
    assert len(pw_rotations(framed)) == 12
    assert frame.rotated
    assert np.allclose(rotation @ [0, 0, 1], [0, 0, 1], atol=1e-12)
    assert a[1] == a[2] == b[2] == 0.0
    assert a[0] > 0 and c[2] > 0
    assert np.allclose(c[:2], 0.0, atol=1e-12)


def test_a_sheet_whose_two_fold_pw_x_cannot_place_keeps_half_its_group() -> None:
    """The slab frame puts a along +x (maintainer decision), and pw.x keeps
    an in-plane 2-fold axis or mirror only at a multiple of 30 or 45 degrees
    from x. The MnPS3 sheet's 2-fold lies along a in its MC2D basis, so pw.x
    keeps all four operations; in the equivalent primitive basis a' = b,
    b' = b - a it lies 60.92 degrees from a', and pw.x keeps two. The count
    is pw.x's either way: the 8x8x1 mesh, the same k-points in both bases,
    gives 34 k-points instead of 21."""
    sheet = manganese_thiophosphate_monolayer()
    rebased = sheet.copy()
    rebased.make_supercell([[0, 1, 0], [-1, 1, 0], [0, 0, 1]])

    framed, frame = pw_frame(sheet)
    framed_rebased, frame_rebased = pw_frame(rebased)

    assert _point_group_order(sheet) == _point_group_order(rebased) == 4
    assert not frame.rotated
    assert len(pw_rotations(framed)) == frame.operations == 4
    assert frame_rebased.rotated
    assert len(pw_rotations(framed_rebased)) == frame_rebased.operations == 2
    mesh, shift = (8, 8, 1), (0, 0, 0)
    assert irreducible_kpoint_count(pw_rotations(framed), mesh, shift) == 21
    assert irreducible_kpoint_count(pw_rotations(framed_rebased), mesh, shift) == 34


def test_a_turn_within_the_idealization_is_no_rotation() -> None:
    """The rebased MnPS3 sheet above, given with a along x as a CIF gives
    it: idealizing tilts a by about 2e-6 rad, and the slab frame turns it
    back. That turn moves no lattice vector by 1e-3 A and leaves the
    uploaded x, y and z where they were, so the frame records no rotation
    (Cartesian cell_dofree masks keep their meaning) and counts the turn
    in its displacement."""
    sheet = manganese_thiophosphate_monolayer()
    sheet.make_supercell([[0, 1, 0], [-1, 1, 0], [0, 0, 1]])
    along_x = Structure(
        Lattice.from_parameters(*sheet.lattice.parameters),
        sheet.species,
        sheet.frac_coords,
    )

    framed, frame = pw_frame(along_x)

    unshifted = framed.frac_coords - np.array(frame.origin_shift)
    unshifted -= np.rint(unshifted - along_x.frac_coords)
    moved = np.concatenate(
        [
            np.linalg.norm(framed.lattice.matrix - along_x.lattice.matrix, axis=1),
            np.linalg.norm(
                unshifted @ framed.lattice.matrix - along_x.cart_coords, axis=1
            ),
        ]
    )
    assert np.allclose(along_x.lattice.matrix[0][1:], 0.0, atol=1e-12)
    assert not frame.rotated
    assert frame.rotation == ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    assert moved.max() == pytest.approx(frame.max_displacement_angstrom, abs=1e-6)
    assert frame.max_displacement_angstrom < 1e-4


def _silicon_111_slab() -> Structure:
    """A Si(111) slab from pymatgen's SlabGenerator: c along z, but a and b
    tilted out of the xy plane (a = (5.43, 0, -5.43) A)."""
    silicon = Structure.from_spacegroup(
        "Fd-3m", Lattice.cubic(5.43), ["Si"], [[0, 0, 0]]
    )
    slab = SlabGenerator(silicon, (1, 1, 1), 8, 12, center_slab=True).get_slab()
    return Structure(slab.lattice, slab.species, slab.frac_coords)


def test_a_tilted_slab_is_written_in_the_xy_frame() -> None:
    """Maintainer decision: a cell whose only vacuum axis is c is turned
    rigidly so that a lies along +x and a x b along +z, so '2Dxy' and the 2D
    Coulomb truncation's in-plane frame apply to SlabGenerator's (111)
    slabs. Its layers, lengths and angles do not change."""
    slab = _silicon_111_slab()

    framed, frame = pw_frame(slab)

    a, b, _ = framed.lattice.matrix
    assert vacuum_axes(slab) == ("c",)
    assert not ab_in_xy_plane(slab.lattice)
    assert frame.rotated
    assert a[1] == a[2] == b[2] == 0.0
    assert np.cross(a, b)[2] > 0
    assert np.allclose(framed.lattice.abc, slab.lattice.abc, atol=1e-9)
    assert np.allclose(framed.lattice.angles, slab.lattice.angles, atol=1e-9)
    assert slab_layers(framed) == slab_layers(slab)
    assert len(pw_rotations(framed)) == _point_group_order(slab) == 12


def test_a_slab_with_its_vacuum_along_a_keeps_its_orientation() -> None:
    sheet = graphene_with_vacuum_along_x()

    framed, frame = pw_frame(sheet)

    assert not frame.rotated
    assert np.array_equal(framed.lattice.matrix, sheet.lattice.matrix)


def test_an_off_centre_mirror_slab_is_shifted_in_one_piece() -> None:
    """A MoS2 sheet whose Mo plane, its mirror, sits at fractional z = 0.37:
    the mirror's translation 0.74 along c is not one pw.x accepts, so it
    keeps 6 of 12 operations. The origin moves the mirror to z = 1/2, not
    to 0 where the sheet would be split across the cell boundary, and the
    bottom layer fix_bottom_layers freezes holds the same atoms."""
    sheet = molybdenum_disulfide_monolayer()
    offset = sheet.frac_coords + np.array([0.0, 0.0, 0.37 - 0.5])
    off_centre = Structure(sheet.lattice, sheet.species, offset)

    framed, frame = pw_frame(off_centre)

    heights = framed.frac_coords[:, 2]
    assert len(pw_rotations(off_centre)) == 6
    assert len(pw_rotations(framed)) == 12
    assert frame.origin_shift[2] == pytest.approx(0.13)
    assert heights[0] == pytest.approx(0.5)
    assert heights.min() > 0.0
    assert heights.max() < 1.0
    assert slab_layers(framed)[0] == slab_layers(off_centre)[0]


def test_an_off_centre_supercell_slab_is_shifted_in_one_piece() -> None:
    """The same off-centre sheet doubled along a: pw.x gives a supercell no
    fractional translation, so the origin may move only by the standard
    shift modulo whole lattice vectors, which would put the sheet across
    z = 0. Half of c further on adds no translation to an operation that
    maps c onto +-c, so it keeps every operation and the sheet in one
    piece."""
    sheet = molybdenum_disulfide_monolayer()
    offset = sheet.frac_coords + np.array([0.0, 0.0, 0.37 - 0.5])
    doubled = Structure(sheet.lattice, sheet.species, offset)
    doubled.make_supercell([2, 1, 1])

    framed, frame = pw_frame(doubled)

    heights = framed.frac_coords[:, 2]
    assert len(pw_rotations(doubled)) == 2
    assert len(pw_rotations(framed)) == frame.operations == 4
    assert frame.origin_shift[2] == pytest.approx(0.13)
    assert heights.min() == pytest.approx(0.5 - 1.585 / 20.0)
    assert heights.max() == pytest.approx(0.5 + 1.585 / 20.0)
    assert slab_layers(framed) == slab_layers(doubled)


def test_a_left_handed_slab_keeps_c_pointing_up() -> None:
    """A POSCAR keeps its handedness: this MoS2 sheet has b mirrored to -y,
    so a x b points along -z while c points along +z, which QE's 2D
    truncation needs (lz = at(3,3)/2, ``Coul_cut_2D.f90:77``). Turned 15
    degrees about z, it is turned back about z alone, not flipped to put
    a x b along +z and c along -z."""
    sheet = molybdenum_disulfide_monolayer()
    a, b, c = sheet.lattice.matrix
    mirrored = Structure(
        Lattice([a, b * np.array([1.0, -1.0, 1.0]), c]),
        sheet.species,
        sheet.frac_coords,
    )
    turned = _turned_about_z(mirrored, 15.0)

    framed, frame = pw_frame(turned)

    a, b, c = framed.lattice.matrix
    assert np.linalg.det(turned.lattice.matrix) < 0
    assert frame.rotated
    assert np.allclose(np.array(frame.rotation) @ [0, 0, 1], [0, 0, 1], atol=1e-12)
    assert a[1] == a[2] == b[2] == 0.0
    assert a[0] > 0 and b[1] < 0 and c[2] == pytest.approx(20.0)
    assert two_d_truncation_obstacles(framed) == ()
    assert len(pw_rotations(framed)) == 12


def _iron_cobalt() -> Structure:
    return Structure(Lattice.cubic(2.80), ["Fe", "Co"], [[0, 0, 0], [0.5, 0.5, 0.5]])


def _soc_cell(structure: Structure):
    return magnetic_cell(
        structure,
        Resolved("magnetic", Provenance(source="heuristic")),
        MagneticConfigHumanInput(spin_orbit_coupling=True),
    ).value


def _k_sampling(mesh: tuple[int, int, int]) -> Resolved[KSamplingDecision]:
    return Resolved(
        KSamplingDecision(mesh=mesh, shift=(0, 0, 0), k_distance=0.2),
        Provenance(source="heuristic"),
    )


def test_b2_iron_cobalt_with_spin_orbit_coupling_still_counts_126() -> None:
    """#172's magnetic count, now pw.x's rules: moments along [001] keep 16
    of B2 FeCo's 48 operations, 126 k-points of a 10^3 mesh as pw.x 7.5 ran
    it. Uploaded turned 30 degrees about z, pw.x would keep fewer; the
    framed cell turns the moments with it and counts 126 again."""
    upright = framed_cell(_soc_cell(_iron_cobalt()))
    turned = _soc_cell(_turned_about_z(_iron_cobalt(), 30.0))
    mesh = _k_sampling((10, 10, 10))

    assert n_irr_k(upright, mesh).value == 126
    assert n_irr_k(turned, mesh).value > 126
    assert n_irr_k(framed_cell(turned), mesh).value == 126


def test_the_hematite_moment_keeps_its_crystal_direction_through_the_frame() -> None:
    """The default spin-orbit moment direction is [001] of the uploaded cell,
    its third lattice vector. The frame turns rhombohedral Fe2O3 into the
    trigonal standard orientation; the moment turns with it, so it stays
    along c, and angle1/angle2 describe the turned c."""
    cell = _soc_cell(hematite())

    framed = framed_cell(cell)

    rotation = np.array(framed.frame.rotation)
    c = framed.structure.lattice.matrix[2]
    assert framed.frame.rotated
    assert np.allclose(framed.moment_axis, c / np.linalg.norm(c), atol=1e-9)
    assert np.allclose(framed.moment_axis, rotation @ cell.moment_axis, atol=1e-9)
    config = magnetic_config(Resolved(framed, Provenance(source="heuristic"))).value
    polar = np.degrees(np.arccos(c[2] / np.linalg.norm(c)))
    assert list(config.angle1.values()) == [pytest.approx(polar, abs=1e-5)] * 2
    assert config.frame == framed.frame


def test_the_frame_keeps_the_basis_the_moment_direction_is_given_in() -> None:
    """``cell_in_input_basis`` is the uploaded cell's basis, which the frame
    keeps, so the written lattice is it times the uploaded one, turned."""
    cell = _soc_cell(hematite())

    framed = framed_cell(cell)

    rotation = np.array(framed.frame.rotation)
    expected = (
        np.array(framed.cell_in_input_basis) @ hematite().lattice.matrix @ rotation.T
    )
    assert framed.cell_in_input_basis == cell.cell_in_input_basis
    assert np.allclose(framed.structure.lattice.matrix, expected, atol=1e-5)
