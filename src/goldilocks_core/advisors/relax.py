"""relax: ion/cell relaxation parameters of a relax or vc-relax step.

``RelaxOptions``/``VcRelaxOptions`` (the typed fields) landed in v2 epic
7 (#7); this epic (v2 epic 10, #10) adds the actual decision cascade
(``relax_settings``, human/llm/heuristic precedence like every other
advisor) plus the two ``HumanInput``/``LlmInput`` bags, closing the gap
epic 7's own docstring named ("full relax parameter coverage... is v2
epic 10's job"). Every default is copied verbatim from QE's own
``INPUT_PW.txt`` (re-downloaded and checked 2026-09-14, not carried over
from memory or the design doc's own prose), not invented or "improved"
with unvalidated numbers.

**A task's protocol can set ``forc_conv_thr``** (#215). The phonon tasks
relax to aiida-quantumespresso's balanced 1e-4 Ry/Bohr
(``workflows/protocols/pw/base.yaml``; fast 1e-3, stringent 0.5e-4), ten
times tighter than QE's default, because DFPT takes second derivatives at
the geometry it is given and leftover forces shift the frequencies. That
value is the task's (``RelaxProtocol``, carried on
``service/_step_protocol.py``'s ``StepProtocol``), not this module's
default: it ranks below a request's ``forc_conv_thr`` and above QE's
default, and, as a threshold, has no llm tier. Its record reads
``heuristic``, with the protocol's note and citations. A request value is
used as given, and one looser than the protocol's carries the protocol's
warning. The relax and vc-relax tasks give no protocol and keep QE's 1e-3.

**``fix_bottom_layers`` (#44, split out of this epic then implemented
separately):** human-only (``RelaxHumanInput`` only, no ``RelaxLlmInput``
counterpart) -- like the numerically-sensitive thresholds below, which
atoms to physically pin during a relaxation is a structural decision,
not a "which scenario" choice an llm tier should be guessing at. The
layers are ``analysis.geometry.slab_layers``, counted up from the vacuum
of a cell with exactly one vacuum axis, on
``system.magnetic.cell`` (the simulated cell) rather than the phase-1
``structure`` this module's ``geometry`` parameter is computed against:
that is the structure whose site order the ``ATOMIC_POSITIONS`` card
needs index-aligned layers for, and AFM species-splitting can change its
site count and order. ``checks.py``'s ``_fix_bottom_layers_requires_slab``
refuses any value other than ``None`` unless that cell is a slab with at
least that many layers (#160); a '2d' rank is not enough, since bulk
graphite has one and no vacuum.

**``cell_dofree`` comes from the vacuum, not the dimensionality rank
(#132).** The rank cannot tell a bulk layered crystal from a slab:
graphite ranks '2d' like graphene, and under QE's 2D constraint '2Dxy'
its stacking axis stayed frozen while BFGS reported convergence on the
masked stress. '2Dxy' moves only the x and y components of a and b and
holds c fixed, in Cartesian axes (QE 7.3 Modules/cell_base.f90:803-808),
so it is the default only for a slab in that frame: one vacuum axis, c,
with a and b in the xy plane (``analysis.geometry.SlabGeometry``), read on
the cell to be written, which the magnetic step turns every slab with its
vacuum along c into (``pw_symmetry.pw_frame``, #140). A cell without
vacuum, or with vacuum along all three axes, gets 'all' (the boundary gate
in ``checks.py`` refuses a vc-relax of an isolated system). A wire, or a
slab with its vacuum along a or b, has no default, so the vc-relax is
``Blocked`` until a human or llm value sets ``cell_dofree``; ``checks.py``
refuses '2Dxy' and '2Dshape' from any source on a written cell outside
that frame. ``CellDofree`` holds only the values pw.x honours under the
writer's ``ibrav = 0`` (#153).

**``etot_conv_thr`` is not this module's own decision.** ``advisors/
convergence.py`` already resolves it as ``nat * etot_conv_thr_per_atom``
(the exact formula/constant the design doc wants for relax too, since
this is the same "how much can the total energy still wobble" question
scf's own convergence advisor already answers) -- ``relax_settings``
reads ``ConvergenceDecision.etot_conv_thr`` off the step's already
-resolved convergence decision rather than recomputing it, so there is
exactly one nat-scaling formula in this codebase, not two that could
drift apart. There is deliberately no separate ``--set``-able
``relax``-scoped ``etot_conv_thr``: the existing ``etot_conv_thr`` key
(``ConvergenceHumanInput``) already reaches this value.

**A real gap found while implementing this epic, not in the original
issue:** ``VcRelaxOptions.cell_dynamics`` (epic 7) is a derived property
that always equals ``ion_dynamics`` -- correct only because this
codebase, until now, could never construct an ``ion_dynamics`` other
than the default ``'bfgs'``. Now that ``RelaxHumanInput``/
``RelaxLlmInput`` exist, a caller *can* set ``ion_dynamics='damp'`` on a
vc-relax request, which would make the derived property emit
``cell_dynamics='damp'`` -- not a valid QE ``cell_dynamics`` value for
vc-relax at all (valid values, confirmed against ``INPUT_PW.txt``:
``none``/``sd``/``damp-pr``/``damp-w``/``bfgs``). ``checks.py``'s
``_vc_relax_requires_bfgs_ion_dynamics`` blocks this rather than letting
it reach generation -- this codebase only models the bfgs/bfgs
combination for vc-relax (the design doc's own stated v2 scope: damp
-paired cell dynamics needs ``wmass``, audit finding F41, "low priority
deferred").
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Literal

from pydantic import Field

from goldilocks_core.advisors.convergence import ConvergenceDecision
from goldilocks_core.analysis.geometry import GeometryFacts, LatticeAxis, SlabGeometry
from goldilocks_core.inputs.overrides import HumanInput, LlmInput
from goldilocks_core.resolution import (
    Blocked,
    FieldState,
    Provenance,
    Resolved,
    Warning,
    blocked_by,
    field_sources_from,
)

IonDynamics = Literal["bfgs", "damp", "fire"]
"""QE's full ``ion_dynamics`` domain across ``relax``/``vc-relax``
(``INPUT_PW.txt``, checked 2026-09-14). ``fire`` is documented for
``relax`` only, not ``vc-relax`` -- not separately encoded here because
``checks.py``'s ``_vc_relax_requires_bfgs_ion_dynamics`` already rejects
every non-``'bfgs'`` value for vc-relax, ``fire`` included."""

CellDofree = Literal[
    "all",
    "a",
    "b",
    "c",
    "fixa",
    "fixb",
    "fixc",
    "x",
    "y",
    "z",
    "xy",
    "xz",
    "yz",
    "xyz",
    "shape",
    "2Dxy",
    "2Dshape",
    "epitaxial_ab",
    "epitaxial_ac",
    "epitaxial_bc",
]
"""The ``cell_dofree`` values pw.x honours under the ``ibrav = 0`` the
writer always emits (``generation/quantum_espresso/scf.py``
``system_keywords``; QE 7.3 ``Modules/cell_base.f90:710-830``
``init_dofree``). QE's other 22 are left out (#153): ``'volume'`` stops
pw.x unless ``ibrav = 1`` ("Isotropic expansion is only allowed for
ibrav=1", ``cell_base.f90:751-756``), and ``'ibrav'`` and every
``'ibrav+option'`` only print "With ibrav=0, cell_dofree='ibrav' has no
effect" (``Modules/latgen.f90:749-752``) and act as ``'all'`` or
``option``. A ``Literal``, so pydantic refuses any other value at the
transport boundary and ``/capabilities`` advertises exactly these. If the
writer ever emits a real ibrav, validity becomes structure-dependent and
belongs in a ``checks.py`` rule."""

_FORC_CONV_THR_DEFAULT = 1.0e-3
"""a.u. (Ry/Bohr). QE's own official INPUT_PW default."""
_NSTEP_DEFAULT = 50
"""QE's own default for calculation not in {scf, nscf, bands}."""
_TRUST_RADIUS_MAX_DEFAULT = 0.8
"""Bohr. bfgs only."""
_TRUST_RADIUS_MIN_DEFAULT = 1.0e-3
"""Bohr. bfgs only."""
_TRUST_RADIUS_INI_DEFAULT = 0.5
"""Bohr. bfgs only."""
_PRESS_DEFAULT = 0.0
"""kbar."""
_PRESS_CONV_THR_DEFAULT = 0.5
"""kbar."""
_CELL_FACTOR_DEFAULT = 2.0
"""Must exceed the maximum linear *contraction* the cell will undergo,
not expansion (audit finding #3)."""
_DEFAULT_CELL_DOFREE: CellDofree = "all"
_SLAB_CELL_DOFREE: CellDofree = "2Dxy"
_WIRE_CELL_DOFREE: dict[LatticeAxis, CellDofree] = {
    "a": "epitaxial_bc",
    "b": "epitaxial_ac",
    "c": "epitaxial_ab",
}
"""The constraint that relaxes only a wire's period, by the period's lattice
vector: it moves every component of that vector and holds the other two, the
vacuum vectors, fixed (QE 7.3 Modules/cell_base.f90:825-842), whatever their
orientation. 'x', 'y' and 'z' move one Cartesian component of a, b or c, which
leaves a period off that axis unrelaxed."""


@dataclass(frozen=True, slots=True)
class RelaxOptions:  # calculation ∈ {relax, vc-relax}
    ion_dynamics: IonDynamics = "bfgs"
    forc_conv_thr: float = _FORC_CONV_THR_DEFAULT
    """a.u. (Ry/Bohr). Defaults to QE's own official INPUT_PW value; a
    task's protocol can set its own (``RelaxProtocol``)."""
    etot_conv_thr: float = 1.0e-5
    """a.u. Not this module's own default -- ``relax_settings`` always
    overwrites this with the caller's already-resolved
    ``ConvergenceDecision.etot_conv_thr`` (``nat *
    etot_conv_thr_per_atom``, this module's own docstring). This bare
    default only matters for a ``RelaxOptions`` built by hand (tests),
    never a real ``relax_settings`` output."""
    nstep: int = _NSTEP_DEFAULT
    trust_radius_max: float = _TRUST_RADIUS_MAX_DEFAULT
    """Bohr."""
    trust_radius_min: float = _TRUST_RADIUS_MIN_DEFAULT
    """Bohr."""
    trust_radius_ini: float = _TRUST_RADIUS_INI_DEFAULT
    """Bohr."""
    remove_rigid_rot: bool = False
    fix_bottom_layers: int | None = None
    """Number of bottom atomic layers (of a 2D slab) to fix with an
    ``if_pos`` card entry. ``None`` matches QE's own default of no
    ``if_pos`` column (every atom free). Human-only -- see this
    module's own docstring."""
    warnings: tuple[Warning, ...] = ()


@dataclass(frozen=True, slots=True)
class VcRelaxOptions(RelaxOptions):  # calculation == 'vc-relax'
    cell_dofree: CellDofree = _DEFAULT_CELL_DOFREE
    press: float = _PRESS_DEFAULT
    """kbar."""
    press_conv_thr: float = _PRESS_CONV_THR_DEFAULT
    """kbar."""
    cell_factor: float = _CELL_FACTOR_DEFAULT
    """Must exceed the maximum linear *contraction* the cell will
    undergo, not expansion -- see this module's docstring, audit
    finding #3."""

    @property
    def cell_dynamics(self) -> str:
        """Always equals ``ion_dynamics`` -- QE requires this coupling
        (audit finding B5, confirmed both directions in ``INPUT_PW.txt``
        2026-09-14). A derived property, not an independent field, so
        the invalid combination cannot be constructed. Only ever
        ``'bfgs'`` in practice: ``checks.py`` blocks any other
        ``ion_dynamics`` for vc-relax -- see this module's own
        docstring."""
        return self.ion_dynamics


class RelaxHumanInput(HumanInput):
    ion_dynamics: IonDynamics | None = None
    forc_conv_thr: float | None = Field(default=None, gt=0)
    nstep: int | None = Field(default=None, gt=0)
    trust_radius_max: float | None = Field(default=None, gt=0)
    trust_radius_min: float | None = Field(default=None, gt=0)
    trust_radius_ini: float | None = Field(default=None, gt=0)
    remove_rigid_rot: bool | None = None
    fix_bottom_layers: int | None = Field(default=None, gt=0)
    cell_dofree: CellDofree | None = None
    press: float | None = None
    press_conv_thr: float | None = Field(default=None, gt=0)
    cell_factor: float | None = Field(default=None, gt=0)


class RelaxLlmInput(LlmInput):
    """Numerically-sensitive thresholds (``forc_conv_thr``,
    ``trust_radius_*``, ``press_conv_thr``, ``cell_factor``) are
    human-only, matching ``advisors/convergence.py``'s own
    ``ConvergenceLlmInput`` precedent of keeping convergence-threshold
    -shaped fields out of the llm tier -- only "which scenario" choices
    are here. ``fix_bottom_layers`` is human-only for the same reason as
    the thresholds above: which atoms to physically pin is a structural
    decision, not a scenario choice."""

    ion_dynamics: IonDynamics | None = None
    nstep: int | None = None
    remove_rigid_rot: bool | None = None
    cell_dofree: CellDofree | None = None
    press: float | None = None


@dataclass(frozen=True, slots=True)
class RelaxProtocol:
    """A task protocol's force threshold for its relaxation step (#215),
    such as the phonon tasks' 1e-4 Ry/Bohr: ranked below a request's
    ``forc_conv_thr`` and above QE's default (module docstring). Not a
    request value, so its record reads ``heuristic``, with ``note`` as its
    ``source_note`` and ``citations`` as its citations. A request value
    looser than ``forc_conv_thr`` is kept and carries ``loose_warning``."""

    forc_conv_thr: float
    """a.u. (Ry/Bohr), as ``RelaxHumanInput.forc_conv_thr``."""
    note: str
    citations: tuple[str, ...]
    loose_warning: Warning


def relax_settings(
    calculation: Literal["relax", "vc-relax"],
    convergence: FieldState[ConvergenceDecision],
    geometry: FieldState[GeometryFacts] | None = None,
    human: RelaxHumanInput | None = None,
    llm: RelaxLlmInput | None = None,
    protocol: RelaxProtocol | None = None,
) -> FieldState[RelaxOptions | VcRelaxOptions]:
    """``etot_conv_thr`` makes this ``Blocked`` whenever ``convergence``
    itself is not ``Resolved`` -- there is no fallback constant, per
    this module's own docstring on why that value is read off
    ``convergence``, not recomputed. A vc-relax is also ``Blocked`` when
    ``geometry`` gives the cell no default ``cell_dofree`` and no human or
    llm value is set (a wire, or a slab outside the xy frame).

    ``forc_conv_thr`` is the request's, else the task ``protocol``'s, else
    QE's default (module docstring). The protocol's value reads
    ``heuristic`` and puts the protocol's note and citations on the record;
    a request value looser than the protocol's carries its warning.

    ``field_sources`` has one entry per field of the decision, so only a
    setting the decision applied can make the record ``human`` (#173; a
    request cannot carry the vc-relax keys to a relax at all, #154);
    ``etot_conv_thr`` reads its source on ``convergence``."""
    human = human or RelaxHumanInput()
    llm = llm or RelaxLlmInput()

    if not convergence.ok:
        return Blocked(by=blocked_by(convergence))

    convergence_field_sources = convergence.provenance.field_sources or {}
    etot_conv_thr_source = convergence_field_sources.get(
        "etot_conv_thr", convergence.source
    )
    forc_conv_thr, warnings, protocol_provenance = _forc_conv_thr(
        human.forc_conv_thr, protocol
    )

    base_kwargs: dict[str, object] = {
        "ion_dynamics": _pick(human.ion_dynamics, llm.ion_dynamics, "bfgs"),
        "forc_conv_thr": forc_conv_thr,
        "etot_conv_thr": convergence.value.etot_conv_thr,
        "nstep": _pick(human.nstep, llm.nstep, _NSTEP_DEFAULT),
        "trust_radius_max": _pick(
            human.trust_radius_max, None, _TRUST_RADIUS_MAX_DEFAULT
        ),
        "trust_radius_min": _pick(
            human.trust_radius_min, None, _TRUST_RADIUS_MIN_DEFAULT
        ),
        "trust_radius_ini": _pick(
            human.trust_radius_ini, None, _TRUST_RADIUS_INI_DEFAULT
        ),
        "remove_rigid_rot": _pick(human.remove_rigid_rot, llm.remove_rigid_rot, False),
        "fix_bottom_layers": _pick(human.fix_bottom_layers, None, None),
        "warnings": warnings,
    }

    if calculation == "vc-relax":
        cell_dofree = _resolve_cell_dofree(human.cell_dofree, llm.cell_dofree, geometry)
        if isinstance(cell_dofree, Blocked):
            return cell_dofree
        decision: RelaxOptions | VcRelaxOptions = VcRelaxOptions(
            **base_kwargs,
            cell_dofree=cell_dofree,
            press=_pick(human.press, llm.press, _PRESS_DEFAULT),
            press_conv_thr=_pick(human.press_conv_thr, None, _PRESS_CONV_THR_DEFAULT),
            cell_factor=_pick(human.cell_factor, None, _CELL_FACTOR_DEFAULT),
        )
    else:
        decision = RelaxOptions(**base_kwargs)

    field_sources = field_sources_from(
        human,
        llm,
        fields=[field.name for field in fields(decision) if field.name != "warnings"],
        decided={"etot_conv_thr": etot_conv_thr_source},
    )
    return Resolved(
        decision, Provenance.from_field_sources(field_sources, **protocol_provenance)
    )


def _forc_conv_thr(
    human_value: float | None, protocol: RelaxProtocol | None
) -> tuple[float, tuple[Warning, ...], dict[str, object]]:
    """``forc_conv_thr`` with the warnings it carries (``protocol``'s
    ``loose_warning`` for a request value strictly looser than the
    protocol's) and the provenance fields it adds (``protocol``'s note and
    citations when the protocol's value is used)."""
    if protocol is None:
        return _pick(human_value, None, _FORC_CONV_THR_DEFAULT), (), {}
    if human_value is None:
        return (
            protocol.forc_conv_thr,
            (),
            {"source_note": protocol.note, "citations": protocol.citations},
        )
    loose = human_value > protocol.forc_conv_thr
    return human_value, (protocol.loose_warning,) if loose else (), {}


def _resolve_cell_dofree(
    human_value: CellDofree | None,
    llm_value: CellDofree | None,
    geometry: FieldState[GeometryFacts] | None,
) -> CellDofree | Blocked:
    """A human or llm value wins; otherwise the vacuum decides, as this
    module's docstring describes. Without a resolved geometry the default
    is QE's own, 'all'."""
    if human_value is not None:
        return human_value
    if llm_value is not None:
        return llm_value
    if geometry is None or not geometry.ok:
        return _DEFAULT_CELL_DOFREE
    slab = geometry.value.slab
    if slab is not None and slab.xy_frame:
        return _SLAB_CELL_DOFREE
    if slab is not None:
        return Blocked(by=_slab_outside_xy_frame(slab))
    if len(geometry.value.vacuum_axes) == 2:
        return Blocked(by=_wire(geometry.value.vacuum_axes))
    return _DEFAULT_CELL_DOFREE


def _slab_outside_xy_frame(slab: SlabGeometry) -> str:
    found = (
        "a or b out of the xy plane"
        if slab.vacuum_axis == "c"
        else f"its vacuum along {slab.vacuum_axis}"
    )
    return (
        "vc-relax of a slab needs QE's 2D cell constraint cell_dofree="
        f"{_SLAB_CELL_DOFREE!r}, which moves only the x and y components of a and b "
        "and holds c fixed. It applies only with the vacuum along c and a, b in "
        f"the Cartesian xy plane, but this slab has {found}. Reorient the cell "
        "that way, or set cell_dofree explicitly."
    )


def wire_period(
    vacuum_axes: tuple[LatticeAxis, ...],
) -> tuple[LatticeAxis, CellDofree]:
    """The lattice vector along a wire whose vacuum lies along the other two,
    ``vacuum_axes``, and the ``cell_dofree`` that relaxes only that vector and
    holds both vacuum vectors fixed, in any orientation."""
    (period,) = (axis for axis in _WIRE_CELL_DOFREE if axis not in vacuum_axes)
    return period, _WIRE_CELL_DOFREE[period]


def _wire(vacuum_axes: tuple[LatticeAxis, ...]) -> str:
    period, constraint = wire_period(vacuum_axes)
    vacuum = " and ".join(vacuum_axes)
    return (
        f"vc-relax of a wire (vacuum along {vacuum}) has no default cell_dofree, "
        "because 'all' would also relax the vacuum. Set cell_dofree explicitly: "
        f"cell_dofree={constraint!r} holds {vacuum} fixed and relaxes only "
        f"{period}, the wire's period."
    )


def _pick[T](human_value: T | None, llm_value: T | None, default: T) -> T:
    if human_value is not None:
        return human_value
    if llm_value is not None:
        return llm_value
    return default
