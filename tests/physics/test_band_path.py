"""Physical invariants of the band path (#118), each computed here from the
written cell and spglib, independently of how the path was built: the
stars of the textbook points of fcc, rhombohedral and hexagonal zones,
special points, the 2D time-reversal-invariant points a slab's path must
visit, and QE's expansion of the path's K_POINTS card into the k-points
pw.x runs."""

from __future__ import annotations

import itertools
import math

import numpy as np
import pytest
import spglib
from pymatgen.core import Structure
from support import (
    antiferromagnetic_nickel_oxide,
    carbon_chain,
    displaced_hcp_gadolinium,
    distorted_tungsten_ditelluride_sheet,
    fcc_copper,
    fcc_lead,
    flattened_rhombohedral_silicon,
    framed_magnetic_cell,
    generated_slab,
    graphene_monolayer,
    graphene_with_a_60_degree_cell,
    graphene_with_c_tilted,
    graphite,
    hcp_gadolinium,
    ilmenite,
    layered_antiferromagnetic_nickel,
    mc3d_42058_silicon,
    monoclinic_zirconia_on_a_hexagonal_lattice,
    monoclinic_zirconia_on_a_rhombic_lattice,
    oblique_carbon_sheet,
    phosphorene,
    points_along_lines,
    rectangular_graphene,
    rhombohedral_bismuth_selenide,
    right_angled_monoclinic_zirconia,
    rutile_ruthenium_dioxide,
    rutile_titanium_dioxide,
    sheared_sulfur_substituted_zirconia,
    sulfur_substituted_monoclinic_zirconia,
    sulfur_substituted_right_angled_zirconia,
)

from goldilocks_core.advisors.k_path import KPathDecision, k_path
from goldilocks_core.analysis.geometry import LATTICE_AXES, vacuum_axes
from goldilocks_core.generation.quantum_espresso.bands import k_points_crystal_b

pytestmark = pytest.mark.physics

_SYMPREC = 1e-3
"""Angstrom: the tolerance the written cell was idealized to."""

_FCC_STARS = {
    "Gamma": (0, 0, 0),
    "X": (0, 0, 1),
    "L": (0.5, 0.5, 0.5),
    "W": (0, 0.5, 1),
    "K": (0, 0.75, 0.75),
    "U": (0.25, 0.25, 1),
}
"""The magnitudes of each fcc vertex's coordinates along the cube axes, in
units of 2 pi / a, sorted: a point is in the vertex's star when the
magnitudes of its coordinates are these."""

_GENERAL_IN_RHL1_R3 = frozenset({"B", "B_1", "P", "P_1", "Q", "X"})

_NICKEL_OXIDE_SEEDS = {"starting_magnetization": {"Ni1": 0.5, "Ni2": -0.5}}
_RUTHENIUM_DIOXIDE_SEEDS = {"starting_magnetization": {"Ru1": 0.5, "Ru2": -0.5}}


def _decision(structure: Structure, **settings) -> KPathDecision:
    state = k_path(framed_magnetic_cell(structure, **settings))
    assert state.ok, state
    return state.value


def _vertices(decision: KPathDecision):
    return [vertex for branch in decision.branches for vertex in branch.vertices]


def _labelled(decision: KPathDecision, label: str) -> tuple[float, float, float]:
    (k,) = {vertex.k for vertex in _vertices(decision) if vertex.label == label}
    return k


def _reciprocal(lattice: np.ndarray) -> np.ndarray:
    return 2 * np.pi * np.linalg.inv(lattice).T


def _cartesian(decision: KPathDecision, k) -> np.ndarray:
    return np.asarray(k) @ _reciprocal(decision.cell.lattice.matrix)


def _cube_axes(lattice: np.ndarray, a: float) -> np.ndarray:
    """Unit vectors along the cube axes of a cubic lattice with conventional
    edge ``a``: three orthogonal lattice vectors of length a among the small
    integer combinations of the rows of ``lattice``."""
    edges = [
        vector
        for coefficients in itertools.product(range(-2, 3), repeat=3)
        if abs(np.linalg.norm(vector := np.array(coefficients) @ lattice) - a) < 1e-3
    ]
    for first, second, third in itertools.combinations(edges, 3):
        if abs(first @ second) + abs(first @ third) + abs(second @ third) < 1e-3:
            return np.array([first, second, third]) / a
    raise AssertionError("no cube axes")


