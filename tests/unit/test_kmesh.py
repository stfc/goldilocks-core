"""The k-mesh ladder, checked on real materials -- ported from
goldilocks-data's own test_kmesh.py (v2 epic 6, #6). For a cell without
vacuum whose symmetry-coupled axes have equal reciprocal lengths, the rungs
(kindex, mesh and intervals) still match goldilocks-data's on the same
lattice; where the point group couples axes of different length, or of
lengths CIF noise has made unequal, core meshes them alike and its rungs
are numbered differently (#163). Core's rungs carry no symmetry-reduced
count (#155); test_advisors_n_irr_k.py checks the reduction. Every bulk
structure here is a real crystal: three built from their space group and
published lattice constants, two MC3D cells -- hexagonal Si exactly as
goldilocks-data's own SCF campaign ran it and triclinic TiNi -- and three
Materials Project cells as MP serves them: alpha-U, UN and a CeCoIn5
supercell. Synthetic lattices were tried first upstream and hid what a
real cell exposes: CIF noise and the slivers it leaves between change
points. The vacuum-axis tests (#159) use a graphene sheet, a carbon chain
and the isolated C pair of MC3D mc3d-6516 from ``tests/support.py``.
"""

from __future__ import annotations

import math
from dataclasses import astuple
from itertools import pairwise

import pytest
from pymatgen.core import Lattice, Structure
from support import (
    alpha_uranium,
    carbon_chain,
    carbon_pair_in_a_box,
    graphene_monolayer,
    graphene_with_vacuum_along_a,
    mc3d_67775_silicon,
    uranium_nitride,
)

from goldilocks_core.kmesh import (
    MIN_K_DISTANCE,
    KMeshEntry,
    build_gamma_kmesh_entries,
    k_distance_to_mesh,
)


def diamond_silicon() -> Structure:
    """Si, Fd-3m, a = 5.43 A. Cubic: 48 point-group operations, |b_i| all
    equal."""
    return Structure.from_spacegroup(
        "Fd-3m", Lattice.cubic(5.43), ["Si"], [[0.0, 0.0, 0.0]]
    )


def graphite() -> Structure:
    """Bernal graphite, C on the 2b and 2c sites of P6_3/mmc, a = 2.46 A,
    c = 6.71 A. Layered: |b_1| is 3.1x |b_3|. goldilocks-data's fixture
    places only the 2b site, a simple-hexagonal cell on the same lattice."""
    return Structure.from_spacegroup(
        "P6_3/mmc",
        Lattice.hexagonal(2.46, 6.71),
        ["C", "C"],
        [[0.0, 0.0, 0.25], [1 / 3, 2 / 3, 0.25]],
    )


def rutile() -> Structure:
    """TiO2, P4_2/mnm, a = 4.594 A, c = 2.959 A. Tetragonal: the short axis
    is c."""
    return Structure.from_spacegroup(
        "P4_2/mnm",
        Lattice.tetragonal(4.594, 2.959),
        ["Ti", "O"],
        [[0.0, 0.0, 0.0], [0.305, 0.305, 0.0]],
    )


def mc3d_31340_tini() -> Structure:
    """Triclinic TiNi, MC3D 31340 (P-1). Its three reciprocal axes all
    differ, and its Laue group, -1, maps every mesh onto itself."""
    return Structure(
        Lattice.from_parameters(
            2.686185331044557,
            6.97034299971133,
            4.530142290302962,
            110.41779674117039,
            90.51114535957441,
            100.25528065043186,
        ),
        ["Ti", "Ti", "Ti", "Ni", "Ni", "Ni"],
        [
            [0.1585096067374422, 0.32623940974867155, 0.7676125146233795],
            [0.8414903932281635, 0.6737605902653331, 0.23238748538371365],
            [0.0, 0.0, 0.0],
            [0.3408662647191799, 0.6631612739114513, 0.7064985079217144],
            [0.6591337352464222, 0.336838726102553, 0.293501492085372],
            [0.4999999999814244, 0.9999999999993829, 0.5000000000107764],
        ],
    )


