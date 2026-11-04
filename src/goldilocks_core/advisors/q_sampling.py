"""q_sampling: the q-point mesh of the phonon tasks' ph.x step (#215).

ph.x computes the phonons on a Gamma-centred nq1 x nq2 x nq3 mesh of
q-points (``ldisp``), one dynamical matrix for each irreducible q-point,
and q2r.x turns those into force constants (QE 7.3 ``PHonon/PH``).

**The mesh** (``q_mesh``). A request ``q_grid`` is the mesh as given, and
wins over ``q_distance``. Otherwise ``q_distance`` (1/Angstrom, 2 pi
included), by default ``Q_DISTANCE`` = 0.3, the balanced
``qpoints_distance`` of aiida-quantumespresso's ph protocol
(``workflows/protocols/ph/base.yaml``; fast 0.6, stringent 0.2), becomes a
mesh through ``kmesh.k_distance_to_mesh`` on the written cell, as
``k_sampling`` meshes k: one division along each vacuum axis, and one
count, the larger, on the periodic axes the point group mixes.
``k_sampling`` raises the first step's k-mesh against this mesh
(``PhononKProtocol``).

**Refusals.** A mesh ph.x or q2r.x would stop on is recorded with a
``QRefusal``, for ``checks`` to refuse:

- ``breaks_symmetry``, for a ``q_grid``:
  - more than one division along a vacuum axis, as kmesh gives k;
  - a mesh some operation pw.x keeps does not map onto itself, on which
    ph.x stops with 'q-mesh breaks symmetry' (``check_q_points_sym``,
    ``PHonon/PH/q_points.f90:94-108``). An operation x -> W x in crystal
    coordinates turns q-points by W^T (QE's ``s``), so it maps the mesh
    onto itself exactly when (n_i W[j, i]) mod n_j is 0 for every i and j;
  - different counts on two periodic axes an operation mixes. ph.x accepts
    some of these (alpha-U's 4x8x4: 4 divides 8), but the phonon tasks
    raise a smearing run's k-mesh to a multiple of the q-mesh on each axis,
    which then can lose the symmetry (17x17x9 to 20x24x12); with equal
    counts it cannot.
- ``too_many_q_points``: q2r.x reads at most 1024 divisions along each axis
  and 1024 dynamical-matrix files, one per irreducible q-point
  (``PHonon/PH/do_q2r.f90:135-139``). pw.x's operations and their
  time-reversed forms lie in the lattice's point group, so an orbit holds
  at most 48 q-points, and a mesh of more than 48 x 1024 points has more
  than 1024 of them: ``q_grid`` is bounded so at input, and a computed mesh
  that large is refused without counting its q-points, which takes spglib
  about 16 bytes per point.

A computed mesh needs only ph.x's symmetry test, since kmesh gives the
periodic axes the point group mixes one count. It fails only where an
operation gives the image of a vacuum vector a component along a periodic
axis, as a vacuum vector that is not perpendicular to the periodic axes
allows (a slab whose c leans off its normal): kmesh leaves vacuum axes out
of that coupling. The record is then ``Blocked``, its cause naming the
remedy, a cell whose vacuum vectors are perpendicular to the periodic axes.

**Counts.** A mesh that passes is reduced as ph.x's ``kpoint_grid``
reduces it under pw.x's operations (``pw_symmetry.irreducible_kpoints``,
``PHonon/PH/q_points.f90:42-48``): ``n_irr_q`` q-points. ``work`` is
ph.x's own estimate of its run in scf-equivalents, (3 nat + 1) nsym /
nsymq summed over them (``check_initial_status.f90:391-406``), nsymq being
the number of operations that map q onto q plus a reciprocal lattice
vector, a time-reversed one acting as -W^T (``smallg_q``,
``LR_Modules/set_small_group_of_q.f90:146-157``). On zincblende AlAs at
4x4x4, QE's PHonon example02, that is 8 q-points and a work of 336.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Annotated, Literal

import numpy as np
from pydantic import Field, field_validator
from pymatgen.core import Structure

from goldilocks_core.advisors.magnetic_config import MagneticCell
from goldilocks_core.analysis.geometry import LATTICE_AXES, vacuum_axes
from goldilocks_core.inputs.overrides import HumanInput
from goldilocks_core.kmesh import k_distance_to_mesh
from goldilocks_core.pw_symmetry import (
    PwRotations,
    irreducible_kpoints,
    mixing_axis_pairs,
    pw_rotations,
)
from goldilocks_core.resolution import (
    Blocked,
    FieldState,
    Provenance,
    Resolved,
    Warning,
    blocked_by,
    field_sources_from,
)

Q_DISTANCE = 0.3
"""1/Angstrom, 2 pi included: the default q-point spacing (module
docstring)."""

MAX_Q_DIVISIONS = 1024
"""q2r.x's largest number of divisions along an axis
(``PHonon/PH/do_q2r.f90:135-137``)."""

MAX_IRREDUCIBLE_Q = 1024
"""q2r.x's largest number of dynamical-matrix files, one per irreducible
q-point (``PHonon/PH/do_q2r.f90:138-139``)."""

MAX_Q_MESH_POINTS = 48 * MAX_IRREDUCIBLE_Q
"""The most points a mesh can have without always holding more than
``MAX_IRREDUCIBLE_Q`` irreducible q-points (module docstring)."""

_SAME_POINT = 1e-5
"""``smallg_q``'s ``accep``: how close to a reciprocal lattice vector the
difference of two q-points in crystal coordinates must be for them to
count as one."""

_DEFAULT_NOTE = (
    "Default q_distance 0.3 1/Angstrom: aiida-quantumespresso's ph protocol, "
    "balanced (fast 0.6, stringent 0.2)."
)

GRID_AND_DISTANCE_WARNING = Warning(
    code="q_sampling.grid_and_distance_conflict",
    level="info",
    category="q_sampling",
    message=(
        "both q_grid and q_distance were given; q_grid wins outright and "
        "q_distance is ignored."
    ),
)

WARNING_CATALOGUE = (GRID_AND_DISTANCE_WARNING,)
"""Every warning code this module can emit -- ``capabilities.py``'s
``warnings[]`` catalogue aggregates one of these tuples per advisor."""

QRefusalKind = Literal["breaks_symmetry", "too_many_q_points"]


@dataclass(frozen=True, slots=True)
class QRefusal:
    """Why ph.x or q2r.x would stop on the mesh (module docstring):
    ``kind`` names the rule and ``cause`` says how the mesh breaks it."""

    kind: QRefusalKind
    cause: str


@dataclass(frozen=True, slots=True)
class QSamplingDecision:
    """The q-point mesh of the ph.x step (module docstring). ``q_distance``
    is the spacing it was built from, ``None`` for a request ``q_grid``.
    ``n_irr_q`` is the number of irreducible q-points, ``None`` when the
    mesh was refused before they were counted; ``work`` is ph.x's estimate
    of its run in scf-equivalents, ``None`` for a refused mesh."""

    mesh: tuple[int, int, int]
    q_distance: float | None
    n_irr_q: int | None
    work: int | None
    refusal: QRefusal | None = None
    warnings: tuple[Warning, ...] = ()


_Divisions = Annotated[int, Field(ge=1, le=MAX_Q_DIVISIONS)]


class QSamplingHumanInput(HumanInput):
    q_grid: tuple[_Divisions, _Divisions, _Divisions] | None = None
    """The q-point mesh ph.x runs on, Gamma-centred: nq1, nq2 and nq3,
    within q2r.x's limits (module docstring)."""
    q_distance: float | None = Field(default=None, gt=0)
    """1/Angstrom, as ``KSamplingHumanInput.k_distance``."""

    @field_validator("q_grid")
    @classmethod
    def _within_q2r_x_limits(
        cls, q_grid: tuple[int, int, int] | None
    ) -> tuple[int, int, int] | None:
        if q_grid is not None and math.prod(q_grid) > MAX_Q_MESH_POINTS:
            raise ValueError(
                f"q_grid {_grid(q_grid)} has {math.prod(q_grid)} points; q2r.x "
                f"reads at most {MAX_IRREDUCIBLE_Q} dynamical matrices, one per "
                "irreducible q-point, and a q-mesh of more than "
                f"{MAX_Q_MESH_POINTS} points always has more"
            )
        return q_grid


