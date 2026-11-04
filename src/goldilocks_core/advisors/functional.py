"""functional: which exchange-correlation functional to use.

New in v2 (v2 epic 5, #5): v1 never actually decided this -- `advice/
parameters.py`'s `_advise_pseudopotential_requirements` took
`intent.functional` as a straight passthrough of whatever
`CalculationIntent.functional` (`calculation.py`) already defaulted to, with
no resolver cascade of its own. This gives it one, matching every other
advisor in this epic: human override wins, heuristic default otherwise.

Heuristic default is "PBEsol", unchanged from v1's `CalculationIntent`
default -- a safe, broadly-applicable GGA for solids, not a new choice.

Deliberately does not validate the human-supplied label against a fixed
enum: `hubbard_u.py`'s "stop adding +U for hybrid functionals" rule
(goldilocks-core-design.md:2626-2627) needs "hybrid" to be a value a human
can set here, even though nothing in this epic builds hybrid-functional QE
generation itself (that is out of scope -- see `functionals.py`'s recognized
label table, which only normalizes LDA/PBE/PBEsol). `normalize_functional_label`
still runs, so a recognized alias normalizes to its canonical spelling; an
unrecognized one (like "hybrid") passes through unchanged rather than being
rejected.
"""

from __future__ import annotations

from goldilocks_core.functionals import normalize_functional_label
from goldilocks_core.inputs.overrides import HumanInput, LlmInput
from goldilocks_core.resolution import FieldState, Provenance, Resolved

DEFAULT_FUNCTIONAL = "PBEsol"

HYBRID_FUNCTIONAL = "hybrid"
"""The value `hubbard_u.py` checks for to suppress +U
(goldilocks-core-design.md:2626-2627). Not produced by the heuristic tier --
only a human (or, later, ml/llm) can select it."""


class FunctionalHumanInput(HumanInput):
    functional: str | None = None


class FunctionalLlmInput(LlmInput):
    functional: str | None = None


def functional(
    human: FunctionalHumanInput | None = None,
    llm: FunctionalLlmInput | None = None,
) -> FieldState[str]:
    human = human or FunctionalHumanInput()
    llm = llm or FunctionalLlmInput()
    if human.functional is not None:
        return Resolved(_normalize(human.functional), Provenance(source="human"))
    ml_value: str | None = None  # no ml model wired yet; stubbed until epic 11
    if ml_value is not None:
        return Resolved(_normalize(ml_value), Provenance(source="ml"))
    if llm.functional is not None:
        return Resolved(_normalize(llm.functional), Provenance(source="llm"))
    return Resolved(DEFAULT_FUNCTIONAL, Provenance(source="heuristic"))


def _normalize(label: str) -> str:
    return normalize_functional_label(label) or label
