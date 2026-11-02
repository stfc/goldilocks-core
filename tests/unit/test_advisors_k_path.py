"""The band path of the written cell (#118): the record, its provenance and
notices, bulk cells, slabs, wires and boxes, merging, and the triclinic
fallback. Physical invariants of the paths (stars, special points, 2D
coverage, QE's expansion of the written card) are in
``tests/physics/test_band_path.py``."""

from __future__ import annotations

import itertools
import math

import numpy as np
import pytest
from pydantic import ValidationError
from pymatgen.core import Lattice, Structure
from pymatgen.core.operations import SymmOp
from pymatgen.symmetry.kpath import KPathSetyawanCurtarolo
from support import (
    carbon_chain,
    carbon_pair_in_a_box,
    displaced_hcp_gadolinium,
    fcc_copper,
    fcc_lead,
    flattened_rhombohedral_silicon,
    framed_magnetic_cell,
    generated_slab,
    graphene_monolayer,
    graphene_with_c_tilted,
    graphene_with_vacuum_along_a,
    ilmenite,
    mc3d_42058_silicon,
    monoclinic_zirconia_on_a_hexagonal_lattice,
    monoclinic_zirconia_on_a_rhombic_lattice,
    oblique_carbon_sheet,
    phosphorene,
    rectangular_graphene,
    rhombohedral_bismuth_selenide,
    right_angled_monoclinic_zirconia,
    rutile_ruthenium_dioxide,
    rutile_titanium_dioxide,
    sulfur_substituted_monoclinic_zirconia,
    sulfur_substituted_right_angled_zirconia,
    tilted_straddling_molybdenum_disulfide,
)

from goldilocks_core.advisors.k_path import (
    DEFAULT_K_PATH_DISTANCE,
    KPathDecision,
    KPathHumanInput,
    k_path,
)
from goldilocks_core.resolution import Blocked, FieldState, Resolved, Unavailable

_SETYAWAN_CURTAROLO = "Setyawan and Curtarolo, Comput. Mater. Sci. 49, 299 (2010)"
_ASE = "Larsen et al., J. Phys.: Condens. Matter 29, 273002 (2017)"


def _path(state: FieldState[KPathDecision]) -> KPathDecision:
    assert isinstance(state, Resolved), state
    return state.value


def _route(decision: KPathDecision) -> str:
    return " | ".join(
        "-".join(vertex.label for vertex in branch.vertices)
        for branch in decision.branches
    )


def _codes(decision: KPathDecision) -> list[str]:
    return [warning.code for warning in decision.warnings]


def _vertices(decision: KPathDecision):
    return [vertex for branch in decision.branches for vertex in branch.vertices]


def test_diamond_silicon_gets_the_fcc_path_of_its_written_cell() -> None:
    written = framed_magnetic_cell(mc3d_42058_silicon())

    state = k_path(written)
    decision = _path(state)

    assert _route(decision) == "Gamma-X-W-K-Gamma-L-U-W-L-K | U-X"
    assert decision.convention == "setyawan_curtarolo"
    assert decision.lattice_type == "FCC"
    assert decision.space_group == "Fd-3m (227)"
    assert decision.primitive_cells == 1
    assert decision.cell is written.value.structure
    assert decision.k_path_distance == DEFAULT_K_PATH_DISTANCE == 0.025
    assert decision.warnings == ()
    for branch in decision.branches:
        assert len(branch.steps) == len(branch.vertices) - 1
        assert min(branch.steps) >= 1
    assert decision.n_kpoints == sum(sum(b.steps) + 1 for b in decision.branches)
    assert decision.n_kpoints == 306
    provenance = state.provenance
    assert provenance.source == "heuristic"
    assert provenance.field_sources == {"k_path_distance": "heuristic"}
    assert provenance.derived_from == ("magnetic",)
    assert provenance.citations == (_SETYAWAN_CURTAROLO,)
    assert "bands.yaml" in provenance.source_note