def q_mesh(
    structure: Structure, human: QSamplingHumanInput | None = None
) -> tuple[int, int, int]:
    """The q-point mesh for the written cell ``structure`` (module
    docstring): the human ``q_grid`` as given, else the mesh of the human
    ``q_distance``, else of ``Q_DISTANCE``."""
    human = human or QSamplingHumanInput()
    if human.q_grid is not None:
        return human.q_grid
    return k_distance_to_mesh(structure, _q_distance(human))


def q_sampling(
    cell: FieldState[MagneticCell], human: QSamplingHumanInput | None = None
) -> FieldState[QSamplingDecision]:
    """The q-point mesh of the written ``cell`` (``q_mesh``), its refusal,
    irreducible q-points and work under the operations pw.x keeps in it
    (module docstring). ``Blocked`` when ``cell`` is not resolved, or when
    the mesh built from a spacing is not symmetric."""
    human = human or QSamplingHumanInput()
    if not cell.ok:
        return Blocked(by=blocked_by(cell))
    structure = cell.value.structure
    rotations = pw_rotations(structure, cell.value.moment_axis)
    mesh = q_mesh(structure, human)
    requested = human.q_grid is not None
    if requested:
        refusal = _grid_refusal(structure, rotations, mesh)
    elif _maps_onto_itself(rotations, mesh):
        refusal = _size_refusal(mesh, human)
    else:
        return Blocked(by=_leaning_vacuum(structure, rotations, mesh, human))
    decision = QSamplingDecision(
        mesh=mesh,
        q_distance=None if requested else _q_distance(human),
        n_irr_q=None,
        work=None,
        refusal=refusal,
        warnings=(
            (GRID_AND_DISTANCE_WARNING,)
            if requested and human.q_distance is not None
            else ()
        ),
    )
    if refusal is None:
        decision = _counted(decision, rotations, len(structure), human)
    return Resolved(decision, _provenance(human))