def doubled_cecoin5() -> Structure:
    """CeCoIn5 (P4/mmm), Materials Project mp-19961, doubled along a. MP's
    a and b differ in the seventh significant figure (4.61176646 against
    4.61176336 A); doubling a leaves no operation that mixes a and b, and
    makes |b_2| twice |b_1| up to that noise."""
    cecoin5 = Structure(
        Lattice.from_parameters(4.61176646, 4.61176336, 7.53603488, 90, 90, 90),
        ["Ce", "In", "In", "In", "In", "In", "Co"],
        [
            [0.0, 0.0, 0.0],
            [0.5, 0.5, 0.0],
            [0.5, 0.0, 0.68994532],
            [0.0, 0.5, 0.31005468],
            [0.5, 0.0, 0.31005468],
            [0.0, 0.5, 0.68994532],
            [0.0, 0.0, 0.5],
        ],
    )
    return cecoin5.make_supercell([2, 1, 1], in_place=False)


def test_gamma_kmesh_entries_start_with_gamma_mesh() -> None:
    entries = build_gamma_kmesh_entries(diamond_silicon(), min_k_distance=0.25)

    assert entries[0].kindex == 1
    assert entries[0].mesh == (1, 1, 1)
    assert entries[1].kindex == 2
    assert entries[0].k_pra == 8.0  # 8 sites in the conventional cell x 1


def test_only_the_gamma_rung_is_open_above() -> None:
    """Rung 1, the Gamma-only mesh, holds for every k-distance above the
    largest change point, so its interval has no upper bound. The bound is
    None, not a float: strict JSON has no infinity (#137). Every other rung
    is bounded on both sides."""
    silicon = diamond_silicon()

    entries = build_gamma_kmesh_entries(silicon, min_k_distance=0.2)

    # The largest change point is |b| / 1, |b| being equal on the three
    # axes of the cubic cell.
    assert entries[0].k_distance_interval == (
        round(silicon.lattice.reciprocal_lattice.a, 8),
        None,
    )
    for entry in entries[1:]:
        low, high = entry.k_distance_interval
        assert high is not None
        assert math.isfinite(low) and math.isfinite(high), entry


def test_k_distance_to_mesh_uses_solid_state_reciprocal_lengths() -> None:
    # Rutile: |b| = (1.3677, 1.3677, 2.1234) 1/A on the 2*pi reciprocal
    # lattice. ceil(|b_i| / 0.7) is (2, 2, 4). Reading the crystallographic
    # lengths instead -- the ones without 2*pi -- would give (1, 1, 1).
    assert k_distance_to_mesh(rutile(), 0.7) == (2, 2, 4)


def test_ladder_is_gap_free_down_to_the_floor() -> None:
    # Graphite is layered, so |b_1| = |b_2| = 2.949 against |b_3| = 0.936.
    # Under a per-axis k-point cap the two long axes would run out of
    # change points while the short one was still stepping, leaving holes.
    # A k-distance floor stops every axis at the same place, so the ladder
    # is gap-free by construction.
    meshes = [
        entry.mesh
        for entry in build_gamma_kmesh_entries(graphite(), min_k_distance=0.1)
    ]

    assert len(meshes) > 1
    for before, after in pairwise(meshes):
        steps = [now - previous for previous, now in zip(before, after, strict=True)]
        assert max(steps) == 1, f"{before} -> {after} skips a mesh"
        assert min(steps) >= 0, f"{before} -> {after} is not monotonic"


def _assert_distinct_and_contiguous(entries: list[KMeshEntry]) -> None:
    """Every rung names its own mesh, and each rung's interval starts where
    the next denser rung's ends, so the intervals tile the k-distance axis
    from the floor up with no gap."""
    assert len({entry.mesh for entry in entries}) == len(entries)
    for coarser, finer in pairwise(entries):
        assert finer.k_distance_interval[1] == coarser.k_distance_interval[0], (
            coarser,
            finer,
        )


