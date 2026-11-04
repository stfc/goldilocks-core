"""k-point mesh ladder math, ported from goldilocks-data's ``kmesh.py``
(v2 epic 6, #6), replacing v1's ``kmesh/`` package (renamed to
``legacy_kmesh/`` to free this name -- see that package's own docstring).
The port no longer matches goldilocks-data rung for rung: core meshes the
axes a crystal's point group mixes alike (#163, below), so its rung numbers
diverge from goldilocks-data's ``goldilocks.k_index.ladder_1based.v2``, the
ladder goldilocks-ml's k_index model predicts rungs on, wherever those axes
differ in length.

**Why replace rather than reuse v1's own ladder.** v1's
``generate_candidate_k_distances`` bounded enumeration with a fixed
per-axis count (``max_kpoints_per_axis=50``): axes with different
reciprocal lengths exhaust that quota at *different* distances, leaving
holes in the ladder that v1's ``_complete_meshes`` then silently
papered over by truncating the whole list the first time any axis's
count jumped by more than one between rungs. This module instead bounds
enumeration with a single distance floor (``MIN_K_DISTANCE``, uniform
across every axis), so every axis runs out of change points together and
no change point above that floor is skipped -- the truncation logic simply
has nothing to trigger it and does not exist here. v1 also rounded
inconsistently between its two entry points (5 decimals in one, 8 in the
other, able to disagree at a boundary); this module keeps goldilocks-data's
own two-stage rounding (8 decimals to enumerate candidate change points,
5 decimals when converting any given probe distance to an integer mesh).
Two change points closer than the 5-decimal rounding resolves leave a
sliver of k-distance whose mesh repeats the rung above it;
``build_gamma_kmesh_entries`` joins the sliver to that rung, so no mesh
takes two rungs and the rungs' intervals tile the k-distance axis (#163).

**``k_pra``**, which v1's ladder never computed, is added here:
k-points per reciprocal atom, a cross-structure-comparable sampling-density
metric.

**No symmetry reduction.** goldilocks-data's ``KMeshEntry`` also carries
``n_reduced_kpoints``, from one ``SpacegroupAnalyzer.get_ir_reciprocal_mesh``
call per rung. Core's does not: nothing in core reads a rung's reduced
count, and reducing every rung made one ladder build take seconds on a
low-symmetry or small cell (#155). The ladder reads the point group only
to couple axes (below), once per ladder, and reduces no mesh.
``advisors/n_irr_k.py`` is the one place a mesh is reduced: the mesh a
step actually uses.

**Axes the point group mixes share one count (#163).** goldilocks-data
meshes each axis from its own reciprocal length. Where the point group
mixes axes of different length -- the reduced primitive cell of a centred
lattice, an antiferromagnetic supercell in a skewed basis -- or of lengths
CIF noise has made unequal, that gives meshes the group does not map onto
itself: alpha-U's 11x10x6 (Materials Project mp-44), 224 irreducible
k-points in pw.x where the denser 11x11x6 has 144, and on UN (mp-1865)
19 sliver rungs such as 32x33x32 that renumbered every rung above them.
Here each periodic axis is meshed from the longest reciprocal length among
the periodic axes some rotation of the point group mixes with it, directly
or through the third. An operation acts on reciprocal fractional
coordinates as an integer matrix R and keeps a mesh exactly when every
n_i R_ij / n_j is an integer, which equal counts on mixed axes guarantee;
the longest length keeps every axis at least as dense as the k-distance
asks. The point group is searched on the structure's species at
``analysis.symmetry.SYMPREC``: the species of a spin-polarized cell carry
their starting-magnetization class (``advisors/species_split.py``), so
sublattices of opposite spin are told apart, as pw.x types them. That
group contains the one pw.x keeps, which can be smaller: pw.x allows a
supercell no fractional translation, finds only the operations its fixed
Cartesian rotations place, and on a noncollinear magnetic run keeps only
those that respect the moments (``advisors/n_irr_k.py``). A mesh invariant
under the group is therefore invariant under pw.x's. Rungs are numbered
differently from goldilocks-data's wherever mixed axes differ in length
(alpha-U has 126 rungs, not 197; UN 74, not 93); a cell whose mixed axes
have equal lengths keeps goldilocks-data's numbering.

**Rung 1's open bound is ``None``.** goldilocks-data stores the upper
k-distance bound of rung 1, the Gamma-only mesh, as ``math.inf``. Core
stores ``None``: strict JSON has no infinity, and the ``inf`` in a
Gamma-only k_sampling record made ``/run`` fail and wrote ``Infinity``
into ``goldilocks.json`` (#137).

**A vacuum axis gets one division.** goldilocks-data divides all three
reciprocal lengths by the k-distance, which gave a monolayer two or three
k-points across its vacuum and a molecule in a box a 3x3x2 mesh, for no
change in energy and up to twice the cost for a monolayer, six times for
the box (#159). Here every lattice vector of the structure passed in that
``analysis.geometry.vacuum_axes`` names (an atom-free slab wider than
5 A) has one division in every mesh, whatever the k-distance. Only
periodic axes give change points, so a slab's rungs step its periodic
axes alone and are numbered differently from goldilocks-data's, and a
cell with vacuum along all three axes has one rung, Gamma-only at every
k-distance. A vacuum axis takes no part in the coupling above. The vacuum
is read from the cell the mesh is built for, never from the dimensionality
label, which calls bulk graphite '2d'; ``_Axes`` reads it once per call,
so a ladder reads it once.

**Naming: no ``k_spacing``.** v1 conflated two different reciprocal-length
conventions -- the solid-state (2*pi) convention (here, ``k_distance``,
matching AiiDA-QuantumESPRESSO) and the crystallographic (no 2*pi)
convention (here, ``k_line_density``) -- into one ambiguous ``k_spacing``
name. This module uses only ``k_distance``/``k_line_density``; the name
``k_spacing`` does not appear anywhere in v2.

**Not ported**: ``n_reduced_kpoints`` (above); goldilocks-data's own
``kindex_points`` helper, which builds
``goldilocks_data.sweeps.models.SweepPoint`` objects for its own
sweep-generation glue -- core has no such concept and must not take a
dependency on the ``goldilocks_data`` package; and its public
``generate_candidate_k_distances`` and ``mesh_to_k_line_density_interval``,
which core computes only inside ``build_gamma_kmesh_entries`` (``_Axes``).
Everything else here is the actual k-mesh math, kept behaviourally
identical apart from rung 1's ``None`` bound, the vacuum axes, the coupled
axes and the joined slivers (above); only the loose ``Any`` structure type
hint is tightened to pymatgen's own ``Structure`` (core, unlike data,
already requires pymatgen unconditionally), and one
``zip(xs[:-1], xs[1:])`` pairing is rewritten as ``itertools.pairwise`` to
satisfy core's lint config -- both mechanical, behaviour-preserving.

The ``is_metal``-based k_distance ceiling (metals >= 0.06 A^-1,
semiconductors/insulators >= 0.12 A^-1 as a cost safety net) and the
rung-can't-exceed-this-structure's-own-ladder-length clamp
(goldilocks-core-design.md:1732-1817) both gate *inputs into* this
ladder from the future ML tier (v2 epic 11) and are out of scope here --
this module only builds the ladder itself.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise

import numpy as np
from pymatgen.core import Lattice, Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from goldilocks_core.analysis.geometry import LATTICE_AXES, vacuum_axes
from goldilocks_core.analysis.symmetry import SYMPREC

MIN_K_DISTANCE = 0.03
"""Resolution floor for the k-mesh ladder, in Angstrom^-1 on the
solid-state (2*pi) reciprocal lattice -- the same convention as
AiiDA-QuantumESPRESSO k-distance. Change points denser than this are not
enumerated, and this value is part of every recorded ``kindex``: a rung
means nothing without it."""


@dataclass(frozen=True, slots=True)
class KMeshEntry:
    """One gamma-centered k-mesh entry in increasing kindex order.

    ``k_distance_interval`` is the ``(low, high)`` range of k-distances,
    in Angstrom^-1, that give ``mesh``. ``high`` is ``None`` only for rung
    1, the Gamma-only mesh, which every k-distance above ``low`` gives;
    ``low`` is 0 for a structure with no periodic axis.
    ``k_line_density_interval`` is the range of scalar k-line densities, in
    Angstrom^-1 on the crystallographic reciprocal lattice, that give
    ``mesh`` along every periodic axis, each axis read at the longest
    length it is coupled to (module docstring), or ``None`` when no single
    value does or there is no periodic axis."""

    kindex: int
    mesh: tuple[int, int, int]
    k_distance_interval: tuple[float, float | None]
    k_line_density_interval: tuple[float, float] | None
    k_pra: float


@dataclass(frozen=True, slots=True)
class _Axes:
    """The lattice vectors of a structure as the mesh sees them: the
    reciprocal length each is meshed from, in Angstrom^-1 on the
    solid-state (2*pi) reciprocal lattice (``lengths``) and on the
    crystallographic one (``line_lengths``), and whether each vector is
    periodic, that is, not one of the structure's
    ``analysis.geometry.vacuum_axes``. A periodic vector's length is the
    longest among the periodic vectors its point group couples it to
    (``_coupled``, module docstring), so coupled vectors carry the same
    length and step together; a vacuum vector keeps its own. Built once per
    call of ``k_distance_to_mesh`` or ``build_gamma_kmesh_entries``, so a
    whole ladder reads the vacuum and the point group once."""

    lengths: tuple[float, float, float]
    line_lengths: tuple[float, float, float]
    periodic: tuple[bool, bool, bool]

    @classmethod
    def from_structure(cls, structure: Structure) -> _Axes:
        vacuum = vacuum_axes(structure)
        a, b, c = (axis not in vacuum for axis in LATTICE_AXES)
        coupled = _coupled(structure, (a, b, c))
        return cls(
            lengths=_longest_coupled(
                _abc(structure.lattice.reciprocal_lattice), coupled
            ),
            line_lengths=_longest_coupled(
                _abc(structure.lattice.reciprocal_lattice_crystallographic), coupled
            ),
            periodic=(a, b, c),
        )

    def mesh(self, k_distance: float) -> tuple[int, int, int]:
        """``ceil(round(length_i / k_distance, 5))`` divisions, at least
        one, along each periodic axis, and one along each vacuum axis."""
        a, b, c = (
            max(1, math.ceil(round(length / k_distance, 5))) if periodic else 1
            for length, periodic in zip(self.lengths, self.periodic, strict=True)
        )
        return (a, b, c)

    def change_points(self, min_k_distance: float) -> list[float]:
        """Every k-distance at which some periodic axis changes its k-point
        count, largest first: ``mesh_i = ceil(length_i / k_distance)``
        steps from ``n`` to ``n + 1`` exactly at ``length_i / n``, rounded
        here to 8 decimals. Coupled axes share their length, so their
        change points coincide. A vacuum axis has one division at every
        k-distance and gives none (#159). ``min_k_distance``, the same floor
        for every axis, bounds the quotients, so all axes run out of change
        points together and none above the floor is skipped."""
        return sorted(
            {
                round(length / index, 8)
                for length, periodic in zip(self.lengths, self.periodic, strict=True)
                if periodic
                for index in range(1, max(1, math.floor(length / min_k_distance)) + 1)
            },
            reverse=True,
        )

    def line_density_interval(
        self, mesh: tuple[int, int, int]
    ) -> tuple[float, float] | None:
        """The intersection of the periodic axes' intervals
        ``[(n_i - 0.5) / |b_i|, (n_i + 0.5) / |b_i|]``, or ``None`` when it is
        empty or there is no periodic axis."""
        sampled = [
            (nk, length)
            for nk, length, periodic in zip(
                mesh, self.line_lengths, self.periodic, strict=True
            )
            if periodic
        ]
        if not sampled:
            return None
        lower = max(max(0.0, (nk - 0.5) / length) for nk, length in sampled)
        upper = min((nk + 0.5) / length for nk, length in sampled)
        if lower > upper:
            return None
        return (float(lower), float(upper))


def _abc(reciprocal: Lattice) -> tuple[float, float, float]:
    return (float(reciprocal.a), float(reciprocal.b), float(reciprocal.c))


def _coupled(structure: Structure, periodic: tuple[bool, bool, bool]) -> np.ndarray:
    """``coupled[i, j]``: whether lattice vectors i and j are the same or
    both periodic and mixed by the point group of ``structure``, directly
    (some rotation has a non-zero ``W[i, j]`` or ``W[j, i]``) or through
    the third periodic vector. The rotations are spglib's, in the lattice
    basis, searched on the species at ``SYMPREC``; a rotation's reciprocal
    action ``W^-T`` mixes the same pairs."""
    rotations = (
        SpacegroupAnalyzer(structure, symprec=SYMPREC).get_symmetry_dataset().rotations
    )
    mixed = np.any(rotations != 0, axis=0) & np.outer(periodic, periodic)
    linked = (mixed | mixed.T | np.eye(3, dtype=bool)).astype(int)
    return linked @ linked > 0


def _longest_coupled(
    lengths: tuple[float, float, float], coupled: np.ndarray
) -> tuple[float, float, float]:
    """Each length raised to the longest among those it is coupled to."""
    a, b, c = (
        max(length for length, linked in zip(lengths, row, strict=True) if linked)
        for row in coupled
    )
    return (a, b, c)


def k_distance_to_mesh(structure: Structure, k_distance: float) -> tuple[int, int, int]:
    """Convert a solid-state reciprocal spacing in Angstrom^-1 to a mesh
    the point group of ``structure`` maps onto itself:
    ``ceil(round(length_i / k_distance, 5))`` divisions, at least one, along
    each periodic lattice vector, ``length_i`` being the longest reciprocal
    length among the periodic vectors the point group couples it to (#163),
    and exactly one along each vacuum axis, whatever ``k_distance`` is
    (#159). Coupled vectors therefore have the same count, the larger one,
    and no periodic vector is sampled more coarsely than ``k_distance``."""
    return _Axes.from_structure(structure).mesh(k_distance)


def build_gamma_kmesh_entries(
    structure: Structure, min_k_distance: float = MIN_K_DISTANCE
) -> list[KMeshEntry]:
    """Build the unshifted, Gamma-inclusive k-mesh ladder for a structure.

    ``kindex`` is 1-based and rung 1 is the Gamma-only ``(1, 1, 1)`` mesh,
    which the first probe always yields because it sits above every
    periodic ``|b_i|``. Rung 1's interval is open above, so its upper bound
    is ``None``: a float ``inf`` there cannot be written as strict JSON
    (#137).

    Every rung has one division along each vacuum axis, and only the
    periodic axes step (#159). A structure with vacuum along all three axes
    has no change point, so rung 1, every k-distance above 0, is its only
    rung.

    Every rung is a distinct mesh the point group of ``structure`` maps
    onto itself: the axes it couples step together, as in
    ``k_distance_to_mesh`` (#163). Rungs are therefore numbered differently
    from goldilocks-data's ``ladder_1based.v2`` where coupled axes differ
    in length, CIF noise included (module docstring).

    The rung is an ordinal position on this structure's ladder and counts
    nothing. It equals the densest axis count only where the axes step
    together, as in a cubic cell.

    Every change point above ``min_k_distance`` is enumerated, so
    consecutive rungs differ by at most one k-point on each axis and no
    reachable mesh is skipped.

    Two change points of uncoupled axes closer than the 5-decimal rounding
    of ``k_distance_to_mesh`` resolves leave a sliver whose mesh repeats
    the rung above; the sliver joins that rung, which then ends at the
    sliver's lower bound, so each mesh has one ``kindex`` and the rungs'
    intervals tile the k-distance axis down to the floor. The ladder used
    to drop such a sliver, leaving a gap no rung covered (#163).

    No rung is reduced by symmetry (``advisors/n_irr_k.py`` reduces the
    mesh a step uses).
    """
    axes = _Axes.from_structure(structure)
    candidates = axes.change_points(min_k_distance)
    # Rung 1 holds above the largest change point, or at every k-distance
    # when no periodic axis gives one.
    top = candidates[0] if candidates else 0.0
    rungs: list[tuple[tuple[int, int, int], tuple[float, float | None]]] = [
        (axes.mesh(top + 1.0), (top, None))
    ]
    for upper, lower in pairwise(candidates):
        mesh = axes.mesh(0.5 * (upper + lower))
        high: float | None = upper
        if mesh == rungs[-1][0]:
            high = rungs.pop()[1][1]
        rungs.append((mesh, (lower, high)))

    return [
        KMeshEntry(
            kindex=kindex,
            mesh=mesh,
            k_distance_interval=interval,
            k_line_density_interval=axes.line_density_interval(mesh),
            k_pra=float(len(structure) * mesh[0] * mesh[1] * mesh[2]),
        )
        for kindex, (mesh, interval) in enumerate(rungs, start=1)
    ]