def _q_distance(human: QSamplingHumanInput) -> float:
    return Q_DISTANCE if human.q_distance is None else human.q_distance


def _grid(mesh: tuple[int, ...]) -> str:
    """``mesh`` as text, e.g. '9x8x5'."""
    return "x".join(str(count) for count in mesh)


def _described(mesh: tuple[int, int, int], human: QSamplingHumanInput) -> str:
    """How a cause names ``mesh``: by the setting it came from."""
    if human.q_grid is not None:
        return f"q_grid {_grid(mesh)}"
    return f"the {_grid(mesh)} q-mesh of q_distance {_q_distance(human):g} 1/Angstrom"


def _vacuum(structure: Structure) -> tuple[int, ...]:
    """The indices of ``structure``'s vacuum axes."""
    return tuple(LATTICE_AXES.index(axis) for axis in vacuum_axes(structure))


def _named(axes: list[int]) -> str:
    """Lattice axes by letter, e.g. 'a and b'."""
    letters = [LATTICE_AXES[axis] for axis in axes]
    if len(letters) == 1:
        return letters[0]
    return f"{', '.join(letters[:-1])} and {letters[-1]}"


def _maps_onto_itself(rotations: PwRotations, mesh: tuple[int, int, int]) -> bool:
    """ph.x's ``check_q_points_sym``: whether every operation in
    ``rotations`` maps the Gamma-centred ``mesh`` onto itself,
    (n_i W[j, i]) mod n_j being 0 for every i and j (module docstring)."""
    counts = np.array(mesh)
    return bool(np.all(rotations.rotations * counts % counts[:, None] == 0))


def _grid_refusal(
    structure: Structure, rotations: PwRotations, mesh: tuple[int, int, int]
) -> QRefusal | None:
    """Why the request ``q_grid`` ``mesh`` breaks the symmetry ph.x and the
    phonon k-mesh need (module docstring), or ``None``."""
    vacuum = _vacuum(structure)
    grid = f"q_grid {_grid(mesh)}"
    crowded = [axis for axis in vacuum if mesh[axis] != 1]
    if crowded:
        along = " and ".join(
            f"{mesh[axis]} divisions along vacuum axis {LATTICE_AXES[axis]}"
            for axis in crowded
        )
        return QRefusal(
            "breaks_symmetry", f"{grid} has {along}; a vacuum axis takes one"
        )
    if not _maps_onto_itself(rotations, mesh):
        return QRefusal(
            "breaks_symmetry",
            f"{grid} is not mapped onto itself by the {len(rotations)} symmetry "
            "operations pw.x keeps in the written cell, so ph.x would stop with "
            "'q-mesh breaks symmetry'",
        )
    pairs = [
        (i, j)
        for i, j in mixing_axis_pairs(rotations)
        if i not in vacuum and j not in vacuum
    ]
    unequal = [sorted(pair) for pair in pairs if mesh[pair[0]] != mesh[pair[1]]]
    if not unequal:
        return None
    return QRefusal(
        "breaks_symmetry",
        f"{grid} gives different counts to axes {_named(unequal[0])}, which a "
        "symmetry operation mixes: ph.x accepts it, but the phonon k-mesh, raised "
        "against it, can then lose the symmetry. Give mixed axes equal counts, "
        f"such as {_grid(_equalized(mesh, pairs))}",
    )


