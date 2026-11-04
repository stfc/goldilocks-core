from __future__ import annotations

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.analysis.composition import composition
from goldilocks_core.analysis.needs_soc import NeedsSocLlmInput, needs_soc
from goldilocks_core.resolution import Blocked


def _composition_for(*species: str):
    lattice = Lattice.cubic(4.0)
    coords = [[i / len(species), 0.0, 0.0] for i in range(len(species))]
    return composition(Structure(lattice, species, coords))


@pytest.mark.parametrize("symbol", ["Rb", "Sr", "Ba"])
def test_heavy_s_block_elements_do_not_need_soc(symbol: str) -> None:
    """stfc/goldilocks-core#175: v1's row>=5 rule flagged these. s orbitals
    have zero orbital angular momentum, so there is no first-order
    spin-orbit splitting to speak of, no matter how heavy the atom is."""
    state = needs_soc(_composition_for(symbol, "Cl"))

    assert state.ok
    assert state.value is False


@pytest.mark.parametrize("symbol", ["I", "Bi", "Pb"])
def test_heavy_non_s_block_elements_need_soc(symbol: str) -> None:
    state = needs_soc(_composition_for(symbol, "Cl"))

    assert state.ok
    assert state.value is True


def test_light_elements_do_not_need_soc() -> None:
    state = needs_soc(_composition_for("Si"))

    assert state.value is False


def test_blocked_composition_propagates_as_blocked_not_a_silent_default() -> None:
    """The Blocked-propagation pattern from goldilocks-core-design.md:299-310,
    demonstrated for real: needs_soc reads composition, so a failed
    composition must poison needs_soc too, not silently compute False."""
    blocked_composition = Blocked(by="synthetic failure")

    state = needs_soc(blocked_composition)

    assert not state.ok
    assert state.status == "blocked"
    assert state.root_cause() == "synthetic failure"


def test_an_llm_value_wins_over_the_heuristic() -> None:
    state = needs_soc(_composition_for("Si"), llm=NeedsSocLlmInput(needs_soc=True))

    assert state.value is True
    assert state.source == "llm"