def _dataset(structure: Structure) -> spglib.SpglibDataset:
    """spglib's dataset of ``structure`` with its sites typed by label, as
    pw.x types its species."""
    index: dict[str, int] = {}
    types = [index.setdefault(site.label, len(index)) for site in structure]
    return spglib.get_symmetry_dataset(
        (structure.lattice.matrix, structure.frac_coords, types), symprec=_SYMPREC
    )


def _point_group(rotations) -> list[np.ndarray]:
    """The distinct matrices among ``rotations`` and their negatives: the
    point group with time reversal, which pairs k with -k."""
    side = len(rotations[0])
    distinct = {
        tuple(np.ravel(m)) for rotation in rotations for m in (rotation, -rotation)
    }
    return [np.array(matrix).reshape(side, side) for matrix in distinct]


def _pure_translations(dataset: spglib.SpglibDataset) -> np.ndarray:
    identity = np.all(dataset.rotations == np.eye(3, dtype=int), axis=(1, 2))
    return dataset.translations[identity]


def _reciprocal_vector(g: np.ndarray, translations: np.ndarray) -> bool:
    """Whether ``g``, in the cell's reciprocal crystal coordinates, is a
    reciprocal vector of the primitive lattice -- the cell's lattice and its
    pure ``translations``: integer, with an integer phase on each."""
    phases = translations @ g
    return bool(
        np.allclose(g, np.rint(g), atol=1e-6)
        and np.allclose(phases, np.rint(phases), atol=1e-6)
    )


def _stabiliser(k: np.ndarray, group, translations: np.ndarray) -> int:
    """How many operations of ``group`` leave ``k`` in place modulo the
    primitive reciprocal lattice."""
    return sum(_reciprocal_vector(k @ rotation - k, translations) for rotation in group)


@pytest.mark.parametrize(
    ("structure", "a"),
    [(mc3d_42058_silicon, 3.8408466175 * math.sqrt(2)), (fcc_lead, 4.919)],
    ids=["diamond_silicon", "conventional_lead"],
)
def test_fcc_vertices_lie_in_their_textbook_stars(structure, a: float) -> None:
    """X <100>, L <1/2 1/2 1/2>, W <1 1/2 0>, K <3/4 3/4 0> and
    U <1 1/4 1/4>, in units of 2 pi / a; the 4-atom cubic cell of Pb gets
    the same Cartesian points as the primitive cell."""
    decision = _decision(structure())

    axes = _cube_axes(decision.cell.lattice.matrix, a)
    for vertex in _vertices(decision):
        along_axes = axes @ _cartesian(decision, vertex.k) / (2 * np.pi / a)
        assert np.allclose(
            sorted(np.abs(along_axes)), _FCC_STARS[vertex.label], atol=1e-6
        ), vertex


def test_a_conventional_cells_zone_folds_x_onto_gamma() -> None:
    """X of the fcc zone, (2 pi / a)(1, 0, 0), is a reciprocal lattice vector
    of the 4-atom cubic cell: the bands at X are folded onto Gamma."""
    x = np.array(_labelled(_decision(fcc_lead()), "X"))

    assert np.allclose(x, np.rint(x))


def test_an_antiferromagnetic_cell_gets_the_zone_of_its_magnetic_order() -> None:
    """NiO's AFM-II order doubles the fcc period along [111]: the magnetic
    cell's Z lies on the 3-fold axis at half the fcc Gamma-L distance, and
    fcc L becomes a reciprocal lattice vector."""
    decision = _decision(antiferromagnetic_nickel_oxide(), **_NICKEL_OXIDE_SEEDS)

    lattice = decision.cell.lattice.matrix
    axis = lattice.sum(axis=0) / np.linalg.norm(lattice.sum(axis=0))
    fcc_l = math.sqrt(3) * math.pi / 4.17 * axis
    phases = lattice @ fcc_l / (2 * np.pi)
    assert np.allclose(phases, np.rint(phases))
    z = _cartesian(decision, _labelled(decision, "Z"))
    assert np.linalg.norm(np.cross(z, axis)) < 1e-9
    assert math.isclose(np.linalg.norm(z), np.linalg.norm(fcc_l) / 2)