def test_near_equal_coupled_axes_step_together() -> None:
    """MC3D 67775, hexagonal Si. Its a and b are equal only to about 11
    decimal places, so |b_1| and |b_2| gave two change points a hair apart,
    and the sliver of k-distance between them gave the mesh of the next
    interval again; the ladder dropped that interval and left a gap in the
    k-distance axis (#163). The six-fold axis mixes a and b, so both are
    meshed from the longer |b_i| and step at one change point: a and b
    always have the same count, and the intervals tile.

    Exactly equal axes never did this -- their change points coincide and
    collapse in the candidate set. It took a near miss, which is why this
    needs a real cell: 36 of the 20,826 MC3D structures in goldilocks-data's
    campaign hit it, and no idealised lattice does."""
    entries = build_gamma_kmesh_entries(mc3d_67775_silicon())

    _assert_distinct_and_contiguous(entries)
    assert all(entry.mesh[0] == entry.mesh[1] for entry in entries)


def test_a_sliver_between_uncoupled_axes_joins_the_rung_above() -> None:
    """Doubled CeCoIn5: no operation mixes a and b, but |b_2| is twice
    |b_1| up to CIF noise, so |b_1| / n and |b_2| / 2n are change points
    closer than the mesh's 5-decimal rounding resolves. The interval between
    them gives the mesh of the interval above it, and joins that rung,
    which now ends at the lower change point: rung 3, (1, 2, 2), runs from
    |b_1| = 0.68121243 A^-1 (|b_2| / 2 = 0.68121289) to |b_3| = 0.83375215.
    The ladder used to drop such an interval, leaving a gap in the
    k-distance axis that no rung covered (#163)."""
    entries = build_gamma_kmesh_entries(doubled_cecoin5())

    _assert_distinct_and_contiguous(entries)
    assert len(entries) == 87
    assert entries[2].mesh == (1, 2, 2)
    assert entries[2].k_distance_interval == (0.68121243, 0.83375215)


def test_alpha_uranium_meshes_its_coupled_axes_alike() -> None:
    """#163: alpha-U as Materials Project serves it (mp-44), the reduced
    primitive cell, whose point group mixes a and b although |b_1| = 2.509
    and |b_2| = 2.148 A^-1. Meshing each axis from its own length gave
    11x10x6 at QRF95's 0.2378 A^-1, which the point group does not map
    onto itself: pw.x ran it with 224 irreducible k-points against 144 for
    the denser 11x11x6. a and b are now both meshed from |b_1|, so every
    rung has n1 = n2, and the ladder has 126 rungs, not 197."""
    structure = alpha_uranium()

    entries = build_gamma_kmesh_entries(structure)

    assert k_distance_to_mesh(structure, 0.237770676612854) == (11, 11, 6)
    assert len(entries) == 126
    assert all(entry.mesh[0] == entry.mesh[1] for entry in entries)
    assert [(entry.mesh, entry.k_distance_interval) for entry in entries[:8]] == [
        ((1, 1, 1), (2.50923743, None)),
        ((2, 2, 1), (1.29547372, 2.50923743)),
        ((2, 2, 2), (1.25461872, 1.29547372)),
        ((3, 3, 2), (0.83641248, 1.25461872)),
        ((4, 4, 2), (0.64773686, 0.83641248)),
        ((4, 4, 3), (0.62730936, 0.64773686)),
        ((5, 5, 3), (0.50184749, 0.62730936)),
        ((6, 6, 3), (0.43182457, 0.50184749)),
    ]


def test_coupled_axes_read_the_k_line_density_at_their_longest_length() -> None:
    """#163: alpha-U's coupled a and b both read the k-line density at a's
    crystallographic reciprocal length |a*|, the longer, so the 11x11x6
    rung's interval is a's [10.5, 11.5] / |a*| cut by c's [5.5, 6.5] / |c*|.
    Read at its own shorter |b*|, b's interval [10.5, 11.5] / |b*| would
    miss a's, and the rung would have no k-line density."""
    structure = alpha_uranium()
    a_star, b_star, c_star = structure.lattice.reciprocal_lattice_crystallographic.abc

    rung = next(
        entry
        for entry in build_gamma_kmesh_entries(structure)
        if entry.mesh == (11, 11, 6)
    )

    assert 10.5 / b_star > 11.5 / a_star
    assert rung.k_line_density_interval == pytest.approx((5.5 / c_star, 11.5 / a_star))