def test_each_segment_takes_the_fewest_steps_no_longer_than_the_distance() -> None:
    """steps = ceil(length / k_path_distance) on every segment: no step is
    longer than the distance, and one step fewer would be."""
    distance = 0.05
    state = k_path(
        framed_magnetic_cell(mc3d_42058_silicon()),
        KPathHumanInput(k_path_distance=distance),
    )
    decision = _path(state)

    reciprocal = decision.cell.lattice.reciprocal_lattice.matrix
    for branch in decision.branches:
        for (start, end), steps in zip(
            itertools.pairwise(branch.vertices), branch.steps, strict=True
        ):
            length = np.linalg.norm((np.array(end.k) - start.k) @ reciprocal)
            assert steps == math.ceil(round(length / distance, 5))
    assert decision.k_path_distance == distance
    assert state.provenance.field_sources == {"k_path_distance": "human"}
    assert state.provenance.source == "human"
    assert state.provenance.source_note is None


@pytest.mark.parametrize("distance", [0.0, 1e-4, -0.025, math.inf, math.nan])
def test_a_distance_outside_its_bound_is_refused(distance: float) -> None:
    with pytest.raises(ValidationError, match="k_path_distance"):
        KPathHumanInput(k_path_distance=distance)


def test_a_conventional_cell_gets_its_primitive_cells_path_folded() -> None:
    decision = _path(k_path(framed_magnetic_cell(fcc_lead())))

    assert decision.lattice_type == "FCC"
    assert decision.primitive_cells == 4
    assert _codes(decision) == ["k_path.folded_bands"]
    assert "4 primitive cells" in decision.warnings[0].message


def test_sublattices_of_opposite_spin_get_their_magnetic_cells_path() -> None:
    """Rutile RuO2 typed Ru1/Ru2 is Cmmm with a = b, so Setyawan and
    Curtarolo's ORCC path has X_1 = Y and A_1 = T: the coincident vertices
    merge, and the walk back from A_1 to Y ends the branch instead of
    retracing it."""
    written = framed_magnetic_cell(
        rutile_ruthenium_dioxide(), starting_magnetization={"Ru1": 0.5, "Ru2": -0.5}
    )

    decision = _path(k_path(written))

    assert decision.space_group == "Cmmm (65)"
    assert decision.lattice_type == "ORCC"
    assert decision.primitive_cells == 1
    assert _route(decision) == "Gamma-X-S-R-A-Z-Gamma-Y-A_1 | Z-A_1"
    for branch in decision.branches:
        for back, _, here in zip(
            branch.vertices, branch.vertices[1:], branch.vertices[2:], strict=False
        ):
            assert not np.allclose(here.k, back.k)


def test_coincident_vertices_of_a_right_angled_monoclinic_cell_merge() -> None:
    """P2_1/c with beta exactly 90 degrees puts Setyawan and Curtarolo's MCL
    vertices C and H_1 on H, and M and M_1 on E. Each point keeps its first
    label, and no two consecutive vertices coincide."""
    decision = _path(k_path(framed_magnetic_cell(right_angled_monoclinic_zirconia())))

    assert decision.space_group == "P2_1/c (14)"
    assert decision.lattice_type == "MCL"
    assert _route(decision) == "Gamma-Y-H-E-A-X-H | E-D-Z | Y-D"
    for branch in decision.branches:
        for start, end in itertools.pairwise(branch.vertices):
            assert not np.allclose(start.k, end.k)
    labels_by_point: dict[tuple[float, ...], str] = {}
    for vertex in _vertices(decision):
        point = tuple(np.round(vertex.k, 8))
        assert labels_by_point.setdefault(point, vertex.label) == vertex.label


