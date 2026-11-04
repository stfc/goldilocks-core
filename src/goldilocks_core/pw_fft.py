"""pw_fft: pw.x's dense FFT grid, the grid ph.x accepts, and the cells on
which pw.x's own grid can fail ph.x (#215).

**pw.x's grid.** Unless the input gives nr1, nr2 and nr3, pw.x sizes its
dense FFT grid itself (QE 7.3 ``FFTXlib/src/fft_types.f90``,
``realspace_grid_init`` ``:1062-1116`` and ``grid_set`` ``:1120-1189``).
Along each lattice vector a_i it takes the largest |m_i| of a G-vector
m_1 b_1 + m_2 b_2 + m_3 b_3 with |G|^2 < ecutrho, and nr_i is the smallest
integer from 2 |m_i| + 1 up that has no prime factor above 5 and is a
multiple of the axis' ``pw_symmetry.fft_factors`` (``fft_support.f90``
``good_fft_order`` and ``allowed``, the rule of every FFT library but IBM's
ESSL). The smooth grid follows the same rule at 4 ecutwfc
(``PW/src/data_structure.f90:74-77``).

**ph.x's test.** ph.x symmetrizes in real space and stops with "FFT grid
incompatible with symmetry" (``PHonon/PH/phq_setup.f90:211-212``) unless
every rotation pw.x kept maps the grid onto itself: (W[j, i] nr_j) mod
nr_i is 0 for i != j, x -> W x being the rotation in crystal coordinates
(``check_grid_sym``, ``PW/src/symm_base.f90:1187-1216``). pw.x never runs
that test, and a rotation that mixes two lattice vectors of different
lengths can fail it, as in a centred lattice written in a primitive basis
or an antiferromagnetic supercell: alpha-U's base-centred cell has a mirror
that turns a_2 into a_1 + a_2, which needs nr_1 to be a multiple of nr_2,
and its grid of 40 x 45 x 64 at 480 Ry fails. ``ph_fft_grid`` is then the
grid to write as nr1-nr3, which pw.x uses as given
(``PW/src/input.f90:1782-1797``).

**Fragile cells.** Lattice vectors a rotation exchanges are equally long
and reach equally far in G, so pw.x gives them equal nr_i when their
factors are equal, and a mixed pair with equal nr_i passes ph.x's test.
pw.x's own grid therefore passes on every symmetric strain of a cell whose
mixed pairs are all exchanged pairs with equal factors;
``fragile_axis_pairs`` names the mixed pairs that are not. That matters
after a vc-relax, whose final scf rebuilds pw.x's grid for the relaxed cell
and drops a written nr1-nr3 (``PW/src/run_pwscf.f90:404-405``).
"""

from __future__ import annotations

import itertools
import math

import numpy as np
from pymatgen.core import Structure

from goldilocks_core.pw_symmetry import PwRotations, fft_factors, mixing_axis_pairs

_BOHR_ANGSTROM = 0.529177210903
"""QE 7.3's bohr radius in A (``Modules/constants.f90:38``, ``:111``)."""


def dense_fft_grid(structure: Structure, ecutrho_ry: float) -> tuple[int, int, int]:
    """pw.x's dense FFT grid (nr1, nr2, nr3) for ``structure`` as written at
    ``ecutrho_ry`` (Ry) when the input gives none (module docstring); at
    4 ecutwfc, its smooth grid."""
    factors = fft_factors(structure)
    reach = _miller_reach(structure.lattice.matrix / _BOHR_ANGSTROM, ecutrho_ry)
    nr1, nr2, nr3 = (
        good_fft_order(2 * index + 1, factor)
        for index, factor in zip(reach, factors, strict=True)
    )
    return nr1, nr2, nr3


def good_fft_order(length: int, factor: int = 1) -> int:
    """The smallest n >= ``length`` that is a multiple of ``factor`` with no
    prime factor above 5 (``good_fft_order``)."""
    while length % factor or not _five_smooth(length):
        length += 1
    return length


def grid_is_compatible(rotations: PwRotations, grid: tuple[int, int, int]) -> bool:
    """Whether every operation in ``rotations`` maps the FFT ``grid`` onto
    itself, ph.x's ``check_grid_sym`` (module docstring)."""
    lengths = np.array(grid)
    return bool(np.all(rotations.rotations * lengths[:, None] % lengths == 0))