def test_cif_noise_between_equivalent_axes_leaves_no_sliver_rung() -> None:
    """#163: UN as Materials Project serves it (mp-1865), the fcc primitive
    cell, whose three reciprocal lengths differ in the seventh significant
    figure. Each axis used to step at its own change point, which put 19
    slivers such as 32x33x32 (an interval 1e-8 A^-1 wide, 8721 irreducible
    k-points against 897 and 969 for its neighbours) on a 93-rung ladder and
    renumbered every rung above 32. The cubic point group mixes all three
    axes, so all are meshed from the longest |b_i|: rung n is n x n x n
    between that length's change points n and n - 1."""
    longest = max(uranium_nitride().lattice.reciprocal_lattice.abc)

    entries = build_gamma_kmesh_entries(uranium_nitride())

    assert [astuple(entry)[:3] for entry in entries] == [
        (
            n,
            (n, n, n),
            (round(longest / n, 8), round(longest / (n - 1), 8) if n > 1 else None),
        )
        for n in range(1, 75)
    ]
    assert entries[32].k_distance_interval == (0.06761454, 0.0697275)


def test_lowering_the_floor_only_extends_the_ladder() -> None:
    # kindex is recorded in campaign snapshots and published records, so a
    # lower floor must never renumber a rung that already existed.
    structure = graphite()
    coarse = [
        entry.mesh for entry in build_gamma_kmesh_entries(structure, min_k_distance=0.2)
    ]
    fine = [
        entry.mesh for entry in build_gamma_kmesh_entries(structure, min_k_distance=0.1)
    ]

    assert len(fine) > len(coarse)
    assert fine[: len(coarse)] == coarse


def test_ladder_stops_at_the_resolution_floor() -> None:
    # The floor caps the densest mesh at ceil(|b_i| / min_k_distance) per
    # axis, independent of any k-point count. Taking the floor as |b| / 8
    # of a cubic cell makes that exactly (8, 8, 8) with no float noise.
    silicon = diamond_silicon()
    entries = build_gamma_kmesh_entries(
        silicon, min_k_distance=silicon.lattice.reciprocal_lattice.a / 8
    )

    assert entries[-1].mesh == (8, 8, 8)


def test_kindex_is_contiguous_and_one_based() -> None:
    entries = build_gamma_kmesh_entries(mc3d_67775_silicon())

    assert [entry.kindex for entry in entries] == list(range(1, len(entries) + 1))