@pytest.mark.parametrize(
    "structure",
    [
        monoclinic_zirconia_on_a_rhombic_lattice,
        monoclinic_zirconia_on_a_hexagonal_lattice,
    ],
)
def test_a_monoclinic_crystal_with_equal_axes_gets_the_whole_mcl_path(
    structure,
) -> None:
    """With the two lattice vectors normal to its unique axis equal in
    length, pymatgen leaves the standard cell out of Setyawan and
    Curtarolo's MCL setting; put in it, the cell gets their whole MCL path,
    the zone corners H, H_1, M and M_1 apart from C and E (on the zone
    boundary: ``tests/physics/test_band_path.py``)."""
    decision = _path(k_path(framed_magnetic_cell(structure())))

    assert decision.space_group == "P2_1/c (14)"
    assert decision.lattice_type == "MCL"
    assert _route(decision) == "Gamma-Y-H-C-E-M_1-A-X-H_1 | M-D-Z | Y-D"


def _turned(structure: Structure) -> Structure:
    """``structure`` in another frame: turned rigidly by 100 degrees about
    [1, 1, 1], its origin moved by (0.31, 0.17, 0.43), its sites in reverse
    order."""
    rotation = SymmOp.from_axis_angle_and_translation((1, 1, 1), 100).rotation_matrix
    return Structure(
        Lattice(structure.lattice.matrix @ rotation.T),
        structure.species[::-1],
        (structure.frac_coords[::-1] + np.array([0.31, 0.17, 0.43])) % 1.0,
    )


@pytest.mark.parametrize("frame", ["given", "turned"])
@pytest.mark.parametrize(
    ("structure", "space_group"),
    [
        (sulfur_substituted_right_angled_zirconia, "P1 (1)"),
        (displaced_hcp_gadolinium, "P-1 (2)"),
        (sulfur_substituted_monoclinic_zirconia, "P1 (1)"),
    ],
)
def test_a_right_angled_triclinic_lattice_takes_the_tri1a_table(
    structure, space_group: str, frame: str
) -> None:
    """pymatgen leaves the path of a triclinic lattice with a right
    reciprocal angle undefined, or picks a table by rounding that differs
    between frames of the cell (in the turned frame, TRI1b for the last two
    cells). In any frame the cell gets Setyawan and Curtarolo's TRI1a
    table, Gamma and the seven time-reversal-invariant points, each at its
    shortest equivalent (on the zone boundary:
    ``tests/physics/test_band_path.py``)."""
    cell = structure() if frame == "given" else _turned(structure())

    decision = _path(k_path(framed_magnetic_cell(cell)))

    assert decision.space_group == space_group
    assert decision.lattice_type == "TRI1a"
    assert _route(decision) == "X-Gamma-Y | L-Gamma-Z | N-Gamma-M | R-Gamma"
    for vertex in _vertices(decision):
        doubled = 2 * np.array(vertex.k)
        assert np.allclose(doubled, np.rint(doubled))


def test_a_cell_pymatgen_gives_no_path_for_is_a_fault_unless_triclinic(
    monkeypatch,
) -> None:
    """Goldilocks chooses Setyawan and Curtarolo's triclinic tables itself
    only for space groups 1 and 2: a pymatgen without a path for any other
    cell raises rather than publishing a triclinic path."""
    monkeypatch.setattr(KPathSetyawanCurtarolo, "kpath", property(lambda _: None))

    with pytest.raises(RuntimeError, match=r"Fd-3m \(227\)"):
        k_path(framed_magnetic_cell(mc3d_42058_silicon()))


def test_the_path_follows_the_symmetry_the_written_cell_keeps() -> None:
    """Symmetry is searched at the 1e-3 A the written cell was idealized to:
    diamond Si with one site moved 4 mA, which the written cell keeps, is
    C2/m there and gets that group's path, not the fcc path a 1e-2 A search
    would find in a symmetry pw.x does not see."""
    silicon = mc3d_42058_silicon()
    silicon.translate_sites([1], [0.004, 0.0, 0.0], frac_coords=False)

    decision = _path(k_path(framed_magnetic_cell(silicon)))

    assert decision.space_group == "C2/m (12)"
    assert decision.lattice_type == "MCLC1"


