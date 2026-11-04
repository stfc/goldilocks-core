from __future__ import annotations

import pytest
from pydantic import ValidationError
from pymatgen.core import Lattice, Structure

from goldilocks_core.analysis.is_magnetic import (
    IsMagneticHumanInput,
    IsMagneticLlmInput,
    is_magnetic,
)


def _structure(*species: str) -> Structure:
    lattice = Lattice.cubic(4.0)
    coords = [[i / len(species), 0.0, 0.0] for i in range(len(species))]
    return Structure(lattice, species, coords)


@pytest.mark.parametrize(
    "species",
    [
        ("Zn", "O"),  # ZnO: Zn2+ is d10
        ("Ti", "O", "O"),  # TiO2: Ti4+ is d0
        ("Cu", "Cu", "O"),  # Cu2O: Cu+ is d10
        ("Sc", "Sc", "O", "O", "O"),  # Sc2O3: Sc3+ is d0
    ],
)
def test_closed_shell_transition_metal_oxides_resolve_as_non_magnetic(
    species: tuple[str, ...],
) -> None:
    """stfc/goldilocks-core#175: v1's transition-metal-present rule
    advises spin-polarized for these -- Zn2+/Ti4+/Cu+/Sc3+ are d10/d0/d10/d0,
    closed or empty d shells, no unpaired electrons to align."""
    state = is_magnetic(_structure(*species))

    assert state.ok
    assert state.value == "non_magnetic"
    assert state.source == "heuristic"


@pytest.mark.parametrize(
    "species",
    [
        ("Fe", "Fe", "O", "O", "O"),  # Fe2O3: Fe3+ is d5
        ("Ni", "O"),  # NiO: Ni2+ is d8
    ],
)
def test_open_shell_transition_metal_oxides_resolve_as_magnetic(
    species: tuple[str, ...],
) -> None:
    state = is_magnetic(_structure(*species))

    assert state.ok
    assert state.value == "magnetic"


@pytest.mark.parametrize(
    ("species", "magnetism"),
    [
        (("La", "La", "O", "O", "O"), "non_magnetic"),  # La3+ is f0
        (("Gd", "Gd", "O", "O", "O"), "magnetic"),  # Gd3+ is f7
        (("Th", "O", "O"), "non_magnetic"),  # Th4+ is f0
        (("U", "O", "O"), "magnetic"),  # U4+ is f2
    ],
)
def test_lanthanide_and_actinide_ions_are_decided_by_their_f_count(
    species: tuple[str, ...], magnetism: str
) -> None:
    """#142: a lanthanide or actinide no longer means magnetic by its
    presence alone -- f0 La3+ and Th4+ are closed shells (the old rule
    seeded ThO2 at 5 uB)."""
    state = is_magnetic(_structure(*species))

    assert state.value == magnetism
    assert state.source == "heuristic"


def test_closed_shell_main_group_solid_resolves_as_non_magnetic(
    diamond_silicon: Structure,
) -> None:
    state = is_magnetic(diamond_silicon)

    assert state.value == "non_magnetic"


def test_an_isolated_open_shell_atom_resolves_as_magnetic(
    silicon_structure: Structure,
) -> None:
    """One Si atom in a 4 A box has no neighbour within 1.5x the
    covalent-radius sum (3.33 A), so it is an isolated 3P atom (#142)."""
    state = is_magnetic(silicon_structure)

    assert state.value == "magnetic"


def test_an_intermetallic_without_an_oxidation_state_guess_is_magnetic() -> None:
    """FeNi3 has no anion to balance charge against, so
    Composition.oxi_state_guesses() returns nothing; Fe and Ni are
    itinerant moment carriers in a metal (#142: the old rule called this
    undecidable and ran it non-magnetic)."""
    permalloy_like = _structure("Fe", "Ni", "Ni", "Ni")

    state = is_magnetic(permalloy_like)

    assert state.value == "magnetic"
    assert state.source == "heuristic"


def test_undecidable_local_moments_leave_is_magnetic_unavailable() -> None:
    """US has no oxidation-state guess, and U's common +6 (5f0) does not
    decide a compound outside its common states -- the tier must not guess
    either answer."""
    uranium_sulfide = _structure("U", "S")

    state = is_magnetic(uranium_sulfide)

    assert not state.ok
    assert state.status == "unavailable"
    assert "U" in state.reason


def test_human_override_wins_over_heuristic() -> None:
    zinc_oxide = _structure("Zn", "O")

    state = is_magnetic(zinc_oxide, human=IsMagneticHumanInput(is_magnetic="magnetic"))

    assert state.value == "magnetic"
    assert state.source == "human"


def test_llm_override_is_used_when_no_human_override_is_given() -> None:
    iron_oxide = _structure("Fe", "Fe", "O", "O", "O")

    state = is_magnetic(iron_oxide, llm=IsMagneticLlmInput(is_magnetic="non_magnetic"))

    assert state.value == "non_magnetic"
    assert state.source == "llm"


@pytest.mark.parametrize("override", [IsMagneticHumanInput, IsMagneticLlmInput])
@pytest.mark.parametrize("value", [True, False, "false", "ferromagnetic"])
def test_an_override_takes_only_the_record_s_own_values(
    override: type[IsMagneticHumanInput], value: object
) -> None:
    """#139: the override takes the record's Literal, the values
    /capabilities advertises; a boolean is refused, not mapped."""
    with pytest.raises(ValidationError, match="'magnetic' or 'non_magnetic'"):
        override(is_magnetic=value)
