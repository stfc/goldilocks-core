"""pw_symmetry: the symmetry pw.x finds in a cell as written, and the frame
the cell is written in so that pw.x finds as much of it as it can (#140).

**pw.x's own rules.** pw.x does not search for symmetry; it tests a fixed
list (QE 7.3 ``PW/src/symm_base.f90``):

- ``set_sym_bl`` (``:126-350``) tries 32 Cartesian rotations -- the 24 of a
  cube with its axes on x, y and z, and 8 more for a hexagonal axis along z
  -- and keeps those that map the lattice onto itself to 1e-6 in the
  lattice basis (``eps1``), each with its product with inversion. A kept
  set of the wrong size, or one that is not a group, leaves the identity
  and inversion, or the identity alone.
- ``sgam_at`` (``:437-600``) keeps the rotations that map every atom onto
  an atom of its own type within 1e-5 in crystal coordinates (``checksym``,
  ``eqvect``, ``accep``), with no fractional translation or with one whose
  every component is 0 or +-1/n, n in {2, 3, 4, 6} (to 1e-5, ``eps2``),
  found by sending the first atom onto each atom of its type. A cell that
  maps onto itself by a pure translation -- a supercell -- gets no
  fractional translation at all.
- A magnetic noncollinear run (``magnetic_sym = noncolin .AND. domag``,
  ``PW/src/setup.f90:484-485``) also keeps only the operations that map
  every moment onto the moment of the atom it lands on, alone or with time
  reversal (``sgam_at_mag``, ``:604-696``), and pairs no k-point with -k.

``pw_rotations`` applies exactly these rules to a structure, typed by its
species: on the simulated cell these are the species pw.x is given, one per
element and starting-magnetization class (``advisors/species_split.py``).
``irreducible_kpoints`` reduces a k-point mesh by what it keeps, as
pw.x's ``kpoint_grid`` does, to one point of each orbit (ph.x reduces its
q-point mesh the same way), and ``irreducible_kpoint_count`` counts them:
the number of k-points pw.x runs, not that of the crystal's full space
group. A cell in pymatgen's frame (c along z, a in the xz plane) shows
pw.x only part of its point group: diamond Si's primitive cell (MC3D
mc3d-42058) keeps 4 of 48 operations there, and pw.x 7.5 ran 282 k-points
of its 10x10x10 mesh where spglib's full group gives 47.

**Grids.** pw.x makes each FFT grid length a multiple of its axis'
``fft_factors``, which the fractional translations ``sgam_at`` finds set,
so that every translation maps grid points onto grid points.
``mixing_axis_pairs`` names the pairs of lattice axes a kept rotation
mixes: ph.x's tests of the FFT grid and of the q-mesh can fail only on
those pairs (``pw_fft``, ``advisors/q_sampling.py``).

**The written frame.** ``pw_frame`` writes the cell in the frame, of those
below, where pw.x keeps the most operations (``FRAME_TOLERANCE``) -- its
whole point group on each of the 84 structures of the 2026-10-19 batch --
keeping its lattice basis, site order, species and labels -- so fractional
coordinates, the k-grid, the k ladder, starting-magnetization and Hubbard
labels and the slab's layers keep their meaning:

- the lattice and the atoms are idealized to the space group spglib finds
  within ``FRAME_TOLERANCE``: CIF rounding leaves lattices about 1e-5 A and
  atoms about 1e-5 to 1e-4 A away from it, more than pw.x's tolerances;
- a cell with no vacuum is turned rigidly into spglib's standard
  orientation (cubic axes on x, y, z; a hexagonal a along x and c along z)
  when that lets pw.x keep more operations;
- a slab with its vacuum along c is turned rigidly so that a lies along +x
  and a x b along +z, the frame QE's 2D cell constraints and 2D Coulomb
  truncation assume (maintainer decision); in a left-handed cell a x b
  goes along -z instead, because the 2D truncation needs c's z component
  positive (``PW/src/Coul_cut_2D.f90:77``). pw.x keeps an in-plane 2-fold
  axis or mirror only where it lies at a multiple of 30 or 45 degrees from
  x, so in this frame a sheet whose in-plane axes lie elsewhere relative
  to a loses them: a centred-rectangular sheet given in its primitive basis
  (a = b, gamma not 60, 90 or 120 degrees) has them along a +- b and keeps
  half its operations. A slab with its vacuum along a or b, a wire and a
  molecule in a box keep their orientation;
- the origin moves to spglib's standard origin when that lets pw.x keep
  more operations, since an off-centre mirror or screw axis has a
  fractional translation pw.x rejects. The shift is taken modulo half
  lattice vectors, which keeps every translation pw.x accepts acceptable
  (in a supercell, which allows no fractional translation, modulo whole
  ones); along a vacuum axis, the choice that keeps the structure in one
  piece inside the cell is preferred.

Among those candidates the one pw.x keeps most operations in wins, then the
unturned, then the unshifted; among shifts, the one that leaves the structure
in one piece along its vacuum axes, then the shortest. ``PwFrame``
records what was done. The rotation and the shift are rigid motions, which
leave the energy unchanged; the idealization moves atoms by no more than
``FRAME_TOLERANCE``.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

import numpy as np
import spglib
from pymatgen.core import Structure

from goldilocks_core.analysis.geometry import LATTICE_AXES, vacuum_axes

FRAME_TOLERANCE = 1e-3
"""Angstrom: spglib's tolerance when ``pw_frame`` idealizes a cell, and so
the most it moves a lattice vector or an atom. CIF rounding is one or two
orders below it, so it finds the groups ``analysis.symmetry.SYMPREC``
(1e-2 A) finds on the 84 structures of the 2026-10-19 batch while moving no
atom more than 1e-4 A, and it keeps real distortions of 1e-3 A and above,
which ``SYMPREC`` would symmetrize away."""

_LATTICE_TOLERANCE = 1e-6
"""pw.x's ``eps1``: largest distance from an integer of a rotation's matrix
in the lattice basis (``set_sym_bl``)."""

_TRANSLATION_TOLERANCE = 1e-5
"""pw.x's ``eps2``: how close 1/|t| must be to an integer for a fractional
translation component t (``sgam_at``), and moments to agree
(``sgam_at_mag``)."""

_POSITION_TOLERANCE = 1e-5
"""pw.x's ``accep``: largest difference of each crystal coordinate between
an atom's image and the atom it lands on (``checksym``)."""