def test_a_layered_order_on_a_cubic_lattice_gets_the_path_of_its_layers() -> None:
    """AFM-I Ni is a tetragonal crystal on a cubic lattice. Of the lattice
    mappings onto its primitive cell only those that keep the layering axis
    (a) carry its sites over, so Z, half the reciprocal period between like
    planes, lies along that axis, pi / a from Gamma."""
    decision = _decision(
        layered_antiferromagnetic_nickel(),
        starting_magnetization={"Ni1": 0.5, "Ni2": -0.5},
    )

    assert decision.space_group == "P4/mmm (123)"
    assert decision.lattice_type == "TET"
    assert decision.primitive_cells == 2
    layering = decision.cell.lattice.matrix[0] / 3.52
    z = _cartesian(decision, _labelled(decision, "Z"))
    assert np.linalg.norm(np.cross(z, layering)) < 1e-9
    assert math.isclose(np.linalg.norm(z), math.pi / 3.52)


@pytest.mark.parametrize(
    ("structure", "a", "c"),
    [(hcp_gadolinium, 3.642, 5.902), (graphite, 2.46, 6.71)],
    ids=["hcp_gadolinium", "graphite"],
)
def test_hexagonal_zone_vertices_lie_at_their_textbook_distances(
    structure, a: float, c: float
) -> None:
    """|M| = 2 pi / (sqrt(3) a), |K| = 4 pi / (3 a), and A at pi / c along
    the c axis."""
    decision = _decision(structure())

    m = _cartesian(decision, _labelled(decision, "M"))
    k = _cartesian(decision, _labelled(decision, "K"))
    a_point = _cartesian(decision, _labelled(decision, "A"))
    c_axis = decision.cell.lattice.matrix[2] / c
    assert math.isclose(np.linalg.norm(m), 2 * math.pi / (math.sqrt(3) * a))
    assert math.isclose(np.linalg.norm(k), 4 * math.pi / (3 * a))
    assert math.isclose(abs(a_point @ c_axis), math.pi / c)
    assert math.isclose(np.linalg.norm(a_point), math.pi / c)


_BULK_CELLS = [
    (mc3d_42058_silicon, {}),
    (fcc_lead, {}),
    (hcp_gadolinium, {}),
    (graphite, {}),
    (rhombohedral_bismuth_selenide, {}),
    (flattened_rhombohedral_silicon, {}),
    (right_angled_monoclinic_zirconia, {}),
    (monoclinic_zirconia_on_a_rhombic_lattice, {}),
    (monoclinic_zirconia_on_a_hexagonal_lattice, {}),
    (sulfur_substituted_right_angled_zirconia, {}),
    (displaced_hcp_gadolinium, {}),
    (sulfur_substituted_monoclinic_zirconia, {}),
    (sheared_sulfur_substituted_zirconia, {}),
    (antiferromagnetic_nickel_oxide, _NICKEL_OXIDE_SEEDS),
    (rutile_ruthenium_dioxide, _RUTHENIUM_DIOXIDE_SEEDS),
    (ilmenite, {}),
]
"""Bulk cells of every Setyawan-Curtarolo case met here, each with its
magnetic settings: conventional and rhombohedral cells; monoclinic crystals
on orthorhombic, C-centred orthorhombic and hexagonal metrics; P1 and P-1
cells on orthorhombic, hexagonal, monoclinic and all-acute lattices; and
antiferromagnetic orders."""


@pytest.mark.parametrize(
    ("structure", "settings"),
    _BULK_CELLS,
    ids=lambda value: getattr(value, "__name__", "seeds"),
)
def test_every_bulk_vertex_is_a_special_point(structure, settings) -> None:
    """Every vertex but Gamma is left in place, modulo reciprocal lattice
    vectors, by an operation of the typed cell's point group with time
    reversal other than the identity -- except, in R3 and R-3 with the RHL1
    variant (ilmenite), Setyawan and Curtarolo's B, B_1, P, P_1, Q and X,
    which are general points there."""
    decision = _decision(structure(), **settings)

    dataset = _dataset(decision.cell)
    group = _point_group(dataset.rotations)
    translations = _pure_translations(dataset)
    general = (
        _GENERAL_IN_RHL1_R3
        if decision.lattice_type == "RHL1" and dataset.number in (146, 148)
        else frozenset()
    )
    for vertex in _vertices(decision):
        if vertex.label == "Gamma":
            continue
        order = _stabiliser(np.array(vertex.k), group, translations)
        assert (order == 1) is (vertex.label in general), (vertex, order)


