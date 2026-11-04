"""pw.x's dense FFT grid against ph.x's test when a cell is strained (#215).

A vc-relax keeps a cell's rotations but changes its lengths, and its final
scf rebuilds pw.x's grid for the relaxed cell. The strains here keep every
rotation pw.x finds: isotropic ones of +-0.5, 1, 2 and 3%, and eight random
ones each of 1, 2 and 3%, averaged over the point group so that each
rotation maps the strained lattice onto itself. A slab is strained in its
plane only, as cell_dofree='2Dxy' relaxes it. The cells come from
``tests/support.py``, each at the ecutrho of its default pseudopotentials.
"""

from __future__ import annotations

import numpy as np
import pytest
from support import (
    ISOTROPIC_STRAINS,
    graphite,
    molybdenum_disulfide_monolayer,
    strained,
    symmetric_strains,
    written_alpha_uranium,
    written_bcc_iron,
    written_boron_nitride_monolayer,
    written_gallium_arsenide,
    written_lanthanum_cuprate,
    written_silicon,
    written_sodium_chloride,
)

from goldilocks_core.pw_fft import (
    dense_fft_grid,
    fragile_axis_pairs,
    grid_is_compatible,
    ph_fft_grid,
)
from goldilocks_core.pw_symmetry import pw_rotations

pytestmark = pytest.mark.physics


_NOT_FRAGILE = [
    (written_silicon, 192.0),
    (written_gallium_arsenide, 384.0),
    (written_sodium_chloride, 384.0),
    (written_bcc_iron, 424.0),
    (graphite, 360.0),
    (written_boron_nitride_monolayer, 384.0),
    (molybdenum_disulfide_monolayer, 368.0),
]
_FRAGILE = [(written_alpha_uranium, 480.0), (written_lanthanum_cuprate, 720.0)]


def _name(value: object) -> str | None:
    return value.__name__ if callable(value) else None


@pytest.mark.parametrize(("build", "ecutrho"), _NOT_FRAGILE, ids=_name)
def test_pw_x_s_grid_passes_on_every_strain_of_a_cell_that_is_not_fragile(
    build, ecutrho: float
) -> None:
    structure = build()
    rotations = pw_rotations(structure)
    assert fragile_axis_pairs(structure, rotations) == ()

    for strain in symmetric_strains(structure, rotations):
        cell = strained(structure, strain)
        kept = pw_rotations(cell)

        assert len(kept) == len(rotations)
        assert grid_is_compatible(kept, dense_fft_grid(cell, ecutrho))


@pytest.mark.parametrize(("build", "ecutrho"), _FRAGILE, ids=_name)
def test_pw_x_s_grid_fails_on_every_isotropic_strain_of_a_fragile_cell(
    build, ecutrho: float
) -> None:
    structure = build()

    for size in ISOTROPIC_STRAINS:
        cell = strained(structure, size * np.eye(3))

        assert not grid_is_compatible(pw_rotations(cell), dense_fft_grid(cell, ecutrho))


@pytest.mark.parametrize(("build", "ecutrho"), _NOT_FRAGILE + _FRAGILE, ids=_name)
def test_the_grid_to_write_passes_on_every_strain(build, ecutrho: float) -> None:
    structure = build()

    for strain in symmetric_strains(structure, pw_rotations(structure)):
        cell = strained(structure, strain)
        kept = pw_rotations(cell)
        own = dense_fft_grid(cell, ecutrho)
        grid = ph_fft_grid(cell, kept, ecutrho)

        assert grid_is_compatible(kept, grid)
        assert all(length >= least for length, least in zip(grid, own, strict=True))
