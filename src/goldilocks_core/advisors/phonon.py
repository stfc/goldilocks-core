"""phonon: the phonon tasks' ph.x, q2r.x and matdyn.x settings, the path of
their dispersion, and the notices of a phonon run (#215).

**ph.x** (``phonon_settings``). tr2_ph 1e-18, alpha_mix(1) 0.4 and nmix_ph
8, each the default of its own setting, are aiida-quantumespresso's balanced
ph protocol (``workflows/protocols/ph/base.yaml``; tr2_ph 1e-16 fast, 1e-20
stringent); Quantum ESPRESSO's own defaults are 1e-12, 0.7 and 4. A request
value is checked as ph.x checks it, tr2_ph > 0 and 0 <= alpha_mix <= 1 (QE
7.3 ``PHonon/PH/phq_readin.f90:409-416``), and nmix_ph, the number of
earlier iterations mixed, must be at least 1. The record carries the run's
notices (``phonon_notices``).

**q2r.x and matdyn.x** (``q2r_settings``). ``asr`` is the acoustic sum rule
both apply, q2r.x to the effective charges and matdyn.x to the force
constants. The default is 'simple', which corrects the on-site force
constants (``PHonon/PH/matdyn.f90:1355-1392``) and so shifts every q alike;
'crystal', INPUT_MATDYN's "optimized correction of the force constants
(projection)", is used when the request sets it (#219). The dominant
violation, the FFT-grid (egg-box) error of the exchange-correlation term, is
on-site and the same at every q. The 'crystal' projection spreads its
correction evenly over the force constants of the q-mesh supercell, which
in q-space is zero at every q-mesh point but Gamma, so it leaves that
violation at every other computed q: on bcc Li it turned a stable Gamma-N
branch imaginary (-1.16 THz) that 'simple' keeps real. q2r.x applies the
same rule to the effective charges only (``do_q2r.f90:214-215``), where
'simple' subtracts their mean (``:697-708``), the correction 'crystal' gives
a 3D crystal. ``loto_2d`` is set with isolation=slab, Quantum ESPRESSO's 2D
Coulomb truncation: q2r.x and matdyn.x then take the 2D non-analytic term
(``PHonon/PH/rigid.f90:129-137``; PHonon example17; Sohier et al., Phys.
Rev. B 96, 075448 (2017)).

**The phonon DOS** (``phonon_dos_settings``). matdyn.x interpolates the
force constants on a Gamma-centred mesh of ``dos_q_distance`` (1/Angstrom,
2 pi included), by default ``DOS_Q_DISTANCE`` = 0.10, the dos task's nscf
spacing (aiida-quantumespresso's ``pdos.yaml``), built by
``kmesh.k_distance_to_mesh`` on the written cell as the q-mesh is: one
division along each vacuum axis and one count on the periodic axes the
point group mixes, so that the point group maps the mesh onto itself, as
matdyn.x's tetrahedra need (``matdyn.f90:2428``, ``PW/src/tetra.f90:160``,
``:170``); a slab whose vacuum vector leans off its normal has no such mesh,
and its q record is blocked. matdyn.x only interpolates, so a fine mesh is
cheap. The DOS is tabulated every ``DOS_DELTA_E`` = 1 cm^-1, matdyn.x's own
default.

**The dispersion** (``dispersion_path``). matdyn.x follows the band task's
path of the written cell (``advisors/k_path.py``), read as the rows pw.x
reads from a K_POINTS crystal_b card (``q_in_band_form``,
``q_in_cryst_coord``) and expanded by the same routine
(``Modules/generate_k_along_lines.f90``). Where the first step runs on
fixed occupations, so that ph.x computes the effective charges
(``PHonon/PH/prepare_q.f90:139-162``), and loto_2d is off, under which
matdyn.x skips this (``matdyn.f90:621``), matdyn.x adds the non-analytic
(LO-TO) term at every point that is q = 0 to within 1e-6 in crystal
coordinates, along the direction from the point before, or from the point
after for the first point and for one whose predecessor is exactly 0
(``matdyn.f90:621-651``). There the path differs from the band task's in
two ways, and the record's ``source_note`` says so:

- each segment that ends at Gamma takes the fewest steps, at least its own,
  with which matdyn.x lands on Gamma exactly: its last point is
  x + (delta * n) * (0 - x), delta = 1 / n, which is 0 only where
  fl(fl(1/n) n) = 1, so 49, 98, 103, ... steps are raised, by at most 4 up
  to 4000 steps. A point about 1e-16 off Gamma still counts as q = 0, and
  the dipole sum adds the term there a second time
  (``rigid.f90:195-217``);
- each Gamma inside a branch ends that branch and starts the next, so the
  rows list it twice with a count of 0 between, as matdyn.x's header
  advises (``matdyn.f90:148-153``): the first copy takes the arriving
  direction, and the second, whose predecessor is exactly 0, the leaving
  one. The path's first Gamma takes the leaving direction already, and a
  Gamma that ends a branch has only the arriving one.

``n_kpoints`` is then matdyn.x's number of points (``matdyn.f90:539-542``):
the band path's, plus one per Gamma split and the steps added into Gamma.
A molecule or cluster in a box has no dispersion: its record is
``Unavailable`` with ``NO_DISPERSION``.

**Notices** (``phonon_notices``), carried by the phonon record:

- ``phonon.relax_first``, for the phonon task, whose first step is an scf:
  DFPT takes second derivatives at the geometry it is given, here the
  written one.
- ``phonon.vc_relax_input_cell``, for vc-relax-phonon: the q- and k-meshes
  and the dispersion path are built on the input cell, and the vc-relax
  makes one pass. matdyn.x applies the path's crystal coordinates to the
  relaxed cell's reciprocal vectors, which keeps every vertex the same
  special point except where special points depend on the axis ratios and
  angles: in BCT, ORCF, ORCI, ORCC, RHL, MCL and MCLC cells and in
  centred-rectangular and oblique layers.
- ``phonon.slab_lo_to_needs_2d_truncation``: a slab with periodic boundaries
  and fixed occupations, whose non-analytic term is then the 3D one, which
  depends on the vacuum width.
- ``phonon.magnetic_noncollinear_experimental``: spin-orbit coupling with
  spin polarization, which QE's PHonon examples describe as experimental
  (example07; Urru and Dal Corso, Phys. Rev. B 100, 045115 (2019)).
- ``phonon.hubbard_experimental``: a Hubbard U, likewise (example18; Floris
  et al., Phys. Rev. B 101, 064305 (2020)).
- ``phonon.d3_two_body``: DFT-D3. d3hess.x builds the D3 Hessian from
  two-body terms only (``dft-d3/dftd3_qe.f90:217``, ``:256-281``), so the
  first step writes dftd3_threebody = .false. and its energy, forces and
  relaxation use the same D3.

A notice whose fact is not resolved is not raised: the unresolved record
blocks the run on its own. ``LOOSE_FORCE_THRESHOLD_WARNING`` is the phonon
tasks' relaxation warning, carried by the relax record
(``advisors/relax.py``'s ``RelaxProtocol``).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, replace
from typing import Literal

from pydantic import Field

from goldilocks_core.advisors.boundary import BoundaryFacts
from goldilocks_core.advisors.hubbard_u import HubbardUDecision
from goldilocks_core.advisors.k_path import (
    KPathDecision,
    KPathHumanInput,
    PathBranch,
    k_path,
)
from goldilocks_core.advisors.magnetic_config import MagneticCell, MagneticConfigFacts
from goldilocks_core.advisors.occupations import OccupationsDecision
from goldilocks_core.analysis.geometry import GeometryFacts
from goldilocks_core.inputs.overrides import HumanInput
from goldilocks_core.kmesh import k_distance_to_mesh
from goldilocks_core.resolution import (
    Blocked,
    FieldState,
    Provenance,
    Resolved,
    Unavailable,
    Warning,
    blocked_by,
    field_sources_from,
)

Asr = Literal["crystal", "simple"]
"""The acoustic sum rules q2r.x and matdyn.x apply here (module docstring).
matdyn.x's 'all', 'one-dim' and 'zero-dim' add rotational conditions these
tasks do not offer, and 'no' leaves the acoustic frequencies at Gamma
non-zero."""

DEFAULT_TR2_PH = 1e-18
DEFAULT_ALPHA_MIX = 0.4
DEFAULT_NMIX_PH = 8
"""aiida-quantumespresso's balanced ph protocol (module docstring)."""

