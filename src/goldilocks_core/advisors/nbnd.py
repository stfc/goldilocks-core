"""nbnd: number of Kohn-Sham bands to compute, from nelec, occupations
and the spin channels the run fills.

New in v2 (v2 epic 6, #6). Fourth of five per-step advisors
(``occupations -> k_sampling -> n_irr_k -> nbnd -> convergence``,
goldilocks-core-design.md:3239-3248). v1 never had this advisor at all
-- ``nbnd`` was only ever computed inside ``resource_estimate``, with
nothing upstream of it deciding what to request from QE itself
(goldilocks-core-design.md's own note: "nbnd only computed in
resource_estimate, no advisor produces it").

**nbnd follows pw.x's own default rule** (#162): a literal port of QE
7.3 ``PW/src/setup.f90:326-345``, which pw.x applies when ``nbnd`` is not
given, departing from pw.x's own count only for the seeded moment below
(#131). It starts from the bands every spin channel needs,
``MAX(NINT(nelec/2), NINT(nelup), NINT(neldw))``; under smearing or
tetrahedra it pads that to ``MAX(NINT(1.2*nelec/2), NINT(1.2*nelup),
NINT(1.2*neldw), base + 4)``, 20% more with at least 4 more; for a
noncollinear run it doubles the padded count. ``nelup``/``neldw`` come
from ``Modules/electrons_base.f90:376-428`` (``set_nelup_neldw``):
``INT(nelec+1)/2`` and the rest without ``tot_magnetization``,
``(INT(nelec) +/- tot_magnetization)/2`` with an integer one, so a
pinned moment sizes the majority channel. ``NINT`` rounds half away
from zero, unlike Python's ``round()``. INPUT_PW's ``nbnd`` text leaves
out the ``nelup``/``neldw`` terms, the rounding and the order of padding
and doubling; the code follows ``setup.f90``.

The spin inputs are the ones the writer renders: the spin mode
(``MagneticConfigFacts.spin_mode``, #146) and, for a collinear run only
(nspin=2, the one mode pw.x accepts it in), the occupations decision's
``tot_magnetization``, the one rendered moment (#138). In a collinear
spin-polarized run QE doubles the number of k-points it solves, not the
number of bands: ``nbnd`` is per spin channel. A noncollinear (spin-orbit)
band is a two-component spinor holding one electron, so ``setup.f90``
doubles the per-spin count after padding; an odd electron count still
gets an even band count.

**The majority channel has room for the seeded moment (#131).** Without
``tot_magnetization`` pw.x's ``nelup``/``neldw`` split the electrons
evenly, and under smearing or tetrahedra it then holds the moment at
``2*nbnd - nelec``, converging to it without an error: hcp Gd's default
22 bands held it at 8 Bohr magnetons per cell on SCARF, 4.19 eV above the
15.5 its 32-band run reached. A collinear smearing or tetrahedra run
without ``tot_magnetization`` therefore sizes its majority channel for
the net moment its starting magnetization seeds,
``MagneticConfigFacts.seeded_moment`` (M): ``nelup`` becomes
``(nelec + |M|)/2`` where that is larger than QE's own and ``neldw`` the
rest, before the padding above, so the default always leaves
``2*nbnd - nelec > |M|`` (Gd: 28 bands). The seeds are
``magnetic_config``'s (aiida's maximal targets, +0.1 on every other
species of a ferromagnetic start), so an oversized seed over-pads, which
costs only compute; a compensated one changes nothing. Without a seeded
moment (no z_valence for an element) such a run is ``Blocked``. A human
``nbnd``, or a human or llm ``extra_bands``, that holds the moment below
its seed resolves with ``nbnd.moment_capped`` on every step. On a step
with its own SCF loop (``plan.SCF_LIKE_PURPOSES``) it says that pw.x holds
the moment there. An nscf or bands step runs at the scf's density instead,
so too few bands leave occupied bands of the majority channel out if the
scf's moment reaches its seed, which as a maximal target it need not; its
message says so and names the seeded majority count, (nelec + |M|)/2
rounded up (#118). Fixed occupations fill the pinned channels exactly, and
a noncollinear spinor band holds either spin, so neither reads the seed.

**pw.x's own floors are the gate's (``band_floors``).** pw.x stops in
setup when a given ``nbnd`` is below ``NINT(nelec/2)``, ``NINT(nelup)``
or ``NINT(neldw)``, or ``NINT(nelec)`` for a noncollinear run
(``setup.f90:349-358``), with the same ``nelup``/``neldw``, but only in a
run with its own SCF loop (``lscf``); an nscf or bands step below them
would leave occupied bands out. ``checks.check_all`` refuses such a count
from any source, on every step. The default is never below them.

**Uses ``occupations`` (not ``is_metal``) to decide the metal branch.**
``advisors/occupations.py`` has already turned ``is_metal`` (plus any
overrides) into an actual ``fixed``/``smearing``/``tetrahedra_opt``
decision; using that decision here -- ``smearing`` or ``tetrahedra_opt``
means "treated as needing empty states above a Fermi level" -- keeps
this advisor consistent with what will actually run, instead of
re-deriving metallicity independently and risking disagreement with a
sibling advisor's own overrides.

**``nelec`` is a required, plain input, not a ``FieldState``.** No
advisor in this codebase computes total valence electron count yet --
that requires knowing which pseudopotential (and therefore which
``z_valence`` per element) was chosen, which is
``advisors/pseudo_selection.py``'s job, and nothing wires that output
into this one yet (the same reason ``magnetic_config.py`` takes an
optional ``z_valences`` rather than computing it itself). There is no
sensible fallback value for a missing electron count, so this is not
made optional with a guessed default -- a caller that does not yet know
``nelec`` should not call this advisor yet.

**A task protocol can raise a step's band count (``NbndProtocol``,
#118).** A band structure plots empty bands above the occupied ones, so
the band task's bands step asks for more than pw.x's default
(``service/_step_protocol.py``'s ``BANDS_PROTOCOL``, aiida-quantumespresso's
``bands.yaml``). Without a human ``nbnd`` its default is the largest of
pw.x's default for the run (with the seeded moment above),
``int(nelec/epb*factor)`` and ``int(nelec/epb) + 4``, epb being 1 for a
noncollinear run and 2 otherwise: aiida-quantumespresso's
``PwBandsWorkChain`` rule, except that nelec is not truncated first and
pw.x's default stands in for the scf run's count. A human or llm
``extra_bands`` adds to it, and the record names the protocol in
``source_note``. A step without one keeps pw.x's default: the dos task's
nscf step gets the metal-like padding above (20% more, at least 4) only
because its protocol runs ``tetrahedra_opt`` (``DOS_NSCF_PROTOCOL``),
whose padding nobody chose for the DOS energy window (the bundled
``Si.cif``, nelec 32: scf ``nbnd=16``, nscf ``nbnd=20``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from pydantic import Field

from goldilocks_core.advisors.magnetic_config import MagneticConfigFacts, SpinMode
from goldilocks_core.advisors.occupations import OccupationsDecision
from goldilocks_core.inputs.overrides import HumanInput, LlmInput
from goldilocks_core.plan import SCF_LIKE_PURPOSES
from goldilocks_core.resolution import (
    Blocked,
    FieldState,
    Provenance,
    Resolved,
    Unavailable,
    Warning,
    blocked_by,
)

_METAL_LIKE_OCCUPATIONS = frozenset({"smearing", "tetrahedra_opt"})

_INTEGER_TOLERANCE = 1e-8
"""QE's ``eps8``, the tolerance ``set_nelup_neldw`` treats a charge or a
moment as an integer within."""

_SEEDED_MOMENT_UNKNOWN = (
    "nbnd sizes the majority spin channel of a collinear smearing run "
    "without tot_magnetization for the seeded moment, the net moment its "
    "starting magnetization seeds, but that is unknown: it needs the "
    "z_valence of every element, from the selected pseudopotentials. Set "
    "tot_magnetization or nbnd."
)

SPIN_NOTE = Warning(
    code="nbnd.spin_channel_note",
    level="info",
    category="nbnd",
    message=(
        "nspin=2 doubles the number of k-points QE solves internally, "
        "not the number of bands -- nbnd here is per spin channel, pw.x's "
        "default rule (QE setup.f90) for a majority channel holding "
        "nelup = (nelec + |M|)/2 electrons, M being tot_magnetization or, "
        "on a smearing or tetrahedra run without one, the net moment the "
        "starting magnetization seeds, where pw.x itself would split the "
        "electrons evenly."
    ),
)

NONCOLLINEAR_NOTE = Warning(
    code="nbnd.noncollinear_bands_doubled",
    level="info",
    category="nbnd",
    message=(
        "noncollinear/spin-orbit bands are spinors holding one electron "
        "each, not two, so nbnd here is twice pw.x's default for the same "
        "electron count and occupations without spin (QE setup.f90: "
        "padded per spin channel, then doubled)."
    ),
)

MOMENT_CAPPED_WARNING = Warning(
    code="nbnd.moment_capped",
    level="warning",
    category="nbnd",
    message=(
        "nbnd leaves the majority spin channel of a collinear smearing run "
        "no room for the moment its starting magnetization seeds: pw.x holds "
        "the moment at 2*nbnd - nelec Bohr magnetons per cell without an "
        "error, and an nscf or bands step leaves occupied majority bands out "
        "if the scf's moment reaches the seed. Raise nbnd, or unset nbnd and "
        "extra_bands."
    ),
)

WARNING_CATALOGUE = (SPIN_NOTE, NONCOLLINEAR_NOTE, MOMENT_CAPPED_WARNING)
"""Every warning code this module can emit -- ``capabilities.py``'s
``warnings[]`` catalogue aggregates one of these tuples per advisor. The
real, per-occurrence ``nbnd.moment_capped`` message names the numbers
(built in ``_moment_capped``); this is the generic description."""


@dataclass(frozen=True, slots=True)
class NbndDecision:
    nbnd: int
    warnings: tuple[Warning, ...] = ()


@dataclass(frozen=True, slots=True)
class BandFloor:
    """One of pw.x's lower bounds on ``nbnd`` (QE 7.3
    ``PW/src/setup.f90:349-356``): ``bands`` is the fewest it accepts,
    room for ``electrons`` electrons described by ``held``, and ``error``
    the message pw.x stops in setup with below it."""

    bands: int
    electrons: float
    held: str
    error: str


class NbndHumanInput(HumanInput):
    """``nbnd`` (#35, v2 epic 9, #9) must be a positive integer at
    construction -- before this, ``nbnd=0``/negative was accepted and
    written straight into the generated ``&SYSTEM`` card as a
    ``Resolved`` success. ``extra_bands`` stays unconstrained here
    (it is a signed adjustment to the heuristic base, legitimately
    negative) -- the combined total is checked in ``nbnd()`` below,
    where the heuristic base is actually known. A total below what pw.x
    accepts (``band_floors``) is refused by ``checks.check_all``."""

    nbnd: int | None = Field(default=None, gt=0)
    extra_bands: int | None = None


class NbndLlmInput(LlmInput):
    extra_bands: int | None = None


@dataclass(frozen=True, slots=True)
class NbndProtocol:
    """A task protocol's band count for one of its steps (#118), such as
    the band task's bands step: ``factor`` times the occupied bands (module
    docstring), ranked below a request's ``nbnd``, with a human or llm
    ``extra_bands`` added to it. Not a request value, so its record reads
    ``heuristic``, with ``note`` naming the protocol as its ``source_note``."""

    factor: float
    note: str


@dataclass(frozen=True, slots=True)
class _Sizing:
    """pw.x's default ``nbnd`` for the run, and the seeded moment it was
    sized for (``None`` when the seed does not size it)."""

    default: int
    seeded_moment: float | None


def nbnd(
    nelec: float,
    occupations: FieldState[OccupationsDecision],
    purpose: str = "scf",
    magnetic: FieldState[MagneticConfigFacts] | None = None,
    human: NbndHumanInput | None = None,
    llm: NbndLlmInput | None = None,
    protocol: NbndProtocol | None = None,
) -> FieldState[NbndDecision]:
    """The band count: a human ``nbnd``, else pw.x's default for the
    run's spin channels (``_sizing``, module docstring), or the larger
    count a task ``protocol`` asks for, plus any human or llm
    ``extra_bands``, with its spin note. ``Blocked`` when ``occupations``
    is, or when a collinear smearing run's seeded moment is unknown, unless
    a human ``nbnd`` is given; a total that is not positive is
    ``Unavailable``. A total that holds the moment below its seed carries
    ``nbnd.moment_capped``, worded for the step's ``purpose``."""
    human = human or NbndHumanInput()
    llm = llm or NbndLlmInput()

    if not occupations.ok:
        if human.nbnd is not None:
            return Resolved(NbndDecision(nbnd=human.nbnd), Provenance(source="human"))
        return Blocked(by=blocked_by(occupations))

    spin_mode, tot_magnetization, seeded_moment = _spin_inputs(
        occupations.value, magnetic
    )
    sizing = _sizing(
        nelec, occupations.value, spin_mode, tot_magnetization, seeded_moment
    )
    note = None
    if human.nbnd is not None:
        total, source, notes = human.nbnd, "human", ()
    elif isinstance(sizing, str):
        return Blocked(by=sizing)
    else:
        extra, source = _extra_bands(human, llm)
        default = sizing.default
        if protocol is not None:
            default = _protocol_default(nelec, spin_mode, default, protocol)
            note = protocol.note
        total, notes = default + extra, _spin_note(spin_mode)
        if total <= 0:
            # #35 (v2 epic 9, #9): extra_bands is a legitimately-signed
            # adjustment (Field(gt=0) on it alone would reject valid
            # negative reductions), but the combined total must still be a
            # physically meaningful band count -- before this, a
            # sufficiently negative extra_bands silently produced a
            # zero/negative &SYSTEM nbnd card, reported as a resolved
            # success.
            return Unavailable(
                reason=(
                    f"heuristic nbnd={default} + extra_bands={extra} = "
                    f"{total}, which is not a valid number of bands (must be "
                    "positive)"
                )
            )

    warnings = (*notes, *_moment_capped(total, nelec, sizing, purpose))
    decision = NbndDecision(nbnd=total, warnings=warnings)
    return Resolved(decision, Provenance(source=source, source_note=note))