@pytest.mark.parametrize(
    ("structure", "settings"),
    _BULK_CELLS,
    ids=lambda value: getattr(value, "__name__", "seeds"),
)
def test_every_bulk_vertex_but_gamma_lies_on_the_zone_boundary(
    structure, settings
) -> None:
    """Each vertex lies on the boundary of the first Brillouin zone of the
    typed cell's primitive lattice, as far from Gamma as from the nearest
    other reciprocal lattice vector of it, so every segment from Gamma stays
    in the zone -- also where Setyawan and Curtarolo's coordinates, read on
    pymatgen's standard cell, can lie outside it: on triclinic lattices
    (TRI1b's N on an all-acute cell, TRI1a's points with a right reciprocal
    angle beside an acute one), and on monoclinic crystals whose two lattice
    vectors normal to the unique axis are equal in length, whose standard
    cell pymatgen leaves out of their setting."""
    decision = _decision(structure(), **settings)

    translations = _pure_translations(_dataset(decision.cell))
    reciprocal = _reciprocal(decision.cell.lattice.matrix)
    lattice_vectors = [
        np.array(m) @ reciprocal
        for m in itertools.product(range(-3, 4), repeat=3)
        if any(m) and _reciprocal_vector(np.array(m), translations)
    ]
    for vertex in _vertices(decision):
        if vertex.label == "Gamma":
            continue
        point = np.array(vertex.k) @ reciprocal
        nearest = min(np.linalg.norm(point - vector) for vector in lattice_vectors)
        assert math.isclose(np.linalg.norm(point), nearest, abs_tol=1e-9), vertex


def _slab_and_its_normal_c(bulk: Structure, miller) -> tuple[Structure, Structure]:
    slab = generated_slab(bulk, miller)
    return slab, slab.get_orthogonal_c_slab()


_SHEETS = {
    "graphene": lambda: (graphene_monolayer(), None),
    "rectangular_graphene": lambda: (rectangular_graphene(), None),
    "phosphorene": lambda: (phosphorene(), None),
    "oblique_sheet": lambda: (oblique_carbon_sheet(), None),
    "obtuse_oblique_sheet": lambda: (oblique_carbon_sheet(obtuse=True), None),
    "graphene_60_degrees": lambda: (graphene_with_a_60_degree_cell(), None),
    "distorted_wte2": lambda: (distorted_tungsten_ditelluride_sheet(), None),
    "tio2_101": lambda: _slab_and_its_normal_c(rutile_titanium_dioxide(), (1, 0, 1)),
    "tio2_111": lambda: _slab_and_its_normal_c(rutile_titanium_dioxide(), (1, 1, 1)),
    "cu_211": lambda: _slab_and_its_normal_c(fcc_copper(), (2, 1, 1)),
    "cu_100": lambda: _slab_and_its_normal_c(fcc_copper(), (1, 0, 0)),
}
"""Sheets with their vacuum along c, each with the same sheet with c along
its normal where c is tilted (SlabGenerator's slabs): on that cell spglib's
operations are the sheet's own -- those that map its lattice onto itself, so
on the rectangular cell of graphene only its rectangular subgroup."""

_COVERAGE_SHEETS = [name for name in _SHEETS if name != "rectangular_graphene"]
"""Every sheet but rectangular graphene, whose three M points the
rectangular subgroup splits into two classes the path need not both visit."""


def _sheet(name: str):
    """The written cell's path for sheet ``name`` and the sheet's 2D
    symmetry in its in-plane basis: the in-plane blocks of its point group
    with time reversal, the in-plane parts of its pure translations, and its
    in-plane reciprocal vectors."""
    structure, normal_c = _SHEETS[name]()
    reference = normal_c or structure
    dataset = _dataset(reference)
    group = _point_group([rotation[:2, :2] for rotation in dataset.rotations])
    translations = _pure_translations(dataset)[:, :2]
    reciprocal = _reciprocal(reference.lattice.matrix)[:2]
    return _decision(structure), group, translations, reciprocal


def _on_path(point: np.ndarray, decision: KPathDecision, reciprocal) -> bool:
    """Whether the in-plane ``point`` lies on a segment of the path."""
    target = point @ reciprocal
    for branch in decision.branches:
        for start, end in itertools.pairwise(branch.vertices):
            first = np.array(start.k)[:2] @ reciprocal
            segment = np.array(end.k)[:2] @ reciprocal - first
            fraction = np.clip((target - first) @ segment / (segment @ segment), 0, 1)
            if np.linalg.norm(first + fraction * segment - target) < 1e-6:
                return True
    return False