DOS_Q_DISTANCE = 0.10
"""1/Angstrom, 2 pi included: the default phonon-DOS mesh spacing (module
docstring)."""

DOS_DELTA_E = 1.0
"""cm^-1: the phonon DOS's energy step, matdyn.x's own default."""

AIIDA_PROTOCOLS_CITATION = "S. P. Huber et al., npj Comput. Mater. 7, 136 (2021)"
"""The aiida-quantumespresso protocols the phonon tasks' ph.x settings and
relaxation threshold come from."""

PHONON_CITATIONS = (
    AIIDA_PROTOCOLS_CITATION,
    "S. Baroni et al., Rev. Mod. Phys. 73, 515 (2001)",
)
"""What the phonon record cites when it uses a default: the protocols and
density-functional perturbation theory."""

_PH_NOTE = (
    "Defaults tr2_ph 1e-18, alpha_mix(1) 0.4 and nmix_ph 8: "
    "aiida-quantumespresso's ph protocol, balanced (tr2_ph 1e-16 fast, 1e-20 "
    "stringent); Quantum ESPRESSO's own are 1e-12, 0.7 and 4."
)

_ASR_NOTE = (
    "Default asr 'simple', which corrects the on-site force constants at every "
    "q, where the dominant sum-rule violation, the FFT-grid error, sits. "
    "matdyn.x's 'crystal' projection corrects that violation at Gamma only."
)