_TINI_LADDER = (
    # kindex, mesh, k_distance_interval, k_line_density_interval, k_pra
    (1, (1, 1, 1), (2.38413115, None), (3.20461063, 3.95312898), 6.0),
    (2, (2, 1, 1), (1.48436263, 2.38413115), (3.95312898, 6.349377), 12.0),
    (3, (2, 1, 2), (1.19206558, 1.48436263), (6.349377, 6.5885483), 24.0),
    (4, (3, 1, 2), (0.98033522, 1.19206558), (6.5885483, 9.22396762), 36.0),
    (5, (3, 2, 2), (0.79471038, 0.98033522), None, 72.0),
    (6, (4, 2, 2), (0.74218132, 0.79471038), (9.61383189, 10.582295), 96.0),
    (7, (4, 2, 3), (0.59603279, 0.74218132), (10.582295, 11.85938694), 144.0),
    (8, (5, 2, 3), (0.49478754, 0.59603279), (11.85938694, 14.49480626), 180.0),
    (9, (5, 2, 4), (0.49016761, 0.49478754), None, 240.0),
    (10, (5, 3, 4), (0.47682623, 0.49016761), None, 360.0),
    (11, (6, 3, 4), (0.39735519, 0.47682623), (16.02305315, 17.13022558), 432.0),
    (12, (7, 3, 4), (0.37109066, 0.39735519), (17.13022558, 19.048131), 504.0),
    (13, (7, 3, 5), (0.34059016, 0.37109066), (19.048131, 19.7656449), 630.0),
    (14, (8, 3, 5), (0.32677841, 0.34059016), (19.7656449, 22.40106422), 720.0),
    (15, (8, 4, 5), (0.29801639, 0.32677841), None, 960.0),
    (16, (9, 4, 5), (0.29687253, 0.29801639), (22.43227441, 23.28104901), 1080.0),
    (17, (9, 4, 6), (0.26490346, 0.29687253), (23.28104901, 25.03648354), 1296.0),
    (18, (10, 4, 6), (0.24739377, 0.26490346), (25.03648354, 27.51396701), 1440.0),
    (19, (10, 4, 7), (0.2450838, 0.24739377), (27.51396701, 27.67190286), 1680.0),
    (20, (10, 5, 7), (0.23841312, 0.2450838), None, 2100.0),
    (21, (11, 5, 7), (0.2167392, 0.23841312), (28.84149566, 30.30732218), 2310.0),
    (22, (12, 5, 7), (0.2120518, 0.2167392), (30.30732218, 31.74688501), 2520.0),
)
_GRAPHITE_LADDER = (
    # kindex, mesh, k_distance_interval, k_line_density_interval, k_pra
    (1, (1, 1, 1), (2.94926726, None), None, 4.0),
    (2, (2, 2, 1), (1.47463363, 2.94926726), (3.355, 5.32605623), 16.0),
    (3, (3, 3, 1), (0.98308909, 1.47463363), (5.32605623, 7.45647873), 36.0),
    (4, (4, 4, 1), (0.93639125, 0.98308909), (7.45647873, 9.58690122), 64.0),
    (5, (4, 4, 2), (0.73731681, 0.93639125), None, 128.0),
    (6, (5, 5, 2), (0.58985345, 0.73731681), (10.065, 11.71732371), 200.0),
    (7, (6, 6, 2), (0.49154454, 0.58985345), (11.71732371, 13.84774621), 288.0),
    (8, (7, 7, 2), (0.46819563, 0.49154454), (13.84774621, 15.9781687), 392.0),
    (9, (7, 7, 3), (0.42132389, 0.46819563), None, 588.0),
    (10, (8, 8, 3), (0.36865841, 0.42132389), (16.775, 18.10859119), 768.0),
    (11, (9, 9, 3), (0.32769636, 0.36865841), (18.10859119, 20.23901369), 972.0),
    (12, (10, 10, 3), (0.31213042, 0.32769636), (20.23901369, 22.36943618), 1200.0),
    (13, (10, 10, 4), (0.29492673, 0.31213042), None, 1600.0),
    (14, (11, 11, 4), (0.26811521, 0.29492673), (23.485, 24.49985867), 1936.0),
    (15, (12, 12, 4), (0.24577227, 0.26811521), (24.49985867, 26.63028117), 2304.0),
    (16, (13, 13, 4), (0.23409781, 0.24577227), (26.63028117, 28.76070366), 2704.0),
    (17, (13, 13, 5), (0.22686671, 0.23409781), None, 3380.0),
    (18, (14, 14, 5), (0.21066195, 0.22686671), (30.195, 30.89112615), 3920.0),
)
_DIAMOND_SILICON_LADDER = (
    # kindex, mesh, k_distance_interval, k_line_density_interval, k_pra
    (1, (1, 1, 1), (1.15712437, None), (2.715, 8.145), 8.0),
    (2, (2, 2, 2), (0.57856218, 1.15712437), (8.145, 13.575), 64.0),
    (3, (3, 3, 3), (0.38570812, 0.57856218), (13.575, 19.005), 216.0),
    (4, (4, 4, 4), (0.28928109, 0.38570812), (19.005, 24.435), 512.0),
    (5, (5, 5, 5), (0.23142487, 0.28928109), (24.435, 29.865), 1000.0),
)


