from __future__ import annotations

from pymatgen.core import Lattice, Structure

from goldilocks_core.analysis.composition import composition
from goldilocks_core.analysis.needs_correlation import (
    NeedsCorrelationHumanInput,
    NeedsCorrelationLlmInput,
    needs_correlation,
)
from goldilocks_core.resolution import Blocked


def _composition_for(*species: str):
    lattice = Lattice.cubic(4.0)
    coords = [[i / len(species), 0.0, 0.0] for i in range(len(species))]
    return composition(Structure(lattice, species, coords))


def test_transition_metal_oxide_needs_correlation() -> None:
    """NiO: a canonical Mott insulator GGA gets wrong without +U."""
    state = needs_correlation(_composition_for("Ni", "O"))

    assert state.ok
    assert state.value is True
    assert state.source == "heuristic"


def test_transition_metal_fluoride_needs_correlation() -> None:
    state = needs_correlation(_composition_for("Fe", "F", "F"))

    assert state.value is True


def test_metallic_transition_metal_does_not_need_correlation() -> None:
    """stfc/goldilocks-core#175's "metallic Fe gets U=5.3" bug: no anion
    means no correlation trigger, even with a transition metal present."""
    state = needs_correlation(_composition_for("Fe"))

    assert state.value is False


def test_anion_without_a_correlated_element_does_not_need_correlation() -> None:
    state = needs_correlation(_composition_for("Na", "O"))

    assert state.value is False


def test_blocked_composition_propagates() -> None:
    state = needs_correlation(Blocked(by="synthetic failure"))

    assert not state.ok
    assert state.status == "blocked"
    assert state.root_cause() == "synthetic failure"


def test_human_override_wins_over_heuristic() -> None:
    state = needs_correlation(
        _composition_for("Fe"), human=NeedsCorrelationHumanInput(needs_correlation=True)
    )

    assert state.value is True
    assert state.source == "human"


def test_llm_override_is_used_when_no_human_override_is_given() -> None:
    state = needs_correlation(
        _composition_for("Ni", "O"),
        llm=NeedsCorrelationLlmInput(needs_correlation=False),
    )

    assert state.value is False
    assert state.source == "llm"
