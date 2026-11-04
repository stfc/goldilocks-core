"""Spin polarization on the heuristic is_magnetic tier (#142).

Without mMACE -- the PyPI wheel and the Docker image ship none, and an
ML-enabled server falls back here too -- ``is_magnetic`` comes from
``analysis/local_moments.py``. These tests run on that tier: the isolated
asset root of every test leaves the ML classifier unset.

The old tier counted d electrons as group minus a guessed oxidation state
for every transition metal: fcc Ni became Ni0 d10 (no moment), FePt and FeCo
had no guess (undecidable, then non-magnetic), and metallic TiN and WC
became Ti3+ d1 and W4+ d2. Any lanthanide or actinide meant magnetic, so f0 ThO2 and
alpha-U were seeded, and no p-block system was ever magnetic, so solid O2
and isolated C atoms were not. An undecidable structure ran non-magnetic.

A spin-polarized SCF can quench a seeded moment; nspin=1 can never find
one. pw.x reference (SCARF, QE 7.5): the heuristic fcc Ni deck without
nspin (MC3D mc3d-4988) is 51.76 meV/atom above the nspin=2 deck on the
same 476 k-points and has none of its 0.69 uB/cell moment, while TiN's
5 uB seed (mc3d-48891) quenches to 0.00 uB, 1 uRy apart, at 1.87x the wall
time.

Cells are built in code from the e2e run's MC3D/MC2D/Materials Project
structures.
"""

from __future__ import annotations

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.advisors.magnetic_config import magnetic_cell
from goldilocks_core.analysis.is_magnetic import is_magnetic


def _cubic(spacegroup: str, a: float, species: list[str], coords) -> Structure:
    return Structure.from_spacegroup(spacegroup, Lattice.cubic(a), species, coords)


_SPIN_POLARIZED = {
    "fcc-Ni": _cubic("Fm-3m", 3.524, ["Ni"], [[0, 0, 0]]),
    "L1_0-FePt": Structure(
        Lattice.tetragonal(2.6855, 3.721),
        ["Fe", "Pt"],
        [[0, 0, 0], [0.5, 0.5, 0.5]],
    ),
    "B2-FeCo": _cubic("Pm-3m", 2.857, ["Fe", "Co"], [[0, 0, 0], [0.5, 0.5, 0.5]]),
    "bcc-Cr": _cubic("Im-3m", 2.884, ["Cr"], [[0, 0, 0]]),
    "GdI2-monolayer": Structure(
        Lattice.hexagonal(4.3566, 19.9386),
        ["Gd", "I", "I"],
        [[0, 0, 0.5], [1 / 3, 2 / 3, 0.5993], [1 / 3, 2 / 3, 0.4007]],
    ),
    "rock-salt-UN": _cubic("Fm-3m", 4.877, ["U", "N"], [[0, 0, 0], [0.5, 0.5, 0.5]]),
    "solid-O2": Structure(
        Lattice.from_parameters(3.5119, 3.5119, 4.2801, 67.257, 112.743, 115.955),
        ["O", "O"],
        [[0.9105, 0.0895, 0.8544], [0.0895, 0.9105, 0.1456]],
    ),
    "C-atoms-in-a-box": Structure(
        Lattice.hexagonal(10.56, 17.18),
        ["C", "C"],
        [[1 / 3, 2 / 3, 0.25], [2 / 3, 1 / 3, 0.75]],
    ),
}

_NOT_SPIN_POLARIZED = {
    "fcc-Cu": _cubic("Fm-3m", 3.615, ["Cu"], [[0, 0, 0]]),
    "rock-salt-TiN": _cubic("Fm-3m", 4.241, ["Ti", "N"], [[0, 0, 0], [0.5, 0.5, 0.5]]),
    "hexagonal-WC": Structure(
        Lattice.hexagonal(2.906, 2.837),
        ["W", "C"],
        [[0, 0, 0], [1 / 3, 2 / 3, 0.5]],
    ),
    "fluorite-ThO2": _cubic(
        "Fm-3m", 5.597, ["Th", "O"], [[0, 0, 0], [0.25, 0.25, 0.25]]
    ),
    "alpha-U": Structure.from_spacegroup(
        "Cmcm", Lattice.orthorhombic(2.854, 5.869, 4.955), ["U"], [[0, 0.1025, 0.25]]
    ),
    "rock-salt-NaCl": _cubic(
        "Fm-3m", 5.640, ["Na", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]]
    ),
    "bcc-Na": _cubic("Im-3m", 4.235, ["Na"], [[0, 0, 0]]),
}


@pytest.mark.parametrize("name", sorted(_SPIN_POLARIZED))
def test_open_shell_metals_ions_and_radicals_run_spin_polarized(name: str) -> None:
    """Itinerant 3d magnets (Ni, FePt, FeCo, Cr), a 4f7 ion without an
    oxidation-state guess (GdI2), an actinide compound (UN, an
    antiferromagnet), triplet O2 molecules and isolated C atoms."""
    structure = _SPIN_POLARIZED[name]
    magnetism = is_magnetic(structure)

    cell = magnetic_cell(structure, magnetism)

    assert magnetism.source == "heuristic"
    assert magnetism.value == "magnetic"
    assert cell.value.spin_polarized is True
    assert cell.value.warnings == ()


@pytest.mark.parametrize("name", sorted(_NOT_SPIN_POLARIZED))
def test_closed_shell_and_itinerant_non_magnets_run_spin_unpolarized(
    name: str,
) -> None:
    """Cu, metallic TiN and WC, f0 Th4+, alpha-U's itinerant 5f band, and
    bonded s-p systems."""
    structure = _NOT_SPIN_POLARIZED[name]
    magnetism = is_magnetic(structure)

    cell = magnetic_cell(structure, magnetism)

    assert magnetism.source == "heuristic"
    assert magnetism.value == "non_magnetic"
    assert cell.value.spin_polarized is False
    assert cell.value.warnings == ()


def test_undecidable_magnetism_runs_spin_polarized_under_a_warning() -> None:
    """US is a ferromagnet (Tc 177 K). pymatgen guesses no oxidation states
    for it and U's common +6 leaves 5f empty, which says nothing about a
    compound outside its common states: the tier cannot decide, and the
    run defaults to the setting that can still find a moment."""
    uranium_sulfide = _cubic("Fm-3m", 5.489, ["U", "S"], [[0, 0, 0], [0.5, 0.5, 0.5]])
    magnetism = is_magnetic(uranium_sulfide)

    cell = magnetic_cell(uranium_sulfide, magnetism)

    assert magnetism.status == "unavailable"
    assert cell.value.spin_polarized is True
    assert [warning.code for warning in cell.value.warnings] == [
        "magnetic.magnetism_unknown_defaulted_spin_polarized"
    ]
    assert magnetism.reason in cell.value.warnings[0].message