_ALLOWED_TRANSLATION_DENOMINATORS = frozenset({2, 3, 4, 6})

_UNCHANGED = 1e-10
"""Idealization keeps a coordinate or lattice component whose idealized
value differs from it by at most this (A for the lattice, crystal
coordinates for atoms): spglib's own arithmetic leaves 1e-11, and CIF
rounding is 1e-6 and above."""

_ZERO = 1e-12
"""A framed lattice component (A) or crystal coordinate within this of 0 is
set to 0: rotating and idealizing leave 1e-16-sized residues where the exact
value is 0. The framed cell is the simulated cell every later reader takes:
the symmetry and k-point counts, QRF95's k_distance (which moves with such
residues) and the writer. The writer also writes any card value below 1e-10
as 0 on its own (``generation.quantum_espresso.scf``), so this snap is not
what keeps exponent-form noise out of the input."""

_SIN3 = 0.866025403784438597
_COS3 = 0.5

_SET_SYM_BL_DATA = (
    (1, 0, 0, 0, 1, 0, 0, 0, 1),
    (-1, 0, 0, 0, -1, 0, 0, 0, 1),
    (-1, 0, 0, 0, 1, 0, 0, 0, -1),
    (1, 0, 0, 0, -1, 0, 0, 0, -1),
    (0, 1, 0, 1, 0, 0, 0, 0, -1),
    (0, -1, 0, -1, 0, 0, 0, 0, -1),
    (0, -1, 0, 1, 0, 0, 0, 0, 1),
    (0, 1, 0, -1, 0, 0, 0, 0, 1),
    (0, 0, 1, 0, -1, 0, 1, 0, 0),
    (0, 0, -1, 0, -1, 0, -1, 0, 0),
    (0, 0, -1, 0, 1, 0, 1, 0, 0),
    (0, 0, 1, 0, 1, 0, -1, 0, 0),
    (-1, 0, 0, 0, 0, 1, 0, 1, 0),
    (-1, 0, 0, 0, 0, -1, 0, -1, 0),
    (1, 0, 0, 0, 0, -1, 0, 1, 0),
    (1, 0, 0, 0, 0, 1, 0, -1, 0),
    (0, 0, 1, 1, 0, 0, 0, 1, 0),
    (0, 0, -1, -1, 0, 0, 0, 1, 0),
    (0, 0, -1, 1, 0, 0, 0, -1, 0),
    (0, 0, 1, -1, 0, 0, 0, -1, 0),
    (0, 1, 0, 0, 0, 1, 1, 0, 0),
    (0, -1, 0, 0, 0, -1, 1, 0, 0),
    (0, -1, 0, 0, 0, 1, -1, 0, 0),
    (0, 1, 0, 0, 0, -1, -1, 0, 0),
    (_COS3, _SIN3, 0, -_SIN3, _COS3, 0, 0, 0, 1),
    (_COS3, -_SIN3, 0, _SIN3, _COS3, 0, 0, 0, 1),
    (-_COS3, _SIN3, 0, -_SIN3, -_COS3, 0, 0, 0, 1),
    (-_COS3, -_SIN3, 0, _SIN3, -_COS3, 0, 0, 0, 1),
    (_COS3, -_SIN3, 0, -_SIN3, -_COS3, 0, 0, 0, -1),
    (_COS3, _SIN3, 0, _SIN3, -_COS3, 0, 0, 0, -1),
    (-_COS3, -_SIN3, 0, -_SIN3, _COS3, 0, 0, 0, -1),
    (-_COS3, _SIN3, 0, _SIN3, _COS3, 0, 0, 0, -1),
)
"""``set_sym_bl``'s ``s0`` (QE 7.3 ``PW/src/symm_base.f90:156-187``), in
its DATA order: Fortran fills each 3x3 matrix column by column."""

