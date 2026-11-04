"""Dimensionality ranks of real crystals (#125).

``geometry()`` ranks a bond graph with Larsen's algorithm, so the rank is
only as good as the bonds. Covalent-scale cutoffs alone (pymatgen's JmolNN)
leave ionic, metallic and long covalent contacts unbonded: rock-salt NaCl,
bcc Na and phosphorene ranked 'molecule', MgB2 and LiCoO2 '2d'. Every cell
here is a real crystal, built from its space group and published lattice
constants or taken from an MC2D/MC3D CIF.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from pymatgen.core import Lattice, Structure
from support import (
    carbon_dioxide,
    carbon_pair_in_a_box,
    graphite,
    molybdenum_disulfide,
    phosphorene,
    sodium_chloride,
)

from goldilocks_core.analysis.geometry import geometry


def caesium_chloride() -> Structure:
    """CsCl, Pm-3m, a = 4.12 A: Cs-Cl 3.57 A."""
    return Structure.from_spacegroup(
        "Pm-3m", Lattice.cubic(4.12), ["Cs", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]]
    )


def bcc_sodium() -> Structure:
    """Na, Im-3m, a = 4.29 A: Na-Na 3.72 A."""
    return Structure.from_spacegroup("Im-3m", Lattice.cubic(4.29), ["Na"], [[0, 0, 0]])


def bcc_caesium() -> Structure:
    """Cs, Im-3m, a = 6.14 A: Cs-Cs 5.32 A, the longest nearest-neighbour
    contact of the elemental solids."""
    return Structure.from_spacegroup("Im-3m", Lattice.cubic(6.14), ["Cs"], [[0, 0, 0]])


def lithium_hydride() -> Structure:
    """Rock salt, Fm-3m, a = 4.08 A: Li-H 2.04 A."""
    return Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(4.08), ["Li", "H"], [[0, 0, 0], [0.5, 0.5, 0.5]]
    )


def calcium_fluoride() -> Structure:
    """Fluorite, Fm-3m, a = 5.46 A: Ca-F 2.36 A."""
    return Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(5.46), ["Ca", "F"], [[0, 0, 0], [0.25, 0.25, 0.25]]
    )


def magnesium_diboride() -> Structure:
    """MgB2, P6/mmm, a = 3.086 A, c = 3.524 A: graphitic B sheets held
    together by Mg at 2.50 A from B."""
    return Structure.from_spacegroup(
        "P6/mmm",
        Lattice.hexagonal(3.086, 3.524),
        ["Mg", "B"],
        [[0, 0, 0], [1 / 3, 2 / 3, 0.5]],
    )


def lithium_cobalt_oxide() -> Structure:
    """LiCoO2, R-3m, a = 2.816 A, c = 14.05 A, z_O = 0.2604 with Co at the
    origin: CoO2 sheets (Co-O 1.92 A) held together by Li at 2.09 A from O."""
    return Structure.from_spacegroup(
        "R-3m",
        Lattice.hexagonal(2.816, 14.05),
        ["Li", "Co", "O"],
        [[0, 0, 0.5], [0, 0, 0], [0, 0, 0.2604]],
    )


def bismuth_selenide() -> Structure:
    """Bi2Se3, R-3m, a = 4.14 A, c = 28.64 A: Se-Bi-Se-Bi-Se quintuple
    layers stacked across a van der Waals gap."""
    return Structure.from_spacegroup(
        "R-3m",
        Lattice.hexagonal(4.14, 28.64),
        ["Bi", "Se", "Se"],
        [[0, 0, 0.4008], [0, 0, 0], [0, 0, 0.2117]],
    )


def _named(build: Callable[[], Structure]) -> str:
    return build.__name__


@pytest.mark.parametrize(
    "build",
    [
        sodium_chloride,
        caesium_chloride,
        bcc_sodium,
        bcc_caesium,
        lithium_hydride,
        calcium_fluoride,
        magnesium_diboride,
        lithium_cobalt_oxide,
    ],
    ids=_named,
)
def test_ionic_and_metallic_solids_rank_3d(build: Callable[[], Structure]) -> None:
    """In each solid some atom's shortest contact is ionic or metallic and
    lies beyond JmolNN's covalent cutoff for that pair: Na-Cl 2.82 A against
    2.41 A, Na-Na 3.72 A against 2.39 A, Mg-B 2.51 A against 2.38 A. bcc Cs's
    5.32 A contact must lie inside the 6 A nearest-shell search."""
    state = geometry(build())

    assert state.ok
    assert state.value.dimensionality == "3d"
    assert state.value.low_dimensional is False


@pytest.mark.parametrize(
    "build",
    [graphite, molybdenum_disulfide, bismuth_selenide, phosphorene],
    ids=_named,
)
def test_layered_crystals_and_monolayers_rank_2d(
    build: Callable[[], Structure],
) -> None:
    """The van der Waals gap stays unbonded: each atom's nearest shell lies
    inside its own layer. Phosphorene's P-P bonds (2.22-2.26 A) are longer
    than JmolNN's 1.95 A cutoff."""
    state = geometry(build())

    assert state.ok
    assert state.value.dimensionality == "2d"
    assert state.value.low_dimensional is True


def test_molecular_crystal_ranks_molecule() -> None:
    """Each atom's nearest shell lies inside its own CO2 molecule."""
    state = geometry(carbon_dioxide())

    assert state.ok
    assert state.value.dimensionality == "molecule"


@pytest.mark.parametrize("a", [4.90, 4.95, 4.992, 5.00, 5.05, 5.10])
def test_a_percent_level_strain_keeps_fcc_lead_3d(a: float) -> None:
    """fcc Pb at its MC3D lattice (a = 4.92 A) and strained by a few
    percent. The Pb-Pb contact a/sqrt(2) crosses JmolNN's fixed cutoff
    between a = 4.992 and 4.995 A; the rank must not depend on it."""
    lead = Structure.from_spacegroup("Fm-3m", Lattice.cubic(a), ["Pb"], [[0, 0, 0]])

    state = geometry(lead)

    assert state.ok
    assert state.value.dimensionality == "3d"


def test_atoms_with_no_neighbour_in_range_stay_unbonded() -> None:
    """MC3D mc3d-6516's two C atoms are 10.5 A apart; no neighbour lies in
    any bonding range, so the cell ranks 'molecule' rather than failing."""
    state = geometry(carbon_pair_in_a_box())

    assert state.status == "resolved"
    assert state.value.dimensionality == "molecule"


def test_a_lone_atom_is_not_bonded_to_its_own_images() -> None:
    """A Xe atom in a 7 A cubic box: its images lie beyond the 6 A
    nearest-shell search, so it stays unbonded and ranks 'molecule'. A 10 A
    search (MinimumDistanceNN's default) would bond it to them and rank the
    box '3d'."""
    box = Structure(Lattice.cubic(7.0), ["Xe"], [[0, 0, 0]])

    state = geometry(box)

    assert state.ok
    assert state.value.dimensionality == "molecule"
