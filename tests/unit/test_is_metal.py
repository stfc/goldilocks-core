from __future__ import annotations

import pytest
from pydantic import ValidationError
from pymatgen.core import Lattice, Structure
from support import written_afm_nickel, written_afm_nickel_oxide

from goldilocks_core.analysis.is_metal import (
    IsMetalHumanInput,
    IsMetalLlmInput,
    all_metallic,
    is_metal,
)


def _structure(*species: str) -> Structure:
    lattice = Lattice.cubic(4.0)
    coords = [[i / len(species), 0.0, 0.0] for i in range(len(species))]
    return Structure(lattice, species, coords)


_ORIGIN_AND_BODY_CENTRE = [[0, 0, 0], [0.5, 0.5, 0.5]]

_COMPOUNDS_WITH_NON_METALS = {
    # Ionic insulators and semiconductors the anion-stripping rule called metal.
    "NaCl": ("Fm-3m", Lattice.cubic(5.64), ["Na", "Cl"], _ORIGIN_AND_BODY_CENTRE),
    "MgO": ("Fm-3m", Lattice.cubic(4.21), ["Mg", "O"], _ORIGIN_AND_BODY_CENTRE),
    "LiF": ("Fm-3m", Lattice.cubic(4.03), ["Li", "F"], _ORIGIN_AND_BODY_CENTRE),
    "LiH": ("Fm-3m", Lattice.cubic(4.08), ["Li", "H"], _ORIGIN_AND_BODY_CENTRE),
    "CsCl": ("Pm-3m", Lattice.cubic(4.12), ["Cs", "Cl"], _ORIGIN_AND_BODY_CENTRE),
    "CaF2": (
        "Fm-3m",
        Lattice.cubic(5.46),
        ["Ca", "F"],
        [[0, 0, 0], [0.25, 0.25, 0.25]],
    ),
    "CdTe": (
        "F-43m",
        Lattice.cubic(6.48),
        ["Cd", "Te"],
        [[0, 0, 0], [0.25, 0.25, 0.25]],
    ),
    "ZnO": (
        "P6_3mc",
        Lattice.hexagonal(3.25, 5.21),
        ["Zn", "O"],
        [[1 / 3, 2 / 3, 0], [1 / 3, 2 / 3, 0.382]],
    ),
    "GaN": (
        "P6_3mc",
        Lattice.hexagonal(3.19, 5.19),
        ["Ga", "N"],
        [[1 / 3, 2 / 3, 0], [1 / 3, 2 / 3, 0.377]],
    ),
    # Metallic oxides and nitrides (stfc/goldilocks-core#175): the same kind
    # of composition, so composition cannot tell them from the insulators.
    "RuO2": (
        "P4_2/mnm",
        Lattice.tetragonal(4.49, 3.11),
        ["Ru", "O"],
        [[0, 0, 0], [0.306, 0.306, 0]],
    ),
    "CrO2": (
        "P4_2/mnm",
        Lattice.tetragonal(4.42, 2.92),
        ["Cr", "O"],
        [[0, 0, 0], [0.303, 0.303, 0]],
    ),
    "ReO3": ("Pm-3m", Lattice.cubic(3.75), ["Re", "O"], [[0, 0, 0], [0.5, 0, 0]]),
    "TiN": ("Fm-3m", Lattice.cubic(4.24), ["Ti", "N"], _ORIGIN_AND_BODY_CENTRE),
    "LaNiO3": (
        "Pm-3m",
        Lattice.cubic(3.84),
        ["La", "Ni", "O"],
        [[0.5, 0.5, 0.5], [0, 0, 0], [0.5, 0, 0]],
    ),
}

_ALL_METAL_COMPOSITIONS = {
    "Al": ("Fm-3m", Lattice.cubic(4.05), ["Al"], [[0, 0, 0]]),
    "Fe": ("Im-3m", Lattice.cubic(2.87), ["Fe"], [[0, 0, 0]]),
    "NiAl": ("Pm-3m", Lattice.cubic(2.88), ["Ni", "Al"], _ORIGIN_AND_BODY_CENTRE),
    "TiNi": ("Pm-3m", Lattice.cubic(3.01), ["Ti", "Ni"], _ORIGIN_AND_BODY_CENTRE),
    "Cu3Au": ("Pm-3m", Lattice.cubic(3.75), ["Au", "Cu"], [[0, 0, 0], [0, 0.5, 0.5]]),
}