def ph_fft_grid(
    structure: Structure, rotations: PwRotations, ecutrho_ry: float
) -> tuple[int, int, int]:
    """The FFT grid ph.x accepts for ``structure`` at ``ecutrho_ry``: pw.x's
    own (``dense_fft_grid``) when it is compatible with ``rotations``;
    otherwise, of the grids whose every nr_i is at least pw.x's own, has no
    prime factor above 5 and is a multiple of the axis' ``fft_factors``,
    the compatible one with the fewest points, the lexicographically
    smallest of equals. One always exists: nr_1 = nr_2 = nr_3 equal to the
    smallest such multiple of all three factors that is at least pw.x's
    largest nr_i."""
    own = dense_fft_grid(structure, ecutrho_ry)
    if grid_is_compatible(rotations, own):
        return own
    factors = fft_factors(structure)
    top = good_fft_order(max(own), math.lcm(*factors))
    lengths = (
        [n for n in range(start, top + 1) if n % factor == 0 and _five_smooth(n)]
        for start, factor in zip(own, factors, strict=True)
    )
    nr1, nr2, nr3 = min(
        (
            grid
            for grid in itertools.product(*lengths)
            if grid_is_compatible(rotations, grid)
        ),
        key=lambda grid: (math.prod(grid), grid),
    )
    return nr1, nr2, nr3


def fragile_axis_pairs(
    structure: Structure, rotations: PwRotations
) -> tuple[tuple[int, int], ...]:
    """The pairs of ``mixing_axis_pairs`` on which a symmetric strain of
    ``structure`` can give pw.x's own grid unequal nr_i (module docstring):
    those no operation in ``rotations`` exchanges, mapping a_i onto +-a_j,
    and exchanged pairs whose ``fft_factors`` differ. When there are none,
    pw.x's own grid passes ph.x's test on every such strain."""
    factors = fft_factors(structure)
    exchanged = _exchanged_axes(rotations)
    return tuple(
        (i, j)
        for i, j in mixing_axis_pairs(rotations)
        if frozenset((i, j)) not in exchanged or factors[i] != factors[j]
    )


def _exchanged_axes(rotations: PwRotations) -> set[frozenset[int]]:
    """The pairs {i, j} of lattice axes some operation in ``rotations``
    exchanges: its column i is +-e_j, so it maps a_i onto +-a_j."""
    magnitudes = np.abs(rotations.rotations)
    targets = magnitudes.argmax(axis=1)
    return {
        frozenset((int(axis), int(targets[operation, axis])))
        for operation, axis in zip(
            *np.nonzero(magnitudes.sum(axis=1) == 1), strict=True
        )
        if targets[operation, axis] != axis
    }


def _miller_reach(lattice: np.ndarray, ecutrho_ry: float) -> tuple[int, int, int]:
    """The largest |m_i| of a G-vector m_1 b_1 + m_2 b_2 + m_3 b_3 with
    |G|^2 < ``ecutrho_ry`` for the ``lattice`` rows in bohr, enumerated as
    ``grid_set`` does over |m_i| <= int(sqrt(ecutrho) |a_i| / 2 pi) + 1,
    which holds every such G; one m_3 >= 0 plane at a time, since -G
    reaches as far as G."""
    reciprocal = 2.0 * math.pi * np.linalg.inv(lattice).T
    bound = [
        int(math.sqrt(ecutrho_ry) * float(np.linalg.norm(row)) / (2.0 * math.pi)) + 1
        for row in lattice
    ]
    m1, m2 = np.meshgrid(
        np.arange(-bound[0], bound[0] + 1),
        np.arange(-bound[1], bound[1] + 1),
        indexing="ij",
    )
    plane = m1[..., None] * reciprocal[0] + m2[..., None] * reciprocal[1]
    reach = [0, 0, 0]
    for m3 in range(bound[2] + 1):
        vectors = plane + m3 * reciprocal[2]
        inside = np.einsum("...i,...i->...", vectors, vectors) < ecutrho_ry
        if inside.any():
            reach[0] = max(reach[0], int(np.abs(m1[inside]).max()))
            reach[1] = max(reach[1], int(np.abs(m2[inside]).max()))
            reach[2] = m3
    return reach[0], reach[1], reach[2]


def _five_smooth(length: int) -> bool:
    """Whether ``length`` has no prime factor above 5 (``allowed``)."""
    for prime in (2, 3, 5):
        while length % prime == 0:
            length //= prime
    return length == 1