_PW_ROTATIONS = tuple(
    np.array(data, dtype=float).reshape(3, 3).T for data in _SET_SYM_BL_DATA
)
"""The 32 Cartesian rotations pw.x tests a lattice against."""

_LATTICE_GROUP_ORDERS = frozenset({1, 2, 4, 6, 8, 12, 24})
"""The numbers of proper rotations a lattice can keep; any other leaves
only the identity (``set_sym_bl``)."""


@dataclass(frozen=True, slots=True, eq=False)
class PwRotations:
    """The operations pw.x keeps (module docstring), by their rotations in
    the lattice basis (``x -> W x + t`` in crystal coordinates, spglib's
    convention). ``time_reversed`` flags the operations a magnetic
    noncollinear run keeps only combined with time reversal;
    ``time_reversal`` is whether pw.x pairs each k-point with -k (false
    exactly for such a run)."""

    rotations: np.ndarray
    time_reversed: np.ndarray
    time_reversal: bool

    def __len__(self) -> int:
        return len(self.rotations)


@dataclass(frozen=True, slots=True)
class PwFrame:
    """How ``pw_frame`` wrote a cell. ``rotation`` is the Cartesian rotation
    R applied to it (rows: written lattice = uploaded lattice @ R^T), the
    identity unless ``rotated``, which is true only when R moves some
    uploaded lattice vector by more than ``FRAME_TOLERANCE``: a smaller
    turn only undoes a tilt the idealization gave the cell, and counts as
    displacement; ``origin_shift`` the fractional vector added to every
    site (the written coordinates are then wrapped into [0, 1));
    ``max_displacement_angstrom`` the most any lattice vector or atom of the
    written cell lies from the uploaded one moved by the recorded rotation
    and shift, in A rounded to 1e-6; ``operations`` the number of
    operations pw.x keeps in the written cell, moments aside
    (``pw_rotations``)."""

    rotated: bool
    rotation: tuple[tuple[float, float, float], ...]
    origin_shift: tuple[float, float, float]
    max_displacement_angstrom: float
    operations: int

    def describe_rotation(self) -> str:
        """The rotation as an angle about an axis, e.g. 'rotated by 54.7356
        degrees about [0.7071, -0.7071, 0]', or 'not rotated'."""
        if not self.rotated:
            return "not rotated"
        rotation = np.array(self.rotation)
        cosine = min(1.0, max(-1.0, (float(np.trace(rotation)) - 1.0) / 2.0))
        angle = math.degrees(math.acos(cosine))
        skew = np.array(
            [
                rotation[2, 1] - rotation[1, 2],
                rotation[0, 2] - rotation[2, 0],
                rotation[1, 0] - rotation[0, 1],
            ]
        )
        if np.linalg.norm(skew) > 1e-6:
            axis = skew
        else:  # a half turn: R + I is twice the axis' outer product
            symmetric = (rotation + np.eye(3)) / 2.0
            axis = symmetric[int(np.argmax(np.diag(symmetric)))]
        axis = axis / np.linalg.norm(axis)
        components = ", ".join(f"{float(value):.4g}" for value in axis + 0.0)
        return f"rotated by {angle:.4f} degrees about [{components}]"