_DOS_NOTE = (
    "Default dos_q_distance 0.10 1/Angstrom: the dos task's nscf spacing, "
    "aiida-quantumespresso's pdos protocol, balanced. matdyn.x only "
    "interpolates the force constants, so a fine mesh is cheap."
)

NO_DISPERSION = "a molecule or cluster in a box has no phonon dispersion"
"""The dispersion record's reason for a written cell with vacuum along a, b
and c."""

_DISPERSION_NOTE = (
    "matdyn.x adds the non-analytic (LO-TO) term on this run: Gamma inside a "
    "branch is listed twice, ending one branch and starting the next, so that "
    "the term takes the direction of each side, and a segment that ends at "
    "Gamma takes the fewest steps, at least its own, with which matdyn.x lands "
    "on Gamma exactly."
)

_GAMMA = (0.0, 0.0, 0.0)
"""Gamma's crystal coordinates as ``k_path`` records them: matdyn.x tests a
point's predecessor for exactly 0 (module docstring)."""

RELAX_FIRST_NOTE = Warning(
    code="phonon.relax_first",
    level="info",
    category="phonon",
    message=(
        "the phonons are computed at the geometry as written, and leftover "
        "forces shift their frequencies, soft modes most. Relax it first with "
        "the same settings, hubbard_projectors included, and forc_conv_thr at "
        "most 1e-4 Ry/Bohr, or use the relax-phonon or vc-relax-phonon task, "
        "which relax in the same job; the scf prints the forces and the stress "
        "on the written geometry."
    ),
)

LOOSE_FORCE_THRESHOLD_WARNING = Warning(
    code="phonon.loose_force_threshold",
    level="warning",
    category="relax",
    message=(
        "the requested forc_conv_thr is looser than 1e-4 Ry/Bohr, the phonon "
        "tasks' relaxation threshold (aiida-quantumespresso's balanced "
        "protocol): the phonons are computed at the relaxed geometry, and "
        "leftover forces shift their frequencies, soft modes most. Leave "
        "forc_conv_thr unset for 1e-4, or set a smaller value."
    ),
)

VC_RELAX_INPUT_CELL_NOTE = Warning(
    code="phonon.vc_relax_input_cell",
    level="info",
    category="phonon",
    message=(
        "the q-mesh, the k-mesh and the dispersion path were built on the input "
        "cell. The meshes keep their divisions on the relaxed cell, so their "
        "spacing changes with it. The path keeps its vertices' crystal "
        "coordinates, which matdyn.x applies to the relaxed cell's reciprocal "
        "vectors: they stay the same special points except in BCT, ORCF, ORCI, "
        "ORCC, RHL, MCL and MCLC cells and centred-rectangular or oblique "
        "layers, whose special points move with the axis ratios and angles, "
        "and a cell near a boundary between Setyawan-Curtarolo subtypes can "
        "change subtype. The vc-relax makes one pass: no relaxation follows its "
        "final scf on the relaxed cell, so check the forces and the stress that "
        "scf prints, and run the task again from the relaxed structure if they "
        "are large."
    ),
)

