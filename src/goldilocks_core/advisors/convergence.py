"""convergence: SCF convergence thresholds, scaled by system size.

New in v2 (v2 epic 6, #6). Last of five per-step advisors
(``occupations -> k_sampling -> n_irr_k -> nbnd -> convergence``,
goldilocks-core-design.md:3239-3248).

**`conv_thr`/`etot_conv_thr` scale with `nat`.** Replaces v1's
``_advise_convergence`` (``advice/parameters.py:276-306``), which took
only ``hints`` and always returned a fixed ``DEFAULT_CONV_THR = 1e-6``
regardless of system size -- QE's own docs concede ``conv_thr`` is
extensive, like the total energy, so a fixed value is too loose for a
large system and possibly too tight for a small one, with no scaling
formula supplied. This adopts aiida-quantumespresso's actual
``PwBaseWorkChain`` implementation instead
(``workflows/pw/base.py:271-272``, goldilocks-core-design.md:2914):
``conv_thr = nat * conv_thr_per_atom`` and
``etot_conv_thr = nat * etot_conv_thr_per_atom``, using its
production-validated balanced-tier constants
(``conv_thr_per_atom=0.2e-9``, ``etot_conv_thr_per_atom=1e-5``) rather
than invented ones. The products are taken in decimal, so the recorded
value is exactly the decimal the formula names (``2.8e-09`` for nat 14):
the float product ``14 * 0.2e-9`` is ``2.8000000000000003e-09``, which
``goldilocks.json`` recorded and the input printed (#178).
``mixing_beta``/``electron_maxstep`` keep v1's own flat defaults
(``0.4``, ``80`` -- ``advice/parameters.py:17-18``); no source in this
codebase scales those with system size.

**`mixing_mode='local-TF'` for a cell with a vacuum region**
(goldilocks-core-design.md:2907, "F26"): QE's default ``'plain'``
mixing struggles on structures with a vacuum region, which the
long-range part of Thomas-Fermi screening mixing handles better. The
rule reads ``GeometryFacts.vacuum_axes``, the region itself: a slab, a
wire and an isolated system all have one. The design doc named the
``2d``/``molecule`` ranks, but bulk graphite ranks '2d' and CO2 dry ice
'molecule' without any vacuum (#160); on SCARF, local-TF and plain
mixing gave the same energies and SCF iteration counts for bulk MgB2
and graphite.

**No default `mixing_fixed_ns`** (#127; replaces the design doc's "F5"
default of 50 for every +U input, goldilocks-core-design.md:2908). While
``iter <= mixing_fixed_ns``, pw.x resets the Hubbard occupation matrix
ns to its iteration-1 value (QE 7.3 ``PW/src/electrons.f90:815-833``),
yet it still declares convergence if the density converges inside that
window: ``mix_rho.f90:162`` has no fixed-ns guard. The freeze restarts
at every ionic step (``electrons.f90:556``). With ns frozen, the Hubbard
stress from ``stres_hub`` can have an antisymmetric part, and pw.x
aborts with "non-symmetric stress contribution"
(``stres_hub.f90:391-397``) when the symmetry group it found leaves
that part in place, as the Ci or C2h groups it often finds on
goldilocks' CIF-frame ``ibrav = 0`` cells do (#140). So the field
resolves only from a human or LLM value; unset leaves QE's default of
0 and the writer renders nothing. A frozen-ns start would have to be an
explicit two-stage plan (a frozen-ns stage with
``starting_ns_eigenvalue``, then a restart with ns free), which is not
modelled.

**+U-specific logic keys on the resolved Hubbard decision** (#166): the
``hubbard_u`` decision that renders the HUBBARD card, never the
``needs_correlation`` fact. The two disagree whenever an override or a
hybrid functional decides (``hubbard_needs_correlation=false`` on CeO2,
``u_by_element`` on the nitride UN) or no element present has a U (Th in
ThO2). A human or LLM ``mixing_fixed_ns`` is kept as given; a nonzero one
on a decision that applies a U carries ``MIXING_FIXED_NS_WARNING``. With
no U, pw.x ignores the keyword: it reads ``mixing_fixed_ns`` only under
``lda_plus_u`` (``electrons.f90:748-815``, ``potinit.f90:286-290``).

**No `is_metal` input.** It appears in the design doc's own illustrative
per-step loop snippet, but no source in this codebase specifies a
metallicity-dependent convergence rule (e.g. a different `mixing_beta`
for metals) -- unlike `k_sampling`'s deliberately-unused `occupations`
input, there is no documented future contract this would need to match,
so it is left out rather than carried as an unjustified placeholder.

``hubbard`` and ``geometry`` are optional: anything other than a
confirmed ``Resolved`` value (``Unavailable``, ``Blocked``, or simply not
supplied) adds no frozen-ns warning and keeps ``mixing_mode='plain'``
respectively -- ``conv_thr``/``etot_conv_thr``/``mixing_beta``/
``electron_maxstep`` depend on neither, so this module never blocks on
them.

**``Provenance.field_sources``, populated here first.** v2 epic 9
(#9)'s scenario 2 needs "did a human touch *this specific* field"
(overriding ``mixing_beta`` alone must not make ``conv_thr``/
``mixing_mode`` look human-sourced too): ``field_sources`` has one entry
per field, from ``resolution.field_sources_from`` in ``_pick``'s priority
order, and the record's ``source`` is the highest of them (#173).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from pydantic import Field

from goldilocks_core.advisors.hubbard_u import HubbardUDecision
from goldilocks_core.analysis.geometry import GeometryFacts
from goldilocks_core.inputs.overrides import HumanInput, LlmInput
from goldilocks_core.resolution import (
    FieldState,
    Provenance,
    Resolved,
    Warning,
    field_sources_from,
)

MixingMode = Literal["plain", "local-TF"]

_CONV_THR_PER_ATOM = Decimal("0.2e-9")
_ETOT_CONV_THR_PER_ATOM = Decimal("1e-5")
_DEFAULT_MIXING_BETA = 0.4
"""Matches v1's DEFAULT_MIXING_BETA (advice/parameters.py:17)."""
_DEFAULT_ELECTRON_MAXSTEP = 80
"""Matches v1's DEFAULT_ELECTRON_MAXSTEP (advice/parameters.py:18)."""