def _crystal(prototype: tuple) -> Structure:
    spacegroup, lattice, species, coords = prototype
    return Structure.from_spacegroup(spacegroup, lattice, species, coords)


@pytest.mark.parametrize("formula", sorted(_COMPOUNDS_WITH_NON_METALS))
def test_a_compound_with_non_metal_elements_is_unavailable_never_metal(
    formula: str,
) -> None:
    """#164: stripping common anions and asking whether the cations are
    metals called nearly every ionic insulator a metal. A non-metal element
    leaves the heuristic undecided, including for the real metals RuO2,
    CrO2, ReO3, TiN and LaNiO3; ``Unavailable`` still means smearing."""
    state = is_metal(_crystal(_COMPOUNDS_WITH_NON_METALS[formula]))

    assert state.status == "unavailable"
    assert state.reason.startswith("composition contains non-metal elements (")


def test_the_unavailable_reason_names_the_non_metal_elements() -> None:
    state = is_metal(_crystal(_COMPOUNDS_WITH_NON_METALS["LaNiO3"]))

    assert state.reason == (
        "composition contains non-metal elements (O); whether such a compound "
        "conducts depends on its band filling, which composition alone "
        "cannot settle"
    )


@pytest.mark.parametrize("formula", sorted(_ALL_METAL_COMPOSITIONS))
def test_an_all_metal_composition_resolves_as_metal(formula: str) -> None:
    state = is_metal(_crystal(_ALL_METAL_COMPOSITIONS[formula]))

    assert state.ok
    assert state.value == "metal"
    assert state.source == "heuristic"


@pytest.mark.parametrize("formula", sorted(_ALL_METAL_COMPOSITIONS))
def test_all_metallic_holds_for_a_composition_of_metallic_elements(
    formula: str,
) -> None:
    assert all_metallic(_crystal(_ALL_METAL_COMPOSITIONS[formula]))


@pytest.mark.parametrize("formula", sorted(_COMPOUNDS_WITH_NON_METALS))
def test_all_metallic_fails_for_any_non_metal_element(formula: str) -> None:
    """The heuristic's own rule: RuO2 and TiN fail it like NaCl, since
    composition cannot tell them apart (#164)."""
    assert not all_metallic(_crystal(_COMPOUNDS_WITH_NON_METALS[formula]))


def test_all_metallic_reads_a_written_cell_s_spin_split_species_by_element() -> None:
    """The simulated cell carries one species per spin class (Ni with spin
    +1 and -1); each is read as its element."""
    assert all_metallic(written_afm_nickel())
    assert not all_metallic(written_afm_nickel_oxide())


def test_metalloid_oxide_is_unavailable_not_a_guessed_non_metal() -> None:
    """Heuristic tier never confidently asserts non_metal from composition
    alone: SiO2 contains non-metal elements, so composition cannot settle
    whether it conducts, but that is not evidence it is an insulator either."""
    silica = _structure("Si", "O", "O")

    state = is_metal(silica)

    assert not state.ok
    assert state.status == "unavailable"


def test_human_override_wins_over_heuristic() -> None:
    silica = _structure("Si", "O", "O")

    state = is_metal(silica, human=IsMetalHumanInput(is_metal="metal"))

    assert state.ok
    assert state.value == "metal"
    assert state.source == "human"


def test_llm_override_is_used_when_no_human_override_is_given() -> None:
    silica = _structure("Si", "O", "O")

    state = is_metal(silica, llm=IsMetalLlmInput(is_metal="non_metal"))

    assert state.ok
    assert state.value == "non_metal"
    assert state.source == "llm"


def test_human_override_takes_priority_over_llm_override() -> None:
    silica = _structure("Si", "O", "O")

    state = is_metal(
        silica,
        human=IsMetalHumanInput(is_metal="metal"),
        llm=IsMetalLlmInput(is_metal="non_metal"),
    )

    assert state.value == "metal"
    assert state.source == "human"


@pytest.mark.parametrize("override", [IsMetalHumanInput, IsMetalLlmInput])
@pytest.mark.parametrize("value", [True, False, "true", "insulator"])
def test_an_override_takes_only_the_record_s_own_values(
    override: type[IsMetalHumanInput], value: object
) -> None:
    """#139: the override takes the record's Literal, the values
    /capabilities advertises; a boolean is refused, not mapped."""
    with pytest.raises(ValidationError, match="'metal' or 'non_metal'"):
        override(is_metal=value)
