"""Boundary conditions and cell constraints of crystals, slabs and
isolated systems (#126, #132).

Martyna-Tuckerman (MT) replaces the periodic Hartree, local-potential and
Ewald terms with those of an isolated cluster, and pw.x then computes no
stress. It suits only a system with vacuum along all three lattice
vectors. The bond rank cannot tell a molecular crystal from a molecule in
a box: CO2 dry ice ranks 'molecule', and H2O ice and trigonal Te rank '1d',
yet each fills its cell. On SCARF, MT on the CO2 SCF deck shifted the total
energy by -3.1 Ry per cell and flipped the sign of the O forces.

The rank cannot tell a bulk layered crystal from a slab either: graphite
ranks '2d' like graphene. QE's 2D cell constraint (cell_dofree='2Dxy')
holds c and the z components of a and b fixed. On SCARF, graphite under it
stopped after one BFGS step with c unchanged and 16 kbar of stress along z
left; with 'all', c shrank by 7.9%.

Nor can it tell which slabs need a dipole correction (#160). QE allows one
only in a slab, with its discontinuity in the empty space (QE 7.3
PW/Doc/INPUT_PW.def:407-416), and a slab carries a dipole along its normal
only if no point operation reverses that normal: every monolayer of the
2026-10-19 batch has an inversion centre or a mirror in the sheet, while a
Janus MoSSe sheet has S on one side and Se on the other.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from pymatgen.core import Lattice, Structure
from support import (
    carbon_chain,
    carbon_dioxide,
    carbon_pair_in_a_box,
    graphene_monolayer,
    graphene_with_vacuum_along_x,
    graphite,
    janus_molybdenum_sulfide_selenide,
    molybdenum_disulfide,
    molybdenum_disulfide_monolayer,
    phosphorene,
    rhombohedral_bismuth_selenide,
    sodium_chloride,
    water_ice,
    with_vacuum_along,
    written_cell,
)

from goldilocks_core.advisors.boundary import BoundaryFacts, boundary
from goldilocks_core.advisors.convergence import convergence
from goldilocks_core.advisors.relax import RelaxOptions, relax_settings
from goldilocks_core.analysis.geometry import geometry
from goldilocks_core.analysis.symmetry import symmetry
from goldilocks_core.checks import check_all
from goldilocks_core.resolution import Blocked, Provenance, Resolved


def trigonal_tellurium() -> Structure:
    """Te, P3_121, a = 4.457 A, c = 5.929 A, x = 0.2636: helical chains
    (Te-Te 2.84 A) 3.49 A apart, ranked '1d'."""
    return Structure.from_spacegroup(
        "P3_121", Lattice.hexagonal(4.457, 5.929), ["Te"], [[0.2636, 0, 1 / 3]]
    )


def _named(build: Callable[[], Structure]) -> str:
    return build.__name__


def _boundary(structure: Structure):
    return boundary(geometry(structure), symmetry(structure))


@pytest.mark.parametrize(
    "build",
    [
        carbon_dioxide,
        water_ice,
        trigonal_tellurium,
        sodium_chloride,
        phosphorene,
        carbon_chain,
    ],
    ids=_named,
)
def test_a_cell_periodic_along_any_axis_is_not_treated_as_isolated(
    build: Callable[[], Structure],
) -> None:
    """Molecular crystals, a chain crystal, an ionic solid, a monolayer and
    a wire: each is periodic along at least one lattice vector, while MT is
    a correction for a molecule or cluster in a 3D supercell (QE 7.3
    PW/Doc/INPUT_PW.def:1593-1594)."""
    state = _boundary(build())

    assert state.ok
    assert state.value.isolation == "periodic"


def test_a_molecule_in_a_box_is_isolated() -> None:
    state = _boundary(carbon_pair_in_a_box())

    assert state.value.isolation == "isolated"


@pytest.mark.parametrize(
    ("build", "vacuum_axes"),
    [
        (carbon_dioxide, ()),
        (water_ice, ()),
        (trigonal_tellurium, ()),
        (sodium_chloride, ()),
        (phosphorene, ("c",)),
        (carbon_chain, ("a", "b")),
        (carbon_pair_in_a_box, ("a", "b", "c")),
    ],
    ids=lambda value: value.__name__ if callable(value) else None,
)
def test_vacuum_axes_are_the_lattice_vectors_with_an_empty_slab(
    build: Callable[[], Structure], vacuum_axes: tuple[str, ...]
) -> None:
    """Dense crystals leave no atom-free slab wider than 1.48 A (CO2) or
    2.82 A (NaCl); phosphorene has 20.07 A of vacuum along c."""
    assert geometry(build()).value.vacuum_axes == vacuum_axes


def test_the_carbon_box_vacuum_widths() -> None:
    """MC3D mc3d-6516: 6.1, 6.1 and 8.59 A between the two atoms' planes
    along a, b and c."""
    widths = geometry(carbon_pair_in_a_box()).value.vacuum_widths_angstrom

    assert widths == (6.1, 6.1, 8.59)


def _vc_relax(structure: Structure):
    return relax_settings(
        "vc-relax", convergence(nat=len(structure)), geometry=geometry(structure)
    )


@pytest.mark.parametrize(
    "build",
    [graphite, molybdenum_disulfide, rhombohedral_bismuth_selenide],
    ids=_named,
)
def test_vc_relax_of_a_bulk_layered_crystal_relaxes_the_whole_cell(
    build: Callable[[], Structure],
) -> None:
    """Each ranks '2d' but has no vacuum, so the stacking axis must relax
    too. Under '2Dxy' the rhombohedral Bi2Se3 cell, whose a and b point out
    of the xy plane, also distorted on SCARF: a and b shrank while c stayed
    fixed."""
    state = _vc_relax(build())

    assert state.ok
    assert state.value.cell_dofree == "all"
    assert state.value.warnings == ()


def test_vc_relax_of_a_monolayer_in_the_xy_plane_holds_its_vacuum_fixed() -> None:
    state = _vc_relax(graphene_monolayer())

    assert state.ok
    assert state.value.cell_dofree == "2Dxy"
    assert state.value.warnings == ()


def test_vc_relax_of_a_monolayer_with_its_vacuum_along_x_is_refused() -> None:
    """'2Dxy' would free the vacuum vector a and freeze c, which lies in the
    sheet."""
    state = _vc_relax(graphene_with_vacuum_along_x())

    assert isinstance(state, Blocked)
    assert "cell_dofree" in state.root_cause()
    assert "along a" in state.root_cause()


@pytest.mark.parametrize(
    "build",
    [graphite, molybdenum_disulfide, rhombohedral_bismuth_selenide],
    ids=_named,
)
def test_a_bulk_layered_crystal_gets_no_slab_advice(
    build: Callable[[], Structure],
) -> None:
    """#160: each ranks '2d' but has no vacuum: no dipole notice, plain
    mixing, since local-TF's stated rationale is a vacuum region, and no
    bottom layer to fix. On SCARF the two mixings gave the same energy and
    SCF iteration count for bulk graphite and MgB2, and with
    fix_bottom_layers=1 relax.in froze graphite's z = 1/4 sheet."""
    structure = build()

    assert _boundary(structure).value.warnings == ()
    state = convergence(nat=len(structure), geometry=geometry(structure))
    assert state.value.mixing_mode == "plain"
    report = check_all(
        relax=Resolved(RelaxOptions(fix_bottom_layers=1), Provenance(source="human")),
        magnetic=written_cell(structure),
    )
    (finding,) = report.blocking
    assert finding.code == "relax.fix_bottom_layers_needs_slab"