def band_floors(
    nelec: float,
    occupations: OccupationsDecision,
    magnetic: FieldState[MagneticConfigFacts] | None,
) -> tuple[BandFloor, ...]:
    """pw.x's lower bounds on ``nbnd`` for ``nelec`` electrons, in the
    order QE 7.3 ``PW/src/setup.f90:349-356`` checks them: ``NINT(nelec/2)``,
    ``NINT(nelup)`` and ``NINT(neldw)``, then ``NINT(nelec)`` for a
    noncollinear run, with the spin inputs ``nbnd`` sizes from. pw.x
    applies them to a given ``nbnd`` in a run with its own SCF loop; its
    default never falls below them."""
    spin_mode, tot_magnetization, _ = _spin_inputs(occupations, magnetic)
    nelup, neldw = _spin_channels(nelec, tot_magnetization)
    floors = (
        BandFloor(_nint(nelec / 2), nelec, "electrons, two per band", "too few bands"),
        BandFloor(_nint(nelup), nelup, "spin-up electrons", "too few spin up bands"),
        BandFloor(_nint(neldw), neldw, "spin-down electrons", "too few spin dw bands"),
    )
    if spin_mode == "noncollinear":
        spinor = BandFloor(
            _nint(nelec), nelec, "electrons, one per spinor band", "too few bands"
        )
        return (*floors, spinor)
    return floors