@pytest.mark.parametrize("name", _COVERAGE_SHEETS)
def test_a_sheets_path_visits_every_2d_time_reversal_invariant_point(
    name: str,
) -> None:
    """Gamma and the other three time-reversal-invariant points of the
    sheet's primitive 2D lattice -- k with 2k a reciprocal lattice vector of
    it -- lie on the path, up to the sheet's 2D point group with time
    reversal and reciprocal lattice vectors. The written cell can be an
    in-plane supercell (Cu(211) cut from the conventional cell is 4-fold),
    so the points are found on a half-integer grid of its reciprocal
    basis."""
    decision, group, translations, reciprocal = _sheet(name)
    cells = len(translations)

    classes: list[np.ndarray] = []
    for m in itertools.product(range(2 * cells), repeat=2):
        k = np.array(m) / 2
        invariant = _reciprocal_vector(2 * k, translations)
        if invariant and not any(
            _reciprocal_vector(k - other, translations) for other in classes
        ):
            classes.append(k)
    shifts = [
        np.array(m)
        for m in itertools.product(range(-2 * cells, 2 * cells + 1), repeat=2)
        if _reciprocal_vector(np.array(m), translations)
    ]

    assert len(classes) == 4
    for k in classes:
        assert any(
            _on_path(k @ rotation + shift, decision, reciprocal)
            for rotation in group
            for shift in shifts
        ), (name, k)


@pytest.mark.parametrize("name", list(_SHEETS))
def test_every_sheet_vertex_but_the_oblique_corners_is_a_special_point(
    name: str,
) -> None:
    """In the plane, every vertex but Gamma is left in place by an operation
    of the sheet's 2D point group with time reversal other than the
    identity, except the corners H and H_1 of ASE's oblique path, general
    points of an oblique zone."""
    decision, group, translations, _ = _sheet(name)

    for vertex in _vertices(decision):
        if vertex.label == "Gamma":
            continue
        order = _stabiliser(np.array(vertex.k)[:2], group, translations)
        corner = decision.lattice_type == "OBL" and vertex.label in ("H", "H_1")
        assert (order == 1) is corner, (vertex, order)


@pytest.mark.parametrize("name", list(_SHEETS))
def test_every_sheet_vertex_but_gamma_lies_on_the_zone_boundary(name: str) -> None:
    """Each of ASE's 2D points lies on the boundary of the sheet's
    primitive 2D Brillouin zone: as far from Gamma as from the nearest other
    reciprocal lattice vector."""
    decision, _, translations, reciprocal = _sheet(name)
    cells = len(translations)

    lattice_vectors = [
        np.array(m) @ reciprocal
        for m in itertools.product(range(-2 * cells, 2 * cells + 1), repeat=2)
        if any(m) and _reciprocal_vector(np.array(m), translations)
    ]
    for vertex in _vertices(decision):
        if vertex.label == "Gamma":
            continue
        point = np.array(vertex.k)[:2] @ reciprocal
        nearest = min(np.linalg.norm(point - vector) for vector in lattice_vectors)
        assert math.isclose(np.linalg.norm(point), nearest, abs_tol=1e-9), vertex


def test_a_rectangular_sheets_x_lies_along_its_shorter_lattice_vector() -> None:
    """ASE's RECT has a < b, with X at pi / a, Y at pi / b and S at the
    corner between them."""
    decision = _decision(phosphorene())

    short, long = sorted(np.linalg.norm(decision.cell.lattice.matrix[:2], axis=1))
    x, y, s = (
        np.linalg.norm(_cartesian(decision, _labelled(decision, label)))
        for label in ("X", "Y", "S")
    )
    assert math.isclose(x, math.pi / short)
    assert math.isclose(y, math.pi / long)
    assert math.isclose(s, math.hypot(x, y))