def _equalized(
    mesh: tuple[int, int, int], pairs: list[tuple[int, int]]
) -> tuple[int, int, int]:
    """``mesh`` with the axes ``pairs`` link, directly or through the third,
    raised to their largest count: two passes settle a chain of three."""
    counts = list(mesh)
    for _ in range(2):
        for i, j in pairs:
            counts[i] = counts[j] = max(counts[i], counts[j])
    return counts[0], counts[1], counts[2]


def _size_refusal(
    mesh: tuple[int, int, int], human: QSamplingHumanInput
) -> QRefusal | None:
    """The refusal of a computed ``mesh`` too large to count (module
    docstring), or ``None``."""
    points = math.prod(mesh)
    if max(mesh) <= MAX_Q_DIVISIONS and points <= MAX_Q_MESH_POINTS:
        return None
    return QRefusal(
        "too_many_q_points",
        f"{_described(mesh, human)} ({points} points) is beyond q2r.x's limits: "
        f"at most {MAX_Q_DIVISIONS} divisions along each axis, and at most "
        f"{MAX_IRREDUCIBLE_Q} dynamical matrices, one per irreducible q-point, "
        f"which a q-mesh of more than {MAX_Q_MESH_POINTS} points always exceeds",
    )


def _leaning_vacuum(
    structure: Structure,
    rotations: PwRotations,
    mesh: tuple[int, int, int],
    human: QSamplingHumanInput,
) -> str:
    """Why the computed ``mesh`` is not symmetric: operations that give the
    image of a vacuum vector a component along a periodic axis (module
    docstring)."""
    vacuum = _vacuum(structure)
    pairs = [
        (i, j)
        for i, j in mixing_axis_pairs(rotations)
        if i in vacuum and j not in vacuum
    ]
    leaning = sorted({i for i, _ in pairs})
    axes, vectors = (
        ("vacuum axis", "vacuum vector")
        if len(leaning) == 1
        else ("vacuum axes", "vacuum vectors")
    )
    return (
        f"{_described(mesh, human)} is not mapped onto itself by the "
        f"{len(rotations)} symmetry operations pw.x keeps in the written cell, so "
        f"ph.x would stop with 'q-mesh breaks symmetry': some of them turn {axes} "
        f"{_named(leaning)} into a vector with components along "
        f"{_named(sorted({j for _, j in pairs}))}, which a vacuum vector that is "
        "not perpendicular to the periodic axes allows. Upload the cell with its "
        f"{vectors} perpendicular to them."
    )


def _counted(
    decision: QSamplingDecision,
    rotations: PwRotations,
    atoms: int,
    human: QSamplingHumanInput,
) -> QSamplingDecision:
    """``decision`` with its irreducible q-points counted, and refused when
    q2r.x would not read them all, otherwise with ph.x's work estimate
    (module docstring)."""
    points = irreducible_kpoints(rotations, decision.mesh, (0, 0, 0))
    if len(points) > MAX_IRREDUCIBLE_Q:
        return replace(
            decision,
            n_irr_q=len(points),
            refusal=QRefusal(
                "too_many_q_points",
                f"{_described(decision.mesh, human)} has {len(points)} irreducible "
                f"q-points, and q2r.x reads at most {MAX_IRREDUCIBLE_Q} dynamical "
                "matrices, one per irreducible q-point",
            ),
        )
    return replace(decision, n_irr_q=len(points), work=_work(rotations, points, atoms))


def _work(rotations: PwRotations, points: np.ndarray, atoms: int) -> int:
    """ph.x's work estimate for the irreducible q-``points`` of a cell of
    ``atoms`` atoms: (3 atoms + 1) nsym / nsymq summed over them, nsymq
    counting the operations t W^T that map q onto q plus a reciprocal
    lattice vector, t = -1 for a time-reversed one (module docstring)."""
    signs = np.where(rotations.time_reversed, -1, 1)
    images = np.einsum("o,oji,pj->opi", signs, rotations.rotations, points)
    offsets = images - points[None, :, :]
    fixed = np.all(np.abs(offsets - np.rint(offsets)) < _SAME_POINT, axis=2)
    return int(np.sum((3 * atoms + 1) * (len(rotations) // fixed.sum(axis=0))))


def _provenance(human: QSamplingHumanInput) -> Provenance:
    """``q_grid`` when the request set it, else ``q_distance``: ``human``
    when the request set it, else ``heuristic`` with the protocol it comes
    from. The mesh follows the written cell (``magnetic``)."""
    setting = "q_grid" if human.q_grid is not None else "q_distance"
    default = human.q_grid is None and human.q_distance is None
    return Provenance.from_field_sources(
        field_sources_from(human, None, fields=(setting,)),
        source_note=_DEFAULT_NOTE if default else None,
        derived_from=("magnetic",),
    )