def _frozen_ns_message(iterations: int | str) -> str:
    return (
        f"mixing_fixed_ns = {iterations} holds the Hubbard occupation matrix at "
        f"its starting value for the first {iterations} SCF iterations, and pw.x "
        "can report convergence inside that window; the resulting energies, "
        "forces and stresses are then not self-consistent DFT+U results. Use a "
        "nonzero value only for a preparatory run whose output seeds a separate "
        "run with ns free."
    )


MIXING_FIXED_NS_WARNING = Warning(
    code="convergence.mixing_fixed_ns_freezes_hubbard_occupations",
    level="warning",
    category="convergence",
    message=_frozen_ns_message("N"),
)
"""Catalogue entry; ``_frozen_ns_warnings`` names the value."""

WARNING_CATALOGUE = (MIXING_FIXED_NS_WARNING,)
"""Every warning code this module can emit -- ``capabilities.py``'s
``warnings[]`` catalogue aggregates one of these tuples per advisor."""


@dataclass(frozen=True, slots=True)
class ConvergenceDecision:
    conv_thr: float
    etot_conv_thr: float
    mixing_beta: float
    electron_maxstep: int
    mixing_mode: MixingMode
    mixing_fixed_ns: int | None
    warnings: tuple[Warning, ...] = ()


class ConvergenceHumanInput(HumanInput):
    conv_thr: float | None = Field(default=None, gt=0)
    etot_conv_thr: float | None = Field(default=None, gt=0)
    mixing_beta: float | None = Field(default=None, gt=0)
    electron_maxstep: int | None = Field(default=None, gt=0)
    mixing_mode: MixingMode | None = None
    mixing_fixed_ns: int | None = Field(default=None, ge=0)


class ConvergenceLlmInput(LlmInput):
    mixing_beta: float | None = Field(default=None, gt=0)
    electron_maxstep: int | None = Field(default=None, gt=0)
    mixing_mode: MixingMode | None = None
    mixing_fixed_ns: int | None = Field(default=None, ge=0)


def convergence(
    nat: int,
    hubbard: FieldState[HubbardUDecision] | None = None,
    geometry: FieldState[GeometryFacts] | None = None,
    human: ConvergenceHumanInput | None = None,
    llm: ConvergenceLlmInput | None = None,
) -> FieldState[ConvergenceDecision]:
    human = human or ConvergenceHumanInput()
    llm = llm or ConvergenceLlmInput()

    local_tf = bool(geometry is not None and geometry.ok and geometry.value.vacuum_axes)

    conv_thr = (
        human.conv_thr
        if human.conv_thr is not None
        else float(nat * _CONV_THR_PER_ATOM)
    )
    mixing_fixed_ns = _pick(human.mixing_fixed_ns, llm.mixing_fixed_ns, None)
    decision = ConvergenceDecision(
        conv_thr=conv_thr,
        etot_conv_thr=(
            human.etot_conv_thr
            if human.etot_conv_thr is not None
            else float(nat * _ETOT_CONV_THR_PER_ATOM)
        ),
        mixing_beta=_pick(human.mixing_beta, llm.mixing_beta, _DEFAULT_MIXING_BETA),
        electron_maxstep=_pick(
            human.electron_maxstep, llm.electron_maxstep, _DEFAULT_ELECTRON_MAXSTEP
        ),
        mixing_mode=_pick(
            human.mixing_mode, llm.mixing_mode, "local-TF" if local_tf else "plain"
        ),
        mixing_fixed_ns=mixing_fixed_ns,
        warnings=_frozen_ns_warnings(mixing_fixed_ns, hubbard),
    )
    field_sources = field_sources_from(
        human, llm, fields=ConvergenceHumanInput.model_fields
    )
    return Resolved(decision, Provenance.from_field_sources(field_sources))


def _frozen_ns_warnings(
    mixing_fixed_ns: int | None, hubbard: FieldState[HubbardUDecision] | None
) -> tuple[Warning, ...]:
    """``MIXING_FIXED_NS_WARNING`` naming the value when a nonzero
    ``mixing_fixed_ns`` meets a resolved decision that applies a U (#166);
    nothing otherwise."""
    applies_u = hubbard is not None and hubbard.ok and bool(hubbard.value.u_values)
    if not (mixing_fixed_ns and applies_u):
        return ()
    message = _frozen_ns_message(mixing_fixed_ns)
    return (MIXING_FIXED_NS_WARNING.model_copy(update={"message": message}),)


def _pick[T](human_value: T | None, llm_value: T | None, default: T) -> T:
    if human_value is not None:
        return human_value
    if llm_value is not None:
        return llm_value
    return default