@pytest.mark.parametrize(
    "build", [molybdenum_disulfide_monolayer, graphene_monolayer], ids=_named
)
def test_a_symmetric_monolayer_gets_no_dipole_notice(
    build: Callable[[], Structure],
) -> None:
    """The MoS2 sheet's mirror through Mo and graphene's inversion centre
    cancel any dipole along c; both still mix with local-TF across their
    vacuum."""
    structure = build()

    assert _boundary(structure).value.warnings == ()
    state = convergence(nat=len(structure), geometry=geometry(structure))
    assert state.value.mixing_mode == "local-TF"


def test_a_janus_sheet_gets_a_dipole_correction_in_its_vacuum() -> None:
    """Janus MoSSe has S 1.55 A above Mo and Se 1.65 A below, so its vacuum
    in the 20 A cell runs from the S plane at z = 0.5775 to the Se plane at
    z = 1.4175: centred at 0.9975 and 0.84 of the cell wide. The sawtooth
    drops from emaxpos = 0.9475 over eopreg = 0.1, inside it."""
    state = _boundary(janus_molybdenum_sulfide_selenide())

    (warning,) = state.value.warnings
    assert warning.code == "boundary.dipole_correction_suggested"
    assert "edir = 3, emaxpos = 0.9475, eopreg = 0.1, eamp = 0" in warning.message
    assert "isolation='slab'" in warning.message


@pytest.mark.parametrize("c", [12.0, 15.0, 20.0])
def test_the_dipole_notice_offers_the_2d_truncation_only_where_check_accepts_it(
    c: float,
) -> None:
    """The 3.2 A Janus sheet needs vacuum 20 bohr (10.58 A) wider than itself
    for QE's 2D truncation, so a cell about 17 A high: in 12 and 15 A cells
    the notice suggests the dipole correction alone, as check() refuses
    isolation='slab' there."""
    sheet = janus_molybdenum_sulfide_selenide(c)

    (warning,) = _boundary(sheet).value.warnings
    report = check_all(
        boundary=Resolved(BoundaryFacts("slab"), Provenance(source="human")),
        magnetic=written_cell(sheet),
    )

    assert ("isolation='slab'" in warning.message) is report.ok
    assert report.ok is (c == 20.0)


@pytest.mark.parametrize(("axis", "edir"), [("a", 1), ("b", 2)])
def test_the_dipole_correction_follows_a_vacuum_along_a_or_b(
    axis: str, edir: int
) -> None:
    """The Janus sheet with its lattice vectors permuted so the vacuum vector
    is a or b: the correction runs along that axis, with the sawtooth at the
    same place in its vacuum as along c, and QE's 2D truncation, which needs
    the vacuum along c, is not offered."""
    state = _boundary(with_vacuum_along(janus_molybdenum_sulfide_selenide(), axis))

    (warning,) = state.value.warnings
    assert f"edir = {edir}, emaxpos = 0.9475, eopreg = 0.1, eamp = 0" in (
        warning.message
    )
    assert "isolation='slab'" not in warning.message