def pw_rotations(
    structure: Structure, moment_axis: np.ndarray | None = None
) -> PwRotations:
    """The operations pw.x keeps in ``structure`` as written (module
    docstring), its sites typed by species. ``moment_axis`` is the
    Cartesian direction of a magnetic noncollinear run's moments, each
    site's moment being its ``Species.spin`` times it; ``None`` for every
    other run. With every moment zero the run is not magnetic (pw.x's
    ``domag``)."""
    lattice = structure.lattice.matrix
    operations = _operations(lattice, structure.frac_coords, _types(structure))
    moments = None
    if moment_axis is not None:
        spins = np.array(
            [getattr(site.specie, "spin", None) or 0.0 for site in structure]
        )
        if np.any(spins != 0.0):
            moments = np.outer(spins, moment_axis) @ np.linalg.inv(lattice)
    if moments is None:
        rotations = [rotation for rotation, _, _ in operations]
        return PwRotations(
            rotations=np.array(rotations, dtype=int),
            time_reversed=np.zeros(len(rotations), dtype=bool),
            time_reversal=True,
        )
    kept = _magnetic(operations, moments)
    return PwRotations(
        rotations=np.array([rotation for rotation, _ in kept], dtype=int),
        time_reversed=np.array([reversed_ for _, reversed_ in kept], dtype=bool),
        time_reversal=False,
    )


def irreducible_kpoints(
    rotations: PwRotations,
    mesh: tuple[int, int, int],
    shift: tuple[int, int, int],
) -> np.ndarray:
    """One k-point of each orbit pw.x reduces the Monkhorst-Pack ``mesh``
    with ``shift`` to under ``rotations``, in crystal coordinates of the
    reciprocal lattice vectors, one row each: spglib's
    ``get_stabilized_reciprocal_mesh`` orbits, where a time-reversed
    operation acts on k as -W and time reversal pairs k with -k only when
    ``rotations.time_reversal``."""
    k_rotations = np.unique(
        [
            -rotation if reversed_ else rotation
            for rotation, reversed_ in zip(
                rotations.rotations, rotations.time_reversed, strict=True
            )
        ],
        axis=0,
    )
    mapping, grid = spglib.get_stabilized_reciprocal_mesh(
        mesh,
        np.asarray(k_rotations, dtype="intc"),
        is_shift=shift,
        is_time_reversal=rotations.time_reversal,
    )
    return (2 * grid[np.unique(mapping)] + np.asarray(shift)) / (2 * np.asarray(mesh))


def irreducible_kpoint_count(
    rotations: PwRotations,
    mesh: tuple[int, int, int],
    shift: tuple[int, int, int],
) -> int:
    """The number of k-points pw.x runs of the Monkhorst-Pack ``mesh`` with
    ``shift`` under ``rotations``: one per orbit (``irreducible_kpoints``)."""
    return len(irreducible_kpoints(rotations, mesh, shift))


def fft_factors(structure: Structure) -> tuple[int, int, int]:
    """``sgam_at``'s ``fft_fact`` for ``structure`` as written, its sites
    typed by species: per lattice axis, the least common multiple of n over
    the operations pw.x finds with a fractional translation component of
    +-1/n along that axis, before a magnetic noncollinear run drops some of
    them (QE 7.3 ``PW/src/symm_base.f90:514,562-572``). pw.x makes each FFT
    grid length a multiple of it; (1, 1, 1) without fractional translations,
    as in a supercell."""
    operations = _operations(
        structure.lattice.matrix, structure.frac_coords, _types(structure)
    )
    factors = [1, 1, 1]
    for _rotation, translation, _landing in operations:
        for axis, component in enumerate(np.abs(translation)):
            if component > _TRANSLATION_TOLERANCE:
                factors[axis] = math.lcm(factors[axis], round(1.0 / component))
    return factors[0], factors[1], factors[2]


def mixing_axis_pairs(rotations: PwRotations) -> tuple[tuple[int, int], ...]:
    """The ordered pairs (i, j), i != j, of lattice axes that some operation
    in ``rotations`` mixes: W[j, i] != 0, so it turns a_i into a vector with
    a component along a_j. Sorted; empty when every operation maps each
    lattice vector onto plus or minus itself."""
    mixed = np.any(rotations.rotations != 0, axis=0)
    return tuple((i, j) for i in range(3) for j in range(3) if i != j and mixed[j, i])