def _spin_inputs(
    occupations: OccupationsDecision,
    magnetic: FieldState[MagneticConfigFacts] | None,
) -> tuple[SpinMode, float | None, float | None]:
    """QE's spin inputs as the writer renders them: the spin mode of
    ``magnetic`` (``none`` when there is no resolved one), and for a
    collinear run only (module docstring) the ``tot_magnetization`` of
    ``occupations`` and the seeded moment of ``magnetic``."""
    if magnetic is None or not magnetic.ok:
        return "none", None, None
    facts = magnetic.value
    if facts.spin_mode != "collinear":
        return facts.spin_mode, None, None
    return "collinear", occupations.tot_magnetization, facts.seeded_moment


def _sizing(
    nelec: float,
    occupations: OccupationsDecision,
    spin_mode: SpinMode,
    tot_magnetization: float | None,
    seeded_moment: float | None,
) -> _Sizing | str:
    """pw.x's default for the spin channels the run fills (module
    docstring): QE's own ``nelup``/``neldw``, the majority channel raised
    to hold the seeded moment on a collinear smearing or tetrahedra run
    without ``tot_magnetization`` (#131). The reason it cannot be sized,
    when that seed is unknown."""
    metal_like = occupations.occupations in _METAL_LIKE_OCCUPATIONS
    channels = _spin_channels(nelec, tot_magnetization)
    seeded = spin_mode == "collinear" and metal_like and tot_magnetization is None
    if seeded:
        if seeded_moment is None:
            return _SEEDED_MOMENT_UNKNOWN
        channels = _seeded_channels(nelec, channels, seeded_moment)
    nelup, neldw = channels
    default = _qe_default_nbnd(nelec, nelup, neldw, metal_like, spin_mode)
    return _Sizing(default, seeded_moment if seeded else None)


