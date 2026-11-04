from __future__ import annotations

import math
from itertools import pairwise

import numpy as np
import pytest
from pymatgen.core import Lattice, Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
from support import (
    alpha_uranium,
    graphene_monolayer,
    graphite,
    mc3d_67775_silicon,
    uranium_nitride,
)

from goldilocks_core.advisors.k_sampling import KSamplingDecision
from goldilocks_core.advisors.magnetic_config import (
    MagneticCell,
    MagneticConfigHumanInput,
    magnetic_cell,
)
from goldilocks_core.advisors.n_irr_k import n_irr_k
from goldilocks_core.analysis.geometry import LATTICE_AXES, vacuum_axes
from goldilocks_core.analysis.symmetry import SYMPREC
from goldilocks_core.kmesh import build_gamma_kmesh_entries, k_distance_to_mesh
from goldilocks_core.resolution import Provenance, Resolved


def _dense_orthorhombic(a: float, b: float, c: float) -> Structure:
    """An orthorhombic a x b x c A cell with Si atoms along its body
    diagonal, at most 4 A apart along each lattice vector: no vector is a
    vacuum axis (more than 5 A atom-free), so every axis is sampled and the
    mesh depends on the lattice alone (#159)."""
    count = math.ceil(max(a, b, c) / 4.0)
    return Structure(
        Lattice.orthorhombic(a, b, c),
        ["Si"] * count,
        [[index / count] * 3 for index in range(count)],
    )


@pytest.mark.parametrize(
    ("lengths", "spacing"),
    [
        ((3.0, 4.0, 6.0), 0.4),
        ((2.5, 7.0, 11.0), 0.27),
        ((8.0, 8.0, 8.0), 0.15),
    ],
)
def test_mesh_is_minimal_grid_that_bounds_solid_state_reciprocal_spacing(
    lengths: tuple[float, float, float],
    spacing: float,
) -> None:
    structure = _dense_orthorhombic(*lengths)

    mesh = k_distance_to_mesh(structure, spacing)
    reciprocal_lengths = tuple(2.0 * math.pi / length for length in lengths)
    expected = tuple(math.ceil(length / spacing) for length in reciprocal_lengths)

    assert mesh == expected
    for reciprocal_length, points in zip(reciprocal_lengths, mesh, strict=True):
        assert reciprocal_length / points <= spacing
        if points > 1:
            assert reciprocal_length / (points - 1) > spacing


@pytest.mark.parametrize("k_distance", [0.03, 0.1, 0.2, 0.5, 2.0])
def test_a_slab_gets_one_k_point_along_its_vacuum_at_any_spacing(
    k_distance: float,
) -> None:
    """A slab's electrons do not disperse across its vacuum, so one k-point
    samples that axis: pw.x gave the 2H-MoS2 monolayer the same total energy
    to 1e-8 Ry on 9x9x1 as on 9x9x2, in 0.6 of the time (#159). The graphene
    sheet's 15 A cell has |b_3| = 2 pi / 15 A = 0.42 A^-1, so
    ceil(|b_3| / k_distance) would give it 3 k-points at 0.2 A^-1 and 14 at
    0.03. The sheet's own axes keep the spacing, |b_1| = |b_2| =
    4 pi / (sqrt(3) a) for the hexagonal lattice."""
    slab = graphene_monolayer(c=15.0)
    in_plane = math.ceil(4 * math.pi / (math.sqrt(3) * 2.46) / k_distance)

    assert k_distance_to_mesh(slab, k_distance) == (in_plane, in_plane, 1)


def test_reciprocal_lattice_length_includes_the_2pi_factor() -> None:
    """A3: k-point spacing is only meaningful under one 2*pi convention. This
    pins the specific pymatgen behavior k_distance_to_mesh's docstring assumes
    (``Lattice.reciprocal_lattice`` already includes the 2*pi factor, the VASP
    KSPACING convention) — if a future pymatgen release changed this, every
    mesh k_distance_to_mesh produces would silently be wrong by a factor of
    2*pi, with no error anywhere."""
    lattice = Lattice.cubic(4.0)

    assert lattice.reciprocal_lattice.a == pytest.approx(2.0 * math.pi / 4.0)


