"""needs_correlation: whether a Hubbard +U (or hybrid) correction is likely
needed, from composition.

Gap-fill for v2 epic 4 (#1): epic 4's scope checklist named five facts
(``is_metal``, ``is_magnetic``, ``symmetry``, ``geometry``, ``needs_soc``) but
epic 5 (#5) depends on a sixth, ``needs_correlation``, that epic 4 never
built. Added here as a small, well-defined addition rather than a separate
issue, following ``needs_soc.py``'s established shape (reads ``composition``,
demonstrates the same ``Blocked`` propagation).

The heuristic is Materials Project's own screening rule for when +U matters
(goldilocks-core-design.md:2587-2592): transition-metal/lanthanide/actinide
compounds with an O or F anion, where localized d/f orbitals are poorly
described by LDA/GGA/PBE without a Hubbard correction. This is deliberately
composition-only and conservative -- it says "a correction is worth
considering," not "here is the U value" (that is ``hubbard_u.py``'s job, one
tier up).
"""

from __future__ import annotations

from goldilocks_core.analysis.composition import CompositionFacts
from goldilocks_core.inputs.overrides import HumanInput, LlmInput
from goldilocks_core.resolution import (
    Blocked,
    FieldState,
    Provenance,
    Resolved,
    blocked_by,
)

_CORRELATION_ANIONS = frozenset({"O", "F"})
"""Materials Project's own +U screening anions -- oxides and fluorides of
correlated-electron elements, where GGA/LDA's self-interaction error is
worst."""


class NeedsCorrelationHumanInput(HumanInput):
    needs_correlation: bool | None = None


class NeedsCorrelationLlmInput(LlmInput):
    needs_correlation: bool | None = None


def needs_correlation(
    composition: FieldState[CompositionFacts],
    human: NeedsCorrelationHumanInput | None = None,
    llm: NeedsCorrelationLlmInput | None = None,
) -> FieldState[bool]:
    human = human or NeedsCorrelationHumanInput()
    llm = llm or NeedsCorrelationLlmInput()
    if human.needs_correlation is not None:
        return Resolved(human.needs_correlation, Provenance(source="human"))
    ml_value: bool | None = None  # no ml model wired yet; stubbed until epic 11
    if ml_value is not None:
        return Resolved(ml_value, Provenance(source="ml"))
    if llm.needs_correlation is not None:
        return Resolved(llm.needs_correlation, Provenance(source="llm"))
    if not composition.ok:
        return Blocked(by=blocked_by(composition))
    return _heuristic(composition.value)


def _heuristic(facts: CompositionFacts) -> FieldState[bool]:
    has_correlated_element = bool(
        facts.transition_metals or facts.lanthanides or facts.actinides
    )
    has_correlation_anion = any(
        symbol in _CORRELATION_ANIONS for symbol in facts.elements
    )
    needs_it = has_correlated_element and has_correlation_anion
    return Resolved(needs_it, Provenance(source="heuristic"))