def _seeded_channels(
    nelec: float, channels: tuple[float, float], seeded_moment: float
) -> tuple[float, float]:
    """``channels`` with the majority one holding ``(nelec + |M|)/2``
    electrons for the seeded moment M, where QE's own ``nelup`` is
    smaller."""
    nelup = (nelec + abs(seeded_moment)) / 2
    if nelup <= channels[0]:
        return channels
    return nelup, nelec - nelup


def _qe_default_nbnd(
    nelec: float,
    nelup: float,
    neldw: float,
    metal_like: bool,
    spin_mode: SpinMode,
) -> int:
    """pw.x's default ``nbnd`` (QE 7.3 ``PW/src/setup.f90:326-345``):
    the bands each spin channel needs, padded under smearing or
    tetrahedra, doubled for a noncollinear run."""
    bands = max(_nint(nelec / 2), _nint(nelup), _nint(neldw))
    if metal_like:
        bands = max(
            _nint(1.2 * nelec / 2), _nint(1.2 * nelup), _nint(1.2 * neldw), bands + 4
        )
    if spin_mode == "noncollinear":
        bands *= 2
    return bands


def _spin_channels(
    nelec: float, tot_magnetization: float | None
) -> tuple[float, float]:
    """``nelup``/``neldw`` as QE 7.3 ``set_nelup_neldw`` sets them
    (``Modules/electrons_base.f90:376-428``), ``INT`` truncation
    included."""
    integer_charge = abs(nelec - _nint(nelec)) < _INTEGER_TOLERANCE
    if tot_magnetization is None:
        if not integer_charge:
            return nelec / 2, nelec / 2
        nelup = int(nelec + 1) // 2
        return nelup, nelec - nelup
    integer_moment = (
        abs(tot_magnetization - _nint(tot_magnetization)) < _INTEGER_TOLERANCE
    )
    charge = int(nelec) if integer_charge and integer_moment else nelec
    return (charge + tot_magnetization) / 2, (charge - tot_magnetization) / 2