@pytest.mark.parametrize(
    "structure",
    [graphene_monolayer, graphene_with_c_tilted, graphene_with_a_60_degree_cell],
    ids=["c_normal", "c_tilted", "b_at_60_degrees"],
)
def test_graphene_zone_vertices_lie_at_their_textbook_in_plane_distances(
    structure,
) -> None:
    """In the sheet's plane, |M| = 2 pi / (sqrt(3) a) and |K| = 4 pi / (3 a),
    a = 2.46 A, however c leans and whichever basis the sheet is given in."""
    decision = _decision(structure())

    lattice = decision.cell.lattice.matrix
    normal = np.cross(lattice[0], lattice[1])
    normal /= np.linalg.norm(normal)
    expected = {
        "Gamma": 0.0,
        "M": 2 * math.pi / (math.sqrt(3) * 2.46),
        "K": 4 * math.pi / (3 * 2.46),
    }
    for vertex in _vertices(decision):
        cartesian = _cartesian(decision, vertex.k)
        in_plane = np.linalg.norm(cartesian - (cartesian @ normal) * normal)
        assert math.isclose(in_plane, expected[vertex.label], abs_tol=1e-9)


def _expanded(card: str) -> tuple[np.ndarray, np.ndarray]:
    """The k-points pw.x generates from a K_POINTS crystal_b ``card``, read
    as QE 7.3 reads it (``Modules/read_cards.f90:761-838``): the number of
    vertices, then for each vertex three coordinates and the nearest integer
    to a fourth number, the rest of the row unread, expanded in crystal
    coordinates as ``generate_k_along_lines`` expands them
    (``support.points_along_lines``): a weight w puts w equal steps up to
    the next vertex, and 0 jumps straight to it. Also returns, for each pair
    of consecutive points, whether it is such a jump."""
    header, count, *rows = card.splitlines()
    assert header == "K_POINTS crystal_b"
    assert len(rows) == int(count)
    vertices = [np.array([float(value) for value in row.split()[:3]]) for row in rows]
    weights = [round(float(row.split()[3])) for row in rows]
    return points_along_lines(vertices, weights)


@pytest.mark.parametrize(
    ("structure", "settings"),
    [
        (mc3d_42058_silicon, {}),
        (fcc_lead, {}),
        (hcp_gadolinium, {}),
        (right_angled_monoclinic_zirconia, {}),
        (rutile_ruthenium_dioxide, _RUTHENIUM_DIOXIDE_SEEDS),
        (graphene_with_c_tilted, {}),
        (phosphorene, {}),
        (oblique_carbon_sheet, {}),
        (carbon_chain, {}),
    ],
    ids=lambda value: getattr(value, "__name__", "seeds"),
)
def test_qe_expands_the_written_card_into_the_points_counted(
    structure, settings
) -> None:
    """The bands step's K_POINTS card, expanded as pw.x expands it, holds
    ``n_kpoints`` points; no step is longer than ``k_path_distance`` along
    the periodic directions; no two consecutive points lie within bands.x's
    1e-4 2 pi / alat of each other, which would leave it without its plot
    file (``PP/src/bands.f90:537-541``); and no point repeats the one two
    places back, a walk back along the path."""
    decision = _decision(structure(), **settings)

    points, jumps = _expanded(k_points_crystal_b(decision))
    assert len(points) == decision.n_kpoints
    lattice = decision.cell.lattice.matrix
    vacuum = vacuum_axes(decision.cell)
    periodic = [i for i, axis in enumerate(LATTICE_AXES) if axis not in vacuum]
    along_periodic = np.linalg.qr(lattice[periodic].T)[0]
    steps = np.diff(points, axis=0) @ _reciprocal(lattice) @ along_periodic
    lengths = np.linalg.norm(steps, axis=1)
    assert lengths[~jumps].max() <= decision.k_path_distance * (1 + 1e-9)
    alat = np.linalg.norm(lattice[0])
    in_alat = points @ _reciprocal(lattice) / (2 * np.pi / alat)
    assert (np.sum(np.diff(in_alat, axis=0) ** 2, axis=1) >= 1e-8).all()
    assert not any(np.allclose(points[i], points[i - 2]) for i in range(2, len(points)))


def test_a_wires_zone_edge_is_half_a_period_away() -> None:
    """Z of the carbon chain (C-C 1.28 A) lies pi / 1.28 A^-1 along it."""
    decision = _decision(carbon_chain())

    lattice = decision.cell.lattice.matrix
    along = lattice[2] / np.linalg.norm(lattice[2])
    z = _cartesian(decision, _labelled(decision, "Z"))
    assert math.isclose(z @ along, math.pi / 1.28)