SLAB_LO_TO_WARNING = Warning(
    code="phonon.slab_lo_to_needs_2d_truncation",
    level="warning",
    category="phonon",
    message=(
        "the slab has periodic boundaries and fixed occupations, so q2r.x and "
        "matdyn.x build the long-range (LO-TO) part of its force constants in "
        "the 3D form, which for a two-dimensional material depends on the "
        "vacuum width. Set isolation=slab, Quantum ESPRESSO's 2D Coulomb "
        "truncation, with which they use the 2D form instead."
    ),
)

MAGNETIC_NONCOLLINEAR_WARNING = Warning(
    code="phonon.magnetic_noncollinear_experimental",
    level="warning",
    category="phonon",
    message=(
        "spin-orbit coupling with spin polarization: Quantum ESPRESSO's PHonon "
        "examples describe the phonons of magnetic systems with spin-orbit "
        "coupling as experimental (Urru and Dal Corso, Phys. Rev. B 100, "
        "045115 (2019)); check them with care."
    ),
)

HUBBARD_EXPERIMENTAL_WARNING = Warning(
    code="phonon.hubbard_experimental",
    level="warning",
    category="phonon",
    message=(
        "a Hubbard U is applied: Quantum ESPRESSO's PHonon examples describe "
        "phonons with a Hubbard U (DFPT+U) as experimental (Floris et al., "
        "Phys. Rev. B 101, 064305 (2020)); check them with care."
    ),
)

D3_TWO_BODY_NOTE = Warning(
    code="phonon.d3_two_body",
    level="info",
    category="phonon",
    message=(
        "DFT-D3 is used, and d3hess.x builds the D3 part of the dynamical "
        "matrices from two-body terms only, so the first step writes "
        "dftd3_threebody = .false.: its energy, forces and any relaxation use "
        "the same two-body D3. The relax and vc-relax tasks keep the three-body "
        "terms, so a geometry they relaxed is not at this equilibrium; "
        "relax-phonon and vc-relax-phonon relax with two-body D3."
    ),
)

WARNING_CATALOGUE = (
    RELAX_FIRST_NOTE,
    LOOSE_FORCE_THRESHOLD_WARNING,
    VC_RELAX_INPUT_CELL_NOTE,
    SLAB_LO_TO_WARNING,
    MAGNETIC_NONCOLLINEAR_WARNING,
    HUBBARD_EXPERIMENTAL_WARNING,
    D3_TWO_BODY_NOTE,
)
"""Every warning code this module can emit -- ``capabilities.py``'s
``warnings[]`` catalogue aggregates one of these tuples per advisor. Each
category is the record that carries the code: the relax record the
force-threshold warning, the phonon record the rest."""


@dataclass(frozen=True, slots=True)
class PhononDecision:
    """ph.x's convergence settings (module docstring) and the notices of
    the run (``phonon_notices``)."""

    tr2_ph: float
    alpha_mix: float
    nmix_ph: int
    warnings: tuple[Warning, ...] = ()


@dataclass(frozen=True, slots=True)
class Q2rDecision:
    """The acoustic sum rule and the 2D non-analytic term q2r.x and matdyn.x
    apply (module docstring)."""

    asr: Asr
    loto_2d: bool


@dataclass(frozen=True, slots=True)
class PhononDosDecision:
    """matdyn.x's phonon-DOS mesh, the spacing it was built from and the
    DOS's energy step in cm^-1 (module docstring)."""

    mesh: tuple[int, int, int]
    dos_q_distance: float
    delta_e: float


class PhononHumanInput(HumanInput):
    tr2_ph: float | None = Field(default=None, gt=0)
    """The threshold of ph.x's self-consistent linear response."""
    alpha_mix: float | None = Field(default=None, ge=0, le=1)
    """ph.x's mixing factor, alpha_mix(1)."""
    nmix_ph: int | None = Field(default=None, ge=1)
    """The number of earlier iterations ph.x mixes."""


class Q2rHumanInput(HumanInput):
    asr: Asr | None = None
    """The acoustic sum rule q2r.x and matdyn.x apply."""


class PhononDosHumanInput(HumanInput):
    dos_q_distance: float | None = Field(default=None, gt=0)
    """1/Angstrom, as ``QSamplingHumanInput.q_distance``."""


