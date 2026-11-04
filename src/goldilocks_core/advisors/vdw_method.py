"""vdw_method: whether to add a dispersion (van der Waals) correction, and
which one, from geometry and the chosen functional.

Ported as decision content from v1's `advice/parameters.py:_advise_vdw`
(lines 309-368, v2 epic 5, #5): low-dimensional structures default to D3BJ,
3D/undetermined defaults to no correction, operator hints always win. That
logic is correct and is reused; two things change around it.

First, the tri-state rewrite: v1's "hint ignored because vdW is off" case
was smuggled into a free-text warning string (lines 350-355) rather than a
structured field -- still surfaced as a warning here (nowhere else to put a
"you asked for X, it was not applied" note), but on a value that is always
``Resolved``, not a silent default with no way to tell it apart from a real
decision.

Second, this now reads `functional` (this epic's `advisors/functional.py`)
to avoid recommending a correction on top of a functional that already
includes dispersion physics -- v1 had no functional advisor to read at all,
so this check did not exist. Nothing in `functionals.py`'s recognized label
table is currently a vdW-inclusive functional (only LDA/PBE/PBEsol), so this
mostly guards a future functional this epic does not otherwise build.

The functional also decides whether the low-dimensional D3BJ default is
possible at all: D3(BJ) needs damping parameters for the functional, which
Quantum ESPRESSO ships only for `functionals.D3BJ_FUNCTIONALS` (#141). For
any other functional, LDA included, the heuristic adds no correction and
warns (`vdw.d3bj_unavailable_for_functional`). A human or llm `use_vdw` is
still resolved as given; `checks.check_all` refuses `use_vdw=True` with such
a functional.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from goldilocks_core.analysis.geometry import GeometryFacts
from goldilocks_core.functionals import D3BJ_FUNCTIONALS, has_d3bj_parameters
from goldilocks_core.inputs.overrides import HumanInput, LlmInput
from goldilocks_core.resolution import (
    Blocked,
    FieldState,
    Provenance,
    Resolved,
    Warning,
    blocked_by,
)

VdwMethod = Literal["d3bj"]

_VDW_INCLUSIVE_FUNCTIONAL_MARKERS = ("vdw", "vv10")
"""Substrings that flag a functional as already including dispersion physics
-- checked case-insensitively so a future "vdW-DF"/"rVV10"-labelled
functional is not double-corrected. No functional this codebase currently
recognizes matches; this is a guard for one that eventually will."""

_D3BJ_FUNCTIONAL_LABELS = ", ".join(sorted(D3BJ_FUNCTIONALS))

WARNING_CATALOGUE = (
    Warning(
        code="vdw.double_counting_avoided",
        level="info",
        category="vdw",
        message=(
            "a vdW correction method was requested, but the chosen functional "
            "already includes dispersion physics; no correction was added to "
            "avoid double-counting it."
        ),
    ),
    Warning(
        code="vdw.d3bj_unavailable_for_functional",
        level="warning",
        category="vdw",
        message=(
            "a low-dimensional structure defaults to D3(BJ) dispersion, but "
            "Quantum ESPRESSO's DFT-D3 has no parameters for the chosen "
            "functional; no correction was added. Choose a functional with "
            f"D3(BJ) parameters ({_D3BJ_FUNCTIONAL_LABELS}) if dispersion matters."
        ),
    ),
)
"""Every warning code this module can emit -- ``capabilities.py``'s
``warnings[]`` catalogue aggregates one of these tuples per advisor."""


@dataclass(frozen=True, slots=True)
class VdwFacts:
    use_vdw: bool
    method: VdwMethod | None
    warnings: tuple[Warning, ...] = ()


class VdwMethodHumanInput(HumanInput):
    use_vdw: bool | None = None
    method: VdwMethod | None = None


class VdwMethodLlmInput(LlmInput):
    use_vdw: bool | None = None
    method: VdwMethod | None = None


def vdw_method(
    geometry: FieldState[GeometryFacts],
    functional: str,
    human: VdwMethodHumanInput | None = None,
    llm: VdwMethodLlmInput | None = None,
) -> FieldState[VdwFacts]:
    human = human or VdwMethodHumanInput()
    llm = llm or VdwMethodLlmInput()

    if human.use_vdw is not None:
        return Resolved(
            _resolved_facts(human.use_vdw, human.method), Provenance(source="human")
        )
    ml_value: bool | None = None  # no ml model wired yet; stubbed until epic 11
    if ml_value is not None:
        return Resolved(_resolved_facts(ml_value, None), Provenance(source="ml"))
    if llm.use_vdw is not None:
        return Resolved(
            _resolved_facts(llm.use_vdw, llm.method), Provenance(source="llm")
        )

    if _is_vdw_inclusive(functional):
        warnings: tuple[Warning, ...] = ()
        if human.method is not None or llm.method is not None:
            warnings = (
                Warning(
                    code="vdw.double_counting_avoided",
                    level="info",
                    category="vdw",
                    message=(
                        f"A vdW correction method was requested, but "
                        f"{functional!r} already includes dispersion physics; "
                        "no correction was added to avoid double-counting it."
                    ),
                ),
            )
        return Resolved(
            VdwFacts(use_vdw=False, method=None, warnings=warnings),
            Provenance(
                source="heuristic",
                source_note=f"{functional} already includes dispersion physics.",
            ),
        )

    if not geometry.ok:
        return Blocked(by=blocked_by(geometry))
    return _heuristic(geometry.value, functional)


def _resolved_facts(use_vdw: bool, method: VdwMethod | None) -> VdwFacts:
    return VdwFacts(use_vdw=use_vdw, method=(method or "d3bj") if use_vdw else None)


def _is_vdw_inclusive(functional: str) -> bool:
    lowered = functional.lower()
    return any(marker in lowered for marker in _VDW_INCLUSIVE_FUNCTIONAL_MARKERS)


def _heuristic(facts: GeometryFacts, functional: str) -> FieldState[VdwFacts]:
    if not facts.low_dimensional:
        return Resolved(
            VdwFacts(use_vdw=False, method=None),
            Provenance(
                source="heuristic",
                source_note=("3D bulk structure; no vdW correction by default."),
            ),
        )
    if not has_d3bj_parameters(functional):
        warning = Warning(
            code="vdw.d3bj_unavailable_for_functional",
            level="warning",
            category="vdw",
            message=(
                f"No D3(BJ) dispersion correction was added for this "
                f"{facts.dimensionality} structure: Quantum ESPRESSO's DFT-D3 has "
                f"no parameters for {functional!r}, so pw.x would stop with "
                "'functional name unknown'. Choose a functional with D3(BJ) "
                f"parameters ({_D3BJ_FUNCTIONAL_LABELS}) if dispersion matters."
            ),
        )
        return Resolved(
            VdwFacts(use_vdw=False, method=None, warnings=(warning,)),
            Provenance(
                source="heuristic",
                source_note=(
                    f"Connectivity-derived {facts.dimensionality} classification "
                    f"would default to D3BJ, but DFT-D3 has no D3(BJ) parameters "
                    f"for {functional}, so no correction is added."
                ),
            ),
        )
    return Resolved(
        VdwFacts(use_vdw=True, method="d3bj"),
        Provenance(
            source="heuristic",
            source_note=(
                f"Connectivity-derived {facts.dimensionality} classification "
                "indicates a low-dimensional structure; D3BJ is the "
                "conservative default because dispersion may be important."
            ),
        ),
    )
