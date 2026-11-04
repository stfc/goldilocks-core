from __future__ import annotations

from goldilocks_core.advisors.functional import (
    DEFAULT_FUNCTIONAL,
    FunctionalHumanInput,
    FunctionalLlmInput,
    functional,
)


def test_defaults_to_pbesol() -> None:
    state = functional()

    assert state.ok
    assert state.value == DEFAULT_FUNCTIONAL
    assert state.source == "heuristic"


def test_human_override_normalizes_a_recognized_alias() -> None:
    state = functional(human=FunctionalHumanInput(functional="perdewburkeernzerhof"))

    assert state.value == "PBE"
    assert state.source == "human"


def test_human_override_passes_through_an_unrecognized_label_unchanged() -> None:
    """hubbard_u.py's functional==hybrid suppression rule needs "hybrid" to
    be settable here even though no functional-label table recognizes it."""
    state = functional(human=FunctionalHumanInput(functional="hybrid"))

    assert state.value == "hybrid"
    assert state.source == "human"


def test_llm_override_is_used_when_no_human_override_is_given() -> None:
    state = functional(llm=FunctionalLlmInput(functional="lda"))

    assert state.value == "LDA"
    assert state.source == "llm"


def test_human_override_takes_priority_over_llm_override() -> None:
    state = functional(
        human=FunctionalHumanInput(functional="pbe"),
        llm=FunctionalLlmInput(functional="lda"),
    )

    assert state.value == "PBE"
    assert state.source == "human"