def test_a_magnetic_noncollinear_run_is_warned_about_its_symmetry() -> None:
    """Moments with spin-orbit coupling can break E(k) = E(-k); spin-orbit
    coupling without moments keeps time reversal, so diamond Si with it gets
    no notice."""
    iron = Structure.from_spacegroup(
        "Im-3m", Lattice.cubic(2.87), ["Fe"], [[0, 0, 0]]
    ).get_primitive_structure()
    spin_orbit = {"spin_polarized": True, "spin_orbit_coupling": True}

    noncollinear = _path(k_path(framed_magnetic_cell(iron, "magnetic", **spin_orbit)))
    collinear = _path(k_path(framed_magnetic_cell(iron, "magnetic")))
    nonmagnetic = _path(
        k_path(framed_magnetic_cell(mc3d_42058_silicon(), spin_orbit_coupling=True))
    )

    assert _codes(noncollinear) == ["k_path.magnetic_noncollinear_symmetry"]
    assert collinear.warnings == ()
    assert noncollinear.lattice_type == collinear.lattice_type == "BCC"
    assert nonmagnetic.warnings == ()


@pytest.mark.parametrize(
    ("structure", "space_group", "lattice_type", "flagged"),
    [
        (ilmenite, "R-3 (148)", "RHL1", True),
        (flattened_rhombohedral_silicon, "R-3 (148)", "RHL2", False),
        (rhombohedral_bismuth_selenide, "R-3m (166)", "RHL1", False),
    ],
)
def test_general_point_vertices_are_flagged_only_for_rhl1_r3_and_r3bar(
    structure, space_group: str, lattice_type: str, flagged: bool
) -> None:
    decision = _path(k_path(framed_magnetic_cell(structure())))

    assert decision.space_group == space_group
    assert decision.lattice_type == lattice_type
    assert ("k_path.non_special_vertices" in _codes(decision)) is flagged


@pytest.mark.parametrize(
    ("structure", "vacuum_axis"),
    [
        (graphene_monolayer, 2),
        (graphene_with_c_tilted, 2),
        (graphene_with_vacuum_along_a, 0),
    ],
)
def test_a_graphene_sheet_gets_the_hexagonal_2d_path(structure, vacuum_axis) -> None:
    """The same sheet gets the same path, counted in its plane, whichever
    lattice vector is the vacuum and however it leans."""
    state = k_path(framed_magnetic_cell(structure()))
    decision = _path(state)

    assert decision.convention == "bravais_2d"
    assert decision.lattice_type == "HEX2D"
    assert decision.space_group == "P6/mmm (191)"
    assert _route(decision) == "Gamma-M-K-Gamma"
    assert decision.n_kpoints == 164
    assert all(vertex.k[vacuum_axis] == 0.0 for vertex in _vertices(decision))
    assert state.provenance.citations == (_ASE,)


def test_a_tilted_sheet_straddling_the_cell_boundary_keeps_its_layer_group() -> None:
    """With c tilted, the S atoms wrapped across the cell boundary sit off
    their partners in the plane unless the layer is first made contiguous:
    the sheet would type as P1 or P-3m1."""
    written = framed_magnetic_cell(tilted_straddling_molybdenum_disulfide())
    heights = written.value.structure.frac_coords[:, 2] % 1.0
    assert heights.min() < 0.1 and heights.max() > 0.9

    decision = _path(k_path(written))

    assert decision.space_group == "P-6m2 (187)"
    assert decision.lattice_type == "HEX2D"
    assert decision.primitive_cells == 1


def test_phosphorene_gets_the_rectangular_2d_path() -> None:
    decision = _path(k_path(framed_magnetic_cell(phosphorene())))

    assert decision.lattice_type == "RECT"
    assert decision.space_group == "Pmna (53)"
    assert _route(decision) == "Gamma-X-S-Y-Gamma-S"