def test_kmesh_ladder_never_has_an_axis_count_jump_larger_than_one() -> None:
    """A4, v2 shape (v2 epic 9, #9): v1's ladder bounded enumeration with a
    fixed per-axis count, so axes with different reciprocal lengths ran out
    of change points at different distances -- v1 then truncated the whole
    ladder the first time that produced a hole (a jump of more than one
    k-point on some axis between adjacent rungs), rather than actually
    preventing the hole.

    v2's ``build_gamma_kmesh_entries`` (``kmesh.py``, ported verbatim from
    goldilocks-data in v2 epic 6, #6) removes the need for that truncation
    outright: it bounds enumeration with one distance floor shared by every
    axis (``MIN_K_DISTANCE``), so every axis runs out of change points
    together and no hole is ever produced in the first place -- confirmed
    below over the *entire* ladder for this exact anisotropic case (76
    rungs), not just the handful v1's truncation used to stop at. This is a
    genuine v2 correctness improvement over v1's workaround, not a test
    changed to dodge a v2 regression -- see this repo's own goldilocks-data
    port docstring in ``kmesh.py`` for why the redesign works. Atoms fill
    the 20 Angstrom axis, so it is periodic, not vacuum (#159)."""
    anisotropic = _dense_orthorhombic(20.0, 3.0, 3.0)

    entries = build_gamma_kmesh_entries(anisotropic)

    assert len(entries) > 5, "ladder too short to exercise the axis-a exhaustion point"
    assert entries[0].mesh == (1, 1, 1)
    for previous, current in pairwise(entries):
        assert all(
            current_count - previous_count <= 1
            for previous_count, current_count in zip(
                previous.mesh, current.mesh, strict=True
            )
        )
    # Concrete regression check: axis "a" (the 20 Angstrom one) exhausts its
    # change points first, at rung 8, exactly where v1's truncation used to
    # cut the ladder off -- v2 keeps going instead of stopping there.
    assert entries[6].mesh == (1, 7, 7)
    assert entries[7].mesh == (2, 7, 7)


def test_floating_point_noise_at_an_integer_boundary_does_not_inflate_the_mesh() -> (
    None
):
    """A5: recip_length / k_distance can land a few ULPs above an integer due
    to floating-point representation (here, 7.000000000000001 for a cubic
    3.3 Angstrom cell probed at exactly its 1/7 boundary). Without rounding,
    ceil() would push the count to 8; k_distance_to_mesh's ceil(round(x, 5))
    must snap it back to 7."""
    lattice_length = 3.3
    structure = Structure(Lattice.cubic(lattice_length), ["Si"], [[0.0, 0.0, 0.0]])
    recip_length = 2.0 * math.pi / lattice_length
    boundary_k_distance = recip_length / 7
    raw_quotient = recip_length / boundary_k_distance
    assert math.ceil(raw_quotient) == 8, (
        "fixture assumption broken: this k_distance no longer lands just "
        "above the integer boundary it's meant to exercise"
    )

    mesh = k_distance_to_mesh(structure, boundary_k_distance)

    assert mesh == (7, 7, 7)


def _spin_orbit_cell(structure: Structure, **settings: object) -> MagneticCell:
    """``structure``'s cell for a magnetic spin-orbit run (#172)."""
    state = magnetic_cell(
        structure,
        Resolved("magnetic", Provenance(source="heuristic")),
        MagneticConfigHumanInput(spin_orbit_coupling=True, **settings),
    )
    return state.value


def _gamma_mesh(mesh: tuple[int, int, int]) -> Resolved[KSamplingDecision]:
    return Resolved(
        KSamplingDecision(mesh=mesh, shift=(0, 0, 0), k_distance=0.2),
        Provenance(source="heuristic"),
    )


def test_noncollinear_moments_lower_the_k_point_symmetry_as_pw_x_does() -> None:
    """#172: with spin-orbit coupling and moments, pw.x keeps only the
    operations that leave every moment unchanged, alone or combined with
    time reversal, and drops the plain k -> -k pairing (QE 7.3
    PW/src/setup.f90:484-485, symm_base.f90 sgam_at_mag). B2 FeCo with
    moments along [001] keeps 16 of its 48 operations, and pw.x 7.5 ran
    goldilocks' own 10x10x10 deck with 126 k-points; the structural count
    is 56, which sized npool and memory for too few k-points."""
    feco = Structure(Lattice.cubic(2.80), ["Fe", "Co"], [[0, 0, 0], [0.5, 0.5, 0.5]])
    mesh = _gamma_mesh((10, 10, 10))

    noncollinear = n_irr_k(_spin_orbit_cell(feco, moment_direction=(0, 0, 1)), mesh)
    collinear = n_irr_k(
        magnetic_cell(feco, Resolved("magnetic", Provenance(source="heuristic"))).value,
        mesh,
    )

    assert noncollinear.value == 126
    assert noncollinear.source == "heuristic"
    assert collinear.value == 56