def phonon_settings(
    human: PhononHumanInput | None = None, notices: tuple[Warning, ...] = ()
) -> FieldState[PhononDecision]:
    """ph.x's tr2_ph, alpha_mix(1) and nmix_ph: each the request's, else
    the balanced protocol's (module docstring), with ``notices``
    (``phonon_notices``) as the record's warnings. When any default is used
    the record names the protocol and cites ``PHONON_CITATIONS``."""
    human = human or PhononHumanInput()
    decision = PhononDecision(
        tr2_ph=DEFAULT_TR2_PH if human.tr2_ph is None else human.tr2_ph,
        alpha_mix=DEFAULT_ALPHA_MIX if human.alpha_mix is None else human.alpha_mix,
        nmix_ph=DEFAULT_NMIX_PH if human.nmix_ph is None else human.nmix_ph,
        warnings=notices,
    )
    field_sources = field_sources_from(
        human, None, fields=("tr2_ph", "alpha_mix", "nmix_ph")
    )
    protocol = (
        {"source_note": _PH_NOTE, "citations": PHONON_CITATIONS}
        if "heuristic" in field_sources.values()
        else {}
    )
    return Resolved(decision, Provenance.from_field_sources(field_sources, **protocol))


def phonon_notices(
    first_step: Literal["scf", "relax", "vc-relax"],
    occupations: FieldState[OccupationsDecision],
    geometry: FieldState[GeometryFacts],
    boundary: FieldState[BoundaryFacts],
    magnetic: FieldState[MagneticConfigFacts],
    hubbard: FieldState[HubbardUDecision],
    *,
    d3: bool,
) -> tuple[Warning, ...]:
    """The notices of a phonon task whose first step is ``first_step``
    (module docstring), from the first step's ``occupations``, the written
    cell's ``geometry``, and the ``boundary``, ``magnetic`` and ``hubbard``
    records; ``d3`` is whether the first step writes DFT-D3. A notice whose
    fact is not resolved is left out."""
    candidates = (
        RELAX_FIRST_NOTE if first_step == "scf" else None,
        VC_RELAX_INPUT_CELL_NOTE if first_step == "vc-relax" else None,
        SLAB_LO_TO_WARNING
        if _periodic_fixed_slab(occupations, geometry, boundary)
        else None,
        MAGNETIC_NONCOLLINEAR_WARNING if _magnetic_spin_orbit(magnetic) else None,
        HUBBARD_EXPERIMENTAL_WARNING if hubbard.ok and hubbard.value.u_values else None,
        D3_TWO_BODY_NOTE if d3 else None,
    )
    return tuple(notice for notice in candidates if notice is not None)


def _periodic_fixed_slab(
    occupations: FieldState[OccupationsDecision],
    geometry: FieldState[GeometryFacts],
    boundary: FieldState[BoundaryFacts],
) -> bool:
    """Whether the written cell is a slab with periodic boundaries and fixed
    occupations."""
    return (
        occupations.ok
        and occupations.value.occupations == "fixed"
        and geometry.ok
        and geometry.value.slab is not None
        and boundary.ok
        and boundary.value.isolation == "periodic"
    )


def _magnetic_spin_orbit(magnetic: FieldState[MagneticConfigFacts]) -> bool:
    """Whether the run has spin-orbit coupling with spin polarization."""
    return (
        magnetic.ok
        and magnetic.value.spin_orbit_enabled
        and magnetic.value.spin_polarized
    )


def q2r_settings(
    boundary: FieldState[BoundaryFacts],
    human: Q2rHumanInput | None = None,
) -> FieldState[Q2rDecision]:
    """q2r.x's and matdyn.x's acoustic sum rule, 'simple' unless the request
    sets one, and ``loto_2d`` from ``boundary`` (module docstring).
    ``Blocked`` when ``boundary`` is not resolved."""
    human = human or Q2rHumanInput()
    if not boundary.ok:
        return Blocked(by=blocked_by(boundary))
    decision = Q2rDecision(
        asr=human.asr or "simple",
        loto_2d=boundary.value.isolation == "slab",
    )
    return Resolved(
        decision,
        Provenance.from_field_sources(
            field_sources_from(human, None, fields=("asr",)),
            source_note=_ASR_NOTE if human.asr is None else None,
            derived_from=("boundary",),
        ),
    )