def _protocol_default(
    nelec: float, spin_mode: SpinMode, default: int, protocol: NbndProtocol
) -> int:
    """The band count ``protocol`` asks for (module docstring): the largest
    of pw.x's ``default`` for the run, ``factor`` times the occupied bands
    and four more than them, a noncollinear band holding one electron and
    any other two."""
    occupied = nelec / (1 if spin_mode == "noncollinear" else 2)
    return max(default, int(occupied * protocol.factor), int(occupied) + 4)


def _nint(value: float) -> int:
    """Fortran ``NINT``: the nearest integer, halves away from zero."""
    return int(math.copysign(math.floor(abs(value) + 0.5), value))


def _extra_bands(human: NbndHumanInput, llm: NbndLlmInput) -> tuple[int, str]:
    """The ``extra_bands`` added to the default and its source: human,
    then llm, else none."""
    if human.extra_bands is not None:
        return human.extra_bands, "human"
    if llm.extra_bands is not None:
        return llm.extra_bands, "llm"
    return 0, "heuristic"


def _spin_note(spin_mode: SpinMode) -> tuple[Warning, ...]:
    if spin_mode == "noncollinear":
        return (NONCOLLINEAR_NOTE,)
    if spin_mode == "collinear":
        return (SPIN_NOTE,)
    return ()


def _moment_capped(
    total: int, nelec: float, sizing: _Sizing | str, purpose: str
) -> tuple[Warning, ...]:
    """``nbnd.moment_capped`` when ``total`` bands hold a seeded moment
    below its seed: pw.x fills at most ``total`` bands per spin channel,
    so the moment of a smearing run stays within ``2*total - nelec``, and
    a step of ``purpose`` without its own SCF loop leaves occupied
    majority bands out if the scf's moment reaches the seed (module
    docstring). The default always has room."""
    if isinstance(sizing, str) or sizing.seeded_moment is None:
        return ()
    seed = abs(sizing.seeded_moment)
    cap = 2 * total - nelec
    if cap >= seed:
        return ()
    if purpose in SCF_LIKE_PURPOSES:
        message = (
            f"nbnd={total} leaves room for at most 2*nbnd - nelec = "
            f"{_number(cap)} Bohr magnetons per cell in this collinear smearing "
            f"run, below the {_number(seed)} its starting magnetization seeds; "
            "pw.x holds the moment there without an error. Use nbnd >= "
            f"{sizing.default}, the default for this seed, or unset nbnd and "
            "extra_bands."
        )
    else:
        fill = (nelec + seed) / 2
        message = (
            f"nbnd={total} holds fewer than the (nelec + |M|)/2 = {_number(fill)} "
            "electrons the majority spin channel fills at the "
            f"{_number(seed)} Bohr magnetons the starting magnetization seeds: if "
            f"the scf's moment reaches that seed, this {purpose} step leaves "
            f"occupied majority bands out. Use nbnd >= {math.ceil(fill)}, or "
            "unset nbnd and extra_bands."
        )
    return (MOMENT_CAPPED_WARNING.model_copy(update={"message": message}),)


def _number(value: float) -> str:
    """``value`` to two decimals, without trailing zeros."""
    return f"{round(value, 2):g}"