def test_moments_along_the_tetragonal_axis_keep_the_structural_count() -> None:
    """#172: L1_0 FePt (MC3D mc3d-49510) with moments along c, its easy
    axis: the operations that keep the moments, with the time-reversed
    ones acting on k as -R, still make up the whole 4/mmm point group, so
    the count is the structural one. Moments along a break it."""
    fept = Structure(
        Lattice.tetragonal(3.86 / math.sqrt(2), 3.71),
        ["Fe", "Pt"],
        [[0, 0, 0], [0.5, 0.5, 0.5]],
    )
    mesh = _gamma_mesh((12, 12, 9))

    along_c = n_irr_k(_spin_orbit_cell(fept, moment_direction=(0, 0, 1)), mesh)
    along_a = n_irr_k(_spin_orbit_cell(fept, moment_direction=(1, 0, 0)), mesh)
    collinear = n_irr_k(
        magnetic_cell(fept, Resolved("magnetic", Provenance(source="heuristic"))).value,
        mesh,
    )

    assert along_c.value == collinear.value == 140
    assert along_a.value > 140


_MP_19735_LA2CUO4_CIF = """\
data_La2CuO4
_symmetry_space_group_name_H-M   'P 1'
_cell_length_a   3.81380400
_cell_length_b   3.81380400
_cell_length_c   7.14122249
_cell_angle_alpha   105.48745549
_cell_angle_beta   105.48745549
_cell_angle_gamma   90.00000000
_symmetry_Int_Tables_number   1
loop_
 _symmetry_equiv_pos_site_id
 _symmetry_equiv_pos_as_xyz
  1  'x, y, z'
loop_
 _atom_site_type_symbol
 _atom_site_label
 _atom_site_symmetry_multiplicity
 _atom_site_fract_x
 _atom_site_fract_y
 _atom_site_fract_z
 _atom_site_occupancy
  La  La0  1  0.36089300  0.36089300  0.72178600  1
  La  La1  1  0.63910700  0.63910700  0.27821400  1
  Cu  Cu2  1  0.00000000  0.00000000  0.00000000  1
  O  O3  1  0.00000000  0.50000000  0.00000000  1
  O  O4  1  0.50000000  0.00000000  0.00000000  1
  O  O5  1  0.18622600  0.18622600  0.37245200  1
  O  O6  1  0.81377400  0.81377400  0.62754800  1
"""

_MC2D_9FFD1741_MNPS3_CIF = """\
data_MnPS3
_symmetry_space_group_name_H-M   'P 1'
_cell_length_a   5.65873239
_cell_length_b   5.82194909
_cell_length_c   22.94442368
_cell_angle_alpha   90.00000000
_cell_angle_beta   90.00000000
_cell_angle_gamma   60.92326590
_symmetry_Int_Tables_number   1
loop_
 _symmetry_equiv_pos_site_id
 _symmetry_equiv_pos_as_xyz
  1  'x, y, z'
loop_
 _atom_site_type_symbol
 _atom_site_label
 _atom_site_symmetry_multiplicity
 _atom_site_fract_x
 _atom_site_fract_y
 _atom_site_fract_z
 _atom_site_occupancy
  P  P0  1  0.66306111  -0.00000032  0.45296354  1
  S  S1  1  0.02624365  0.99999955  0.44023695  1
  S  S2  1  0.66528178  0.64273171  0.43589274  1
  S  S3  1  0.30801345  0.35726818  0.43589239  1
  Mn  Mn4  1  0.33795819  0.64540778  0.50000020  1
  Mn  Mn5  1  0.98337329  0.35459231  0.50000006  1
  P  P6  1  0.65827057  1.00000031  0.54703642  1
  S  S7  1  0.29508767  1.00000040  0.55976288  1
  S  S8  1  0.65604996  0.35726852  0.56410724  1
  S  S9  1  0.01331841  0.64273157  0.56410758  1
"""