def pw_frame(structure: Structure) -> tuple[Structure, PwFrame]:
    """``structure`` written in the frame, of those the module docstring
    lists, where pw.x keeps the most operations, with the ``PwFrame``
    describing how and how many it keeps. Site order, species, labels and
    site properties are kept. A disordered structure, or one spglib finds
    no symmetry dataset for, is returned as it is."""
    types = _types(structure)
    lattice = structure.lattice.matrix
    dataset = (
        spglib.get_symmetry_dataset(
            (lattice, structure.frac_coords, types), symprec=FRAME_TOLERANCE
        )
        if structure.is_ordered
        else None
    )
    if dataset is None:
        return structure, _unframed(structure, types)
    ideal = _idealized(structure, types, dataset)
    axes = vacuum_axes(structure)
    candidates = [
        (rotation, written, shift)
        for rotation, written in _orientations(ideal, axes)
        for shift in _origin_shifts(ideal, axes)
    ]
    scored = [
        (_score(written, ideal.positions, shift, types, rotation, axes), index)
        for index, (rotation, written, shift) in enumerate(candidates)
    ]
    (count, *_), index = min(scored)
    rotation, written, shift = candidates[index]
    framed = Structure(
        _snapped(written),
        structure.species,
        _snapped(_shifted(ideal.positions, shift)),
        labels=structure.labels,
        site_properties=structure.site_properties,
    )
    rotated = _turns(rotation, lattice)
    recorded = rotation if rotated else np.eye(3)
    displacement = _displacement(structure, written, ideal.positions, recorded)
    return framed, PwFrame(
        rotated=rotated,
        rotation=_rounded_rows(recorded),
        origin_shift=_rounded(shift),
        max_displacement_angstrom=round(displacement, 6) + 0.0,
        operations=-count,
    )


def _turns(rotation: np.ndarray, lattice: np.ndarray) -> bool:
    """Whether ``rotation`` moves some vector of ``lattice`` by more than
    ``FRAME_TOLERANCE``, the most the idealization moves one: a slab whose
    idealized a tilts 1e-6 rad off x is turned back by that much, which
    leaves the uploaded Cartesian axes where they were."""
    moved = np.linalg.norm(lattice @ (rotation - np.eye(3)).T, axis=1)
    return bool(moved.max() > FRAME_TOLERANCE)


def _displacement(
    structure: Structure,
    written: np.ndarray,
    positions: np.ndarray,
    rotation: np.ndarray,
) -> float:
    """The most a vector of the ``written`` lattice, or an atom at
    ``positions`` (crystal coordinates before the origin shift) in it, lies
    from the same vector or atom of ``structure`` turned by ``rotation``,
    in A."""
    turned = structure.lattice.matrix @ rotation.T
    moved = np.concatenate(
        [
            np.linalg.norm(written - turned, axis=1),
            np.linalg.norm(
                positions @ written - structure.frac_coords @ turned, axis=1
            ),
        ]
    )
    return float(moved.max())


@dataclass(frozen=True, slots=True)
class _Idealized:
    """A cell idealized to its space group (``pw_frame``): ``lattice`` in its
    input orientation and ``standard`` turned rigidly into spglib's
    standard orientation by ``rotation``, both in the input's basis;
    ``positions`` symmetrized in the input's basis and site order, close to
    the input's (not wrapped); ``origin`` the fractional shift that puts the
    standard origin at 0; ``supercell`` whether a pure translation maps the
    cell onto itself."""

    lattice: np.ndarray
    standard: np.ndarray
    rotation: np.ndarray
    positions: np.ndarray
    origin: np.ndarray
    supercell: bool