def phonon_dos_settings(
    cell: FieldState[MagneticCell], human: PhononDosHumanInput | None = None
) -> FieldState[PhononDosDecision]:
    """matdyn.x's phonon-DOS mesh on the written ``cell``, at the request's
    ``dos_q_distance`` or ``DOS_Q_DISTANCE`` (module docstring). ``Blocked``
    when ``cell`` is not resolved."""
    human = human or PhononDosHumanInput()
    if not cell.ok:
        return Blocked(by=blocked_by(cell))
    distance = DOS_Q_DISTANCE if human.dos_q_distance is None else human.dos_q_distance
    decision = PhononDosDecision(
        mesh=k_distance_to_mesh(cell.value.structure, distance),
        dos_q_distance=distance,
        delta_e=DOS_DELTA_E,
    )
    return Resolved(
        decision,
        Provenance.from_field_sources(
            field_sources_from(human, None, fields=("dos_q_distance",)),
            source_note=_DOS_NOTE if human.dos_q_distance is None else None,
            derived_from=("magnetic",),
        ),
    )


def dispersion_path(
    cell: FieldState[MagneticCell],
    geometry: FieldState[GeometryFacts],
    occupations: FieldState[OccupationsDecision],
    q2r: FieldState[Q2rDecision],
    human: KPathHumanInput | None = None,
) -> FieldState[KPathDecision]:
    """The path matdyn.x follows on the dispersion step (module docstring):
    the band path of the written ``cell`` at ``human``'s
    ``k_path_distance``, with each Gamma inside a branch listed twice and
    each segment into Gamma landing on it exactly where the first step's
    ``occupations`` are fixed and ``q2r`` has no loto_2d. ``Blocked`` when
    ``cell`` is not resolved; else ``Unavailable`` with ``NO_DISPERSION``
    when the written cell's ``geometry`` has vacuum along a, b and c; else
    ``Blocked`` by the first of ``occupations``, ``q2r`` and the band path
    that is not resolved, q2r before the path so that a structure whose
    boundary blocks q2r keeps that root cause. An unresolved ``geometry``
    is not read: the band path takes the vacuum from the cell itself."""
    if not cell.ok:
        return Blocked(by=blocked_by(cell))
    if geometry.ok and len(geometry.value.vacuum_axes) == 3:
        return Unavailable(reason=NO_DISPERSION)
    for state in (occupations, q2r):
        if not state.ok:
            return Blocked(by=blocked_by(state))
    path = k_path(cell, human)
    if not path.ok:
        return Blocked(by=blocked_by(path))
    band = path.value
    branches = band.branches
    if occupations.value.occupations == "fixed" and not q2r.value.loto_2d:
        branches = tuple(
            piece for branch in branches for piece in _matdyn_branches(branch)
        )
    notes = (
        path.provenance.source_note,
        _DISPERSION_NOTE if branches != band.branches else None,
    )
    return Resolved(
        replace(
            band,
            branches=branches,
            n_kpoints=sum(sum(branch.steps) + 1 for branch in branches),
        ),
        path.provenance.model_copy(
            update={
                "source_note": " ".join(note for note in notes if note) or None,
                "derived_from": ("magnetic", "occupations", "q2r"),
            }
        ),
    )


def _matdyn_branches(branch: PathBranch) -> tuple[PathBranch, ...]:
    """``branch`` as matdyn.x reads it where it adds the non-analytic term
    (module docstring): each segment into Gamma takes ``_exact_count``
    steps, then each Gamma inside the branch ends one branch and starts the
    next."""
    vertices = branch.vertices
    steps = tuple(
        _exact_count(count) if end.k == _GAMMA else count
        for count, end in zip(branch.steps, vertices[1:], strict=True)
    )
    cuts = [
        index
        for index, vertex in enumerate(vertices[1:-1], start=1)
        if vertex.k == _GAMMA
    ]
    bounds = (0, *cuts, len(vertices) - 1)
    return tuple(
        PathBranch(vertices=vertices[start : end + 1], steps=steps[start:end])
        for start, end in itertools.pairwise(bounds)
    )


def _exact_count(steps: int) -> int:
    """The fewest steps, at least ``steps``, whose last point lands exactly
    on Gamma: n with fl(fl(1/n) n) = 1 in double precision (module
    docstring)."""
    return next(n for n in itertools.count(steps) if (1.0 / n) * n == 1.0)