@pytest.mark.parametrize(
    ("structure", "reference"),
    [
        (mc3d_31340_tini(), _TINI_LADDER),
        (graphite(), _GRAPHITE_LADDER),
        (diamond_silicon(), _DIAMOND_SILICON_LADDER),
    ],
    ids=["triclinic TiNi", "hexagonal graphite", "cubic silicon"],
)
def test_ladder_matches_its_stored_reference(
    structure: Structure, reference: tuple[tuple[object, ...], ...]
) -> None:
    """Every field of every rung down to a 0.2 A^-1 floor, as the ladder
    stood at d254510 apart from rung 1's open upper bound, now None
    instead of inf (#137). The axes each point group mixes have equal
    reciprocal lengths here, so meshing them alike (#163) changes nothing.
    ``kindex`` is recorded in published records, so any change here
    renumbers them. The k-line-density bounds are stored to 8 decimals;
    every other value is exact."""
    entries = build_gamma_kmesh_entries(structure, min_k_distance=0.2)

    assert [astuple(entry) for entry in entries] == [
        (kindex, mesh, k_distance, pytest.approx(k_line_density, abs=1e-8), k_pra)
        for kindex, mesh, k_distance, k_line_density, k_pra in reference
    ]


@pytest.mark.parametrize("k_distance", [0.05, 0.1, 0.2, 0.3])
@pytest.mark.parametrize(
    ("structure", "vacuum"),
    [
        (graphene_monolayer(c=15.0), {2}),
        (graphene_with_vacuum_along_a(), {0}),
        (carbon_chain(), {0, 1}),
    ],
    ids=["slab, vacuum along c", "slab, vacuum along a", "wire"],
)
def test_a_vacuum_axis_gets_one_division_at_any_k_distance(
    structure: Structure, vacuum: set[int], k_distance: float
) -> None:
    """A vacuum axis has no dispersion to sample, whatever its length. The
    old ceil(|b_i| / k_distance) on every axis gave the graphene sheet in a
    15 A cell kz = 3 at 0.2 A^-1 (#159); the periodic axes keep that
    formula."""
    lengths = structure.lattice.reciprocal_lattice.abc

    assert k_distance_to_mesh(structure, k_distance) == tuple(
        1 if axis in vacuum else math.ceil(round(length / k_distance, 5))
        for axis, length in enumerate(lengths)
    )


def test_a_slab_ladder_steps_its_periodic_axes_alone() -> None:
    """Only graphene's in-plane axes give change points, so its rungs are
    (n, n, 1) and each interval runs between consecutive |b_1| / n: no
    quotient of the vacuum axis splits a rung or renumbers the ladder
    (#159). The k-line density covers the in-plane axes alone."""
    slab = graphene_monolayer(c=15.0)
    in_plane = slab.lattice.reciprocal_lattice.a
    line = slab.lattice.reciprocal_lattice_crystallographic.a
    counts = range(1, math.floor(in_plane / MIN_K_DISTANCE) + 1)

    entries = build_gamma_kmesh_entries(slab)

    assert [astuple(entry) for entry in entries] == [
        (
            n,
            (n, n, 1),
            (round(in_plane / n, 8), round(in_plane / (n - 1), 8) if n > 1 else None),
            pytest.approx(((n - 0.5) / line, (n + 0.5) / line)),
            2.0 * n * n,
        )
        for n in counts
    ]


def test_a_cell_with_vacuum_along_every_axis_has_only_the_gamma_rung() -> None:
    """The isolated C pair of MC3D mc3d-6516 ran on a 3x3x2 mesh (#159).
    With no periodic axis there is no change point, every k-distance gives
    the Gamma-only mesh, and its rung's interval is open above: None, never
    inf (#137). No axis is left for a k-line density."""
    box = carbon_pair_in_a_box()

    assert {k_distance_to_mesh(box, k) for k in (0.05, 0.1, 0.2, 0.3)} == {(1, 1, 1)}
    assert build_gamma_kmesh_entries(box) == [
        KMeshEntry(
            kindex=1,
            mesh=(1, 1, 1),
            k_distance_interval=(0.0, None),
            k_line_density_interval=None,
            k_pra=2.0,
        )
    ]