def _idealized(
    structure: Structure, types: list[int], dataset: spglib.SpglibDataset
) -> _Idealized:
    """``structure``'s idealized lattice and positions from spglib's
    standardized, idealized cell (``std_lattice``, ``std_positions``),
    mapped back through ``transformation_matrix`` P and ``origin_shift`` p
    (x_std = P x + p), the positions then averaged over the space group
    (``_averaged``)."""
    transformation = np.array(dataset.transformation_matrix)
    origin_shift = np.array(dataset.origin_shift)
    rotation = np.array(dataset.std_rotation_matrix)
    standard = transformation.T @ np.array(dataset.std_lattice)
    original = structure.lattice.matrix
    lattice = _kept(original, standard @ rotation)

    inverse = np.linalg.inv(transformation)
    standard_coordinates = structure.frac_coords @ transformation.T + origin_shift
    snapped = np.empty_like(standard_coordinates)
    std_positions = np.array(dataset.std_positions)
    std_lattice = np.array(dataset.std_lattice)
    std_mapping = np.array(dataset.std_mapping_to_primitive)
    mapping = np.array(dataset.mapping_to_primitive)
    for atom in np.unique(mapping):
        sites = np.flatnonzero(mapping == atom)
        images = std_positions[std_mapping == atom]
        offsets = standard_coordinates[sites][:, None, :] - images[None, :, :]
        offsets -= np.rint(offsets)
        nearest = np.argmin(np.linalg.norm(offsets @ std_lattice, axis=2), axis=1)
        snapped[sites] = (
            standard_coordinates[sites] - offsets[np.arange(len(sites)), nearest]
        )
    ideal = (snapped - origin_shift) @ inverse.T
    positions = _kept(
        structure.frac_coords,
        _averaged(structure.frac_coords, ideal, types, dataset),
    )

    pure_translation = [
        np.any(np.abs(translation - np.rint(translation)) > _POSITION_TOLERANCE)
        for rotation_, translation in zip(
            dataset.rotations, dataset.translations, strict=True
        )
        if np.array_equal(rotation_, np.eye(3, dtype=int))
    ]
    return _Idealized(
        lattice=lattice,
        standard=standard,
        rotation=rotation,
        positions=positions,
        origin=origin_shift @ inverse.T,
        supercell=any(pure_translation),
    )


def _averaged(
    positions: np.ndarray,
    ideal: np.ndarray,
    types: list[int],
    dataset: spglib.SpglibDataset,
) -> np.ndarray:
    """``positions`` averaged over the space group, the symmetric
    configuration nearest them: ``ideal`` (spglib's, which keeps one atom of
    each orbit where it is and moves the others onto its images) plus each
    site's displacement from it averaged over the operations. The pure
    translations of a supercell average the displacements of the sites
    they relate (those spglib maps to one primitive-cell atom); each
    rotation, with its translation refined on ``ideal``, carries a site's
    displacement onto the site it lands on."""
    kinds = np.asarray(types)
    displacement = positions - ideal
    mapping = np.array(dataset.mapping_to_primitive)
    for atom in np.unique(mapping):
        sites = mapping == atom
        displacement[sites] = displacement[sites].mean(axis=0)
    first = {}
    for rotation, translation in zip(
        dataset.rotations, dataset.translations, strict=True
    ):
        first.setdefault(rotation.tobytes(), (rotation, translation))
    total = np.zeros_like(displacement)
    alike = np.flatnonzero(kinds == kinds[0])
    for rotation, translation in first.values():
        images = ideal @ rotation.T + translation
        offsets = ideal[alike] - images[0]
        offsets -= np.rint(offsets)
        images += offsets[np.argmin(np.abs(offsets).max(axis=1))]
        landing = _landing(images, ideal, kinds)
        total[landing] += displacement @ rotation.T
    return ideal + total / len(first)


def _snapped(values: np.ndarray) -> np.ndarray:
    """``values`` with every component within ``_ZERO`` of 0 set to 0."""
    return np.where(np.abs(values) < _ZERO, 0.0, values)


def _kept(original: np.ndarray, ideal: np.ndarray) -> np.ndarray:
    """``ideal``, keeping each component of ``original`` it differs from by
    at most ``_UNCHANGED``."""
    return np.where(np.abs(ideal - original) <= _UNCHANGED, original, ideal)


def _orientations(
    ideal: _Idealized, axes: tuple[str, ...]
) -> list[tuple[np.ndarray, np.ndarray]]:
    """The (rotation, written lattice) pairs ``pw_frame`` chooses from
    (module docstring): a slab with its vacuum along c only in the slab
    frame, any other cell with vacuum only as it is, a cell without vacuum
    as it is or in spglib's standard orientation."""
    if axes == ("c",):
        return [_slab_frame(ideal.lattice)]
    unturned = (np.eye(3), ideal.lattice)
    if axes or np.linalg.det(ideal.rotation) < 0:
        return [unturned]
    return [unturned, (ideal.rotation, ideal.standard)]