@pytest.mark.parametrize(
    ("bulk", "miller", "space_group", "cells"),
    [
        (rutile_titanium_dioxide, (1, 0, 1), "Pc (7)", 1),
        (fcc_copper, (2, 1, 1), "P2_1/m (11)", 4),
    ],
)
def test_a_monoclinic_slab_with_its_unique_axis_in_plane_is_rectangular(
    bulk, miller: tuple[int, int, int], space_group: str, cells: int
) -> None:
    """SlabGenerator writes these slabs with c tilted. Their layer groups
    are monoclinic with the unique axis in the sheet, whose 2D lattice is
    rectangular; Cu(211) cut from conventional fcc Cu is a 4-fold in-plane
    supercell."""
    decision = _path(k_path(framed_magnetic_cell(generated_slab(bulk(), miller))))

    assert decision.space_group == space_group
    assert decision.lattice_type == "RECT"
    assert decision.primitive_cells == cells
    assert _route(decision) == "Gamma-X-S-Y-Gamma-S"
    assert ("k_path.folded_bands" in _codes(decision)) is (cells > 1)


@pytest.mark.parametrize("obtuse", [False, True], ids=["acute", "obtuse"])
def test_an_oblique_sheet_gets_the_oblique_2d_path(obtuse: bool) -> None:
    """The obtuse basis (b, -a) of the same sheet is reduced to an acute one
    with the shorter vector first, so it gets the same path."""
    sheet = oblique_carbon_sheet(obtuse=obtuse)

    decision = _path(k_path(framed_magnetic_cell(sheet)))

    assert decision.lattice_type == "OBL"
    assert _route(decision) == "Gamma-Y-H-C-H_1-X-Gamma"
    assert decision.n_kpoints == 182
    assert all(vertex.k[2] == 0.0 for vertex in _vertices(decision))


def test_a_square_sheet_gets_the_square_2d_path() -> None:
    """ASE's SQR path, M-Gamma-X-M, on SlabGenerator's Cu(100) slab."""
    decision = _path(
        k_path(framed_magnetic_cell(generated_slab(fcc_copper(), (1, 0, 0))))
    )

    assert decision.lattice_type == "SQR"
    assert decision.space_group == "P4/nmm (129)"
    assert _route(decision) == "M-Gamma-X-M"


def test_a_honeycomb_layer_in_its_rectangular_cell_is_hexagonal_and_folded() -> None:
    """spglib reports only the operations that map the given lattice onto
    itself, so the layer is analysed on its primitive cell: in the
    rectangular cell the honeycomb would pass for centred rectangular."""
    decision = _path(k_path(framed_magnetic_cell(rectangular_graphene())))

    assert decision.lattice_type == "HEX2D"
    assert decision.primitive_cells == 2
    assert _codes(decision) == ["k_path.folded_bands"]


def test_a_wire_is_sampled_from_gamma_to_z() -> None:
    """The carbon chain's cell holds two periods (C-C 1.28 A, c = 2.56 A),
    so Z, at half a period's reciprocal vector, is (0, 0, 1)."""
    state = k_path(framed_magnetic_cell(carbon_chain()))
    decision = _path(state)

    assert decision.convention == "wire"
    assert decision.lattice_type == "LINE"
    assert _route(decision) == "Gamma-Z"
    assert decision.branches[0].vertices[1].k == (0.0, 0.0, 1.0)
    assert decision.primitive_cells == 2
    assert _codes(decision) == ["k_path.folded_bands"]
    assert state.provenance.citations == ()


def test_a_molecule_in_a_box_has_no_band_path() -> None:
    state = k_path(framed_magnetic_cell(carbon_pair_in_a_box()))

    assert isinstance(state, Blocked)
    reason = state.root_cause()
    assert "box" in reason
    assert "scf_single_point" in reason
    assert "relax" in reason


@pytest.mark.parametrize(
    "cell",
    [Blocked(by="pseudopotential table sssp is not installed"), Unavailable("x")],
    ids=["blocked", "unavailable"],
)
def test_an_unresolved_cell_blocks_the_path(cell) -> None:
    state = k_path(cell)

    assert isinstance(state, Blocked)
    expected = cell.root_cause() if isinstance(cell, Blocked) else cell.reason
    assert state.root_cause() == expected