def _primitive_diamond_silicon() -> Structure:
    """Diamond Si in pymatgen's frame for its fcc primitive cell
    (a = 5.43 A): three equal axes the cubic group mixes."""
    return Structure(
        Lattice.from_parameters(3.84, 3.84, 3.84, 60, 60, 60),
        ["Si", "Si"],
        [[0.0, 0.0, 0.0], [0.25, 0.25, 0.25]],
    )


def _rutile() -> Structure:
    """TiO2, P4_2/mnm, a = 4.594 A, c = 2.959 A."""
    return Structure.from_spacegroup(
        "P4_2/mnm",
        Lattice.tetragonal(4.594, 2.959),
        ["Ti", "O"],
        [[0.0, 0.0, 0.0], [0.305, 0.305, 0.0]],
    )


def _body_centred_la2cuo4() -> Structure:
    """La2CuO4 (I4/mmm, T structure), Materials Project mp-19735, as MP
    serves it: the body-centred tetragonal primitive cell, whose point group
    mixes all three axes although |b_3| is about half |b_1|."""
    return Structure.from_str(_MP_19735_LA2CUO4_CIF, fmt="cif")


def _mnps3_monolayer() -> Structure:
    """MnPS3 monolayer, MC2D mc2d-9ffd1741: vacuum along c, and a and b of
    different lengths (5.659 and 5.822 A) that its point group, 2/m, mixes."""
    return Structure.from_str(_MC2D_9FFD1741_MNPS3_CIF, fmt="cif")


def _maps_onto_itself(mesh: tuple[int, int, int], rotations: np.ndarray) -> bool:
    """Whether a Gamma-centred ``mesh`` is invariant under every rotation.
    An operation with fractional rotation W acts on reciprocal fractional
    coordinates as R = W^-T, taking the mesh point (m_j / n_j) to
    (sum_j R_ij m_j / n_j), which is a mesh point for every m exactly when
    each n_i R_ij / n_j is an integer."""
    counts = np.array(mesh, dtype=float)
    for rotation in rotations:
        scaled = counts[:, None] * np.linalg.inv(rotation).T / counts[None, :]
        if not np.allclose(scaled, np.rint(scaled)):
            return False
    return True


@pytest.mark.parametrize(
    "structure",
    [
        _primitive_diamond_silicon(),
        graphite(),
        _rutile(),
        alpha_uranium(),
        uranium_nitride(),
        _body_centred_la2cuo4(),
        mc3d_67775_silicon(),
        _mnps3_monolayer(),
    ],
    ids=[
        "primitive diamond Si",
        "graphite",
        "rutile",
        "alpha-U mp-44",
        "UN mp-1865",
        "La2CuO4 mp-19735",
        "hexagonal Si mc3d-67775",
        "MnPS3 monolayer mc2d-9ffd1741",
    ],
)
def test_every_mesh_is_invariant_under_the_point_group_and_keeps_the_spacing(
    structure: Structure,
) -> None:
    """#163: pw.x reduces a k-mesh by the operations that map it onto
    itself, so a mesh the point group does not keep costs k-points: alpha-U's
    11x10x6 ran with 224 irreducible points where 11x11x6 ran with 144, and
    La2CuO4's 8x8x4 is not invariant either. Every rung of the ladder and
    every mesh a k-distance gives is invariant under the cell's point group,
    and still at least as dense as asked along each periodic axis: |b_i| /
    n_i is at most the k-distance (for a rung, the lower end of its
    interval), up to the 5-decimal rounding of the quotient. A vacuum axis
    keeps its one division (#159)."""
    rotations = (
        SpacegroupAnalyzer(structure, symprec=SYMPREC).get_symmetry_dataset().rotations
    )
    lengths = structure.lattice.reciprocal_lattice.abc
    vacuum = vacuum_axes(structure)
    periodic = [index for index, axis in enumerate(LATTICE_AXES) if axis not in vacuum]

    def spaced(mesh: tuple[int, int, int], k_distance: float) -> bool:
        return all(
            lengths[index] / mesh[index] <= k_distance * (1 + 1e-5)
            for index in periodic
        )

    for entry in build_gamma_kmesh_entries(structure):
        assert _maps_onto_itself(entry.mesh, rotations), entry
        assert spaced(entry.mesh, entry.k_distance_interval[0]), entry
    for k_distance in (0.1, 0.15, 0.237770676612854, 0.3):
        mesh = k_distance_to_mesh(structure, k_distance)
        assert _maps_onto_itself(mesh, rotations), (k_distance, mesh)
        assert spaced(mesh, k_distance), (k_distance, mesh)