def _slab_frame(lattice: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The rotation that puts a along +x, a and b in the xy plane and c's z
    component above 0 -- a x b along +z, or along -z in a left-handed cell
    -- and the lattice it gives, built from lengths and projections so that
    a's y and z and b's z components are exactly 0."""
    a, b, c = lattice
    e1 = a / np.linalg.norm(a)
    normal = np.cross(a, b) * np.sign(np.linalg.det(lattice))
    e3 = normal / np.linalg.norm(normal)
    e2 = np.cross(e3, e1)
    rotation = np.array([e1, e2, e3])
    written = np.array(
        [
            [float(np.linalg.norm(a)), 0.0, 0.0],
            [float(b @ e1), float(b @ e2), 0.0],
            [float(c @ e1), float(c @ e2), float(c @ e3)],
        ]
    )
    return rotation, written


def _origin_shifts(ideal: _Idealized, axes: tuple[str, ...]) -> list[np.ndarray]:
    """The fractional origin shifts ``pw_frame`` chooses from (module
    docstring): none, or the standard origin -- reduced modulo half lattice
    vectors, or modulo whole ones in a supercell, where pw.x allows no
    fractional translation -- with each vacuum axis' component also tried
    half a vector further on and left unshifted. Half a vacuum vector
    further on adds no translation to an operation that maps that vector
    onto itself or its negative, so it costs a supercell nothing there."""
    step = 1.0 if ideal.supercell else 0.5
    reduced = ideal.origin - np.rint(ideal.origin / step) * step
    options = []
    for index, axis in enumerate(LATTICE_AXES):
        values = [float(reduced[index])]
        if axis in axes:
            values.extend((float(reduced[index]) + 0.5, 0.0))
        options.append(values)
    shifts = [np.zeros(3)]
    shifts.extend(np.array(choice) for choice in itertools.product(*options))
    return shifts


def _score(
    lattice: np.ndarray,
    positions: np.ndarray,
    shift: np.ndarray,
    types: list[int],
    rotation: np.ndarray,
    axes: tuple[str, ...],
) -> tuple[int, bool, bool, bool, float]:
    """``pw_frame``'s ranking key, smallest first: the most operations pw.x
    keeps, then no rotation, then no shift, then -- among shifts -- the
    structure in one piece along each vacuum axis and the shortest shift."""
    coordinates = _shifted(positions, shift)
    count = len(_operations(lattice, coordinates, types))
    turned = bool(np.abs(rotation - np.eye(3)).max() > _UNCHANGED)
    split = any(
        not _in_one_piece(coordinates[:, LATTICE_AXES.index(axis)]) for axis in axes
    )
    length = float(np.linalg.norm(shift @ lattice))
    return -count, turned, bool(np.any(shift)), split, length


def _shifted(positions: np.ndarray, shift: np.ndarray) -> np.ndarray:
    """``positions`` plus ``shift``, wrapped into [0, 1) when ``shift`` is
    not zero."""
    if not np.any(shift):
        return positions
    return np.mod(positions + shift, 1.0)


def _in_one_piece(coordinates: np.ndarray) -> bool:
    """Whether the widest atom-free gap along one lattice vector is the one
    across the cell boundary, so no atom of the slab is wrapped to the
    other side of the cell."""
    ordered = np.sort(np.mod(coordinates, 1.0))
    across = ordered[0] + 1.0 - ordered[-1]
    inside = np.diff(ordered)
    return bool(len(inside) == 0 or across >= inside.max())


def _unframed(structure: Structure, types: list[int]) -> PwFrame:
    """The frame of a structure written as it is."""
    count = (
        len(_operations(structure.lattice.matrix, structure.frac_coords, types))
        if structure.is_ordered
        else 1
    )
    return PwFrame(
        rotated=False,
        rotation=_rounded_rows(np.eye(3)),
        origin_shift=(0.0, 0.0, 0.0),
        max_displacement_angstrom=0.0,
        operations=count,
    )


def _rounded(vector: np.ndarray) -> tuple[float, float, float]:
    x, y, z = (round(float(value), 12) + 0.0 for value in vector)
    return x, y, z


def _rounded_rows(matrix: np.ndarray) -> tuple[tuple[float, float, float], ...]:
    return tuple(_rounded(row) for row in matrix)


def _types(structure: Structure) -> list[int]:
    """One integer per site, one per distinct species: element and, in a
    spin-polarized cell, starting-magnetization class."""
    index: dict[str, int] = {}
    return [index.setdefault(site.species_string, len(index)) for site in structure]


def _operations(
    lattice: np.ndarray, positions: np.ndarray, types: list[int]
) -> list[tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """``sgam_at``: each lattice rotation W pw.x keeps, as (W, its
    fractional translation t with x -> W x + t, the index of the site each
    site lands on)."""
    kinds = np.asarray(types)
    fractional = not _supercell(positions, kinds)
    kept = []
    for rotation in _lattice_rotations(lattice):
        rotated = positions @ rotation.T
        translation = np.zeros(3)
        landing = _landing(rotated, positions, kinds)
        if landing is None and fractional:
            for candidate in np.flatnonzero(kinds == kinds[0]):
                offset = rotated[candidate] - positions[0]
                translation = -(offset - np.rint(offset))
                if not _allowed_translation(translation):
                    continue
                landing = _landing(rotated + translation, positions, kinds)
                if landing is not None:
                    break
        if landing is not None:
            kept.append((rotation, translation, landing))
    return kept


def _lattice_rotations(lattice: np.ndarray) -> list[np.ndarray]:
    """``set_sym_bl``: the lattice-basis matrix W (x -> W x) of each of
    ``_PW_ROTATIONS`` that maps ``lattice`` (rows) onto itself to
    ``_LATTICE_TOLERANCE``, then each times -1 (inversion); only the
    identity and inversion when the proper ones number other than
    ``_LATTICE_GROUP_ORDERS``, only the identity when the whole set is not
    a group."""
    columns = lattice.T / np.linalg.norm(lattice[0])
    inverse_overlap = np.linalg.inv(columns.T @ columns)
    proper = []
    for cartesian in _PW_ROTATIONS:
        value = inverse_overlap @ columns.T @ cartesian @ columns
        if np.all(np.abs(np.rint(value) - value) <= _LATTICE_TOLERANCE):
            proper.append(np.rint(value).astype(int))
    if len(proper) not in _LATTICE_GROUP_ORDERS:
        proper = [np.eye(3, dtype=int)]
    rotations = [*proper, *(-rotation for rotation in proper)]
    keys = {rotation.tobytes() for rotation in rotations}
    closed = all(
        (first @ second).tobytes() in keys
        for first in rotations
        for second in rotations
    )
    return rotations if closed else [np.eye(3, dtype=int)]


def _supercell(positions: np.ndarray, kinds: np.ndarray) -> bool:
    """Whether a pure translation sending the first site onto another of its
    type maps every site onto one of its type (``sgam_at``)."""
    for candidate in np.flatnonzero(kinds == kinds[0])[1:]:
        offset = positions[candidate] - positions[0]
        offset -= np.rint(offset)
        if _landing(positions + offset, positions, kinds) is not None:
            return True
    return False


def _allowed_translation(translation: np.ndarray) -> bool:
    """Whether every component of ``translation`` (within (-1/2, 1/2]) is 0
    or +-1/n with n in ``_ALLOWED_TRANSLATION_DENOMINATORS``, to
    ``_TRANSLATION_TOLERANCE`` (``sgam_at``)."""
    for component in np.abs(translation):
        if component <= _TRANSLATION_TOLERANCE:
            continue
        inverse = 1.0 / component
        nearest = round(inverse)
        if abs(inverse - nearest) >= _TRANSLATION_TOLERANCE:
            return False
        if nearest not in _ALLOWED_TRANSLATION_DENOMINATORS:
            return False
    return True


def _landing(
    images: np.ndarray, positions: np.ndarray, kinds: np.ndarray
) -> np.ndarray | None:
    """The first site of its type each image lands on, within
    ``_POSITION_TOLERANCE`` in every crystal coordinate modulo 1
    (``checksym``, ``eqvect``); ``None`` when some image lands on none."""
    landing = np.empty(len(positions), dtype=int)
    for kind in np.unique(kinds):
        sites = np.flatnonzero(kinds == kind)
        offsets = images[sites][:, None, :] - positions[sites][None, :, :]
        offsets -= np.rint(offsets)
        matches = np.all(np.abs(offsets) < _POSITION_TOLERANCE, axis=2)
        if not matches.any(axis=1).all():
            return None
        landing[sites] = sites[np.argmax(matches, axis=1)]
    return landing


def _magnetic(
    operations: list[tuple[np.ndarray, np.ndarray, np.ndarray]],
    moments: np.ndarray,
) -> list[tuple[np.ndarray, bool]]:
    """``sgam_at_mag``: the operations that map every moment (crystal
    components, rows) onto the moment of the site it lands on, as (W,
    False), or onto its negative, as (W, True). Moments are axial, so an
    improper W also reverses them."""
    kept = []
    for rotation, _translation, landing in operations:
        turned = moments @ rotation.T * round(float(np.linalg.det(rotation)))
        target = moments[landing]
        same = np.all(np.abs(turned - target).sum(axis=1) < _TRANSLATION_TOLERANCE)
        opposite = np.all(np.abs(turned + target).sum(axis=1) < _TRANSLATION_TOLERANCE)
        if same:
            kept.append((rotation, False))
        elif opposite:
            kept.append((rotation, True))
    return kept
