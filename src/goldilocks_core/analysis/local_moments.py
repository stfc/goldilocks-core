"""local_moments: which elements of a structure carry a local magnetic
moment, and whether it holds an open-shell radical (#142).

The package's one open-shell model: ``is_magnetic``'s heuristic tier reads
it, and so does the antiferromagnetic sublattice. Two exclusive rules decide
the moment-bearing elements, and a third looks for radicals:

- **ionic**, when a chalcogen or halogen anion (O, S, Se, Te, F, Cl, Br, I)
  is present. The first ``Composition.oxi_state_guesses()`` guess fixes the
  shell count of each transition metal, lanthanide and actinide: the 4f
  count Z - 54 - ox for a lanthanide, the 5f count Z - 86 - ox for an
  actinide (La and Ac too, although pymatgen also calls them transition
  metals), the d count group - ox otherwise. A shell strictly between empty
  and full is open, including a fractional mixed-valence count (Fe3O4's Fe
  +8/3). An element the guess does not cover (pymatgen guesses nothing for
  GdI2, Fe3GeTe2, NpO2 or US) carries a moment when every one of its
  ``common_oxidation_states`` leaves the shell open (Gd +3 is 4f7; Fe +2
  and +3 are d6 and d5), and is undecided otherwise: a composition the
  common states cannot charge-balance holds the element in another state,
  so a closed common state is no evidence (US, a ferromagnet, against U's
  common +6, 5f0).
- **metallic**, otherwise: elements, intermetallics, nitrides, carbides,
  borides, hydrides and pnictides, which formal oxidation states do not
  describe (fcc Ni is not d10 Ni0, TiN is not d1 Ti3+). Cr, Mn, Fe, Co and Ni
  carry moments, as do the lanthanides with an open 4f at their metallic
  valence, Ce to Tm (not La 4f0, Yb 4f14 or Lu 4f14), and, in a compound,
  the actinides Pa to Md, whose 5f shells localize once the actinide atoms
  are kept apart (UN). The elemental actinide metals (alpha-U, alpha-Pu)
  have itinerant 5f bands and no moment; nor do Sc-V, Cu, Zn or the 4d and
  5d metals.
- **radical**, in any context: an open-shell main-group atom (groups 1 and
  13-17) with no neighbour within 1.5x the sum of the two covalent radii
  (two C atoms in a box), or an O2 or S2 molecule bonded only to its partner
  (a triplet; solid O2's molecules are 2.5x that sum apart). Bonded s-p
  solids sit well inside the cutoff: NaCl at 1.05, bcc Na at 1.09, LiH at
  1.25. The radii are pymatgen's ``CovalentRadius`` (Cordero et al., Dalton
  Trans. 2008), tabulated up to Cm.

``Unavailable`` for an undecided element, and for an element without a
covalent radius in a structure with an open-shell main-group atom to test.
A disordered structure is refused before it gets here
(``inputs.structure.require_ordered``, #224).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pymatgen.core import PeriodicNeighbor, Structure
from pymatgen.core.molecule_structure_comparator import CovalentRadius
from pymatgen.core.periodic_table import Element

from goldilocks_core.resolution import FieldState, Provenance, Resolved, Unavailable

MomentRule = Literal["ionic", "metallic"]

_IONIC_ANIONS = frozenset({"O", "S", "Se", "Te", "F", "Cl", "Br", "I"})

_METALLIC_MOMENTS = frozenset(
    {"Cr", "Mn", "Fe", "Co", "Ni"}
    | {"Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm"}
)
"""The itinerant 3d magnets, and the lanthanides with an open 4f shell at
their metallic valence."""
_OPEN_5F_IN_COMPOUNDS = frozenset(
    {"Pa", "U", "Np", "Pu", "Am", "Cm", "Bk", "Cf", "Es", "Fm", "Md"}
)
"""The actinides with an open 5f shell at their metallic valence: a moment
in a compound, none in the elemental metal."""

_OPEN_SHELL_MAIN_GROUPS = frozenset({1, 13, 14, 15, 16, 17})
_TRIPLET_DIMERS = frozenset({"O", "S"})
_BOND_TOLERANCE = 1.5
"""A neighbour within this multiple of the covalent-radius sum is bonded."""


@dataclass(frozen=True, slots=True)
class LocalMomentFacts:
    """``moment_elements``: the sorted symbols whose sites carry a local d
    or f moment. ``shell_counts``: the d or f electron count of each
    transition metal, lanthanide and actinide the oxidation-state guess
    covers (ionic rule only; capped at a full shell, so Hg+ is 10).
    ``radical``: an isolated open-shell main-group atom or an O2/S2
    molecule is present. ``rule``: the rule that decided
    ``moment_elements``."""

    moment_elements: tuple[str, ...]
    shell_counts: dict[str, float]
    radical: bool
    rule: MomentRule


def local_moments(structure: Structure) -> FieldState[LocalMomentFacts]:
    """The local moments of ``structure`` (module docstring), always from
    the heuristic: there is no model or override for them."""
    radical = _radical(structure)
    if isinstance(radical, Unavailable):
        return radical

    elements = tuple(
        Element(symbol)
        for symbol in sorted({element.symbol for element in structure.composition})
    )
    if not _IONIC_ANIONS.isdisjoint(element.symbol for element in elements):
        ionic = _ionic_moments(structure, elements)
        if isinstance(ionic, Unavailable):
            return ionic
        moment_elements, shell_counts = ionic
        rule: MomentRule = "ionic"
    else:
        moment_elements, shell_counts = _metallic_moments(elements), {}
        rule = "metallic"
    facts = LocalMomentFacts(
        moment_elements=moment_elements,
        shell_counts=shell_counts,
        radical=radical,
        rule=rule,
    )
    return Resolved(facts, Provenance(source="heuristic"))


def _ionic_moments(
    structure: Structure, elements: tuple[Element, ...]
) -> tuple[tuple[str, ...], dict[str, float]] | Unavailable:
    """The ionic rule: moment-bearing elements and shell counts, or the
    elements it cannot decide. Only d- and f-shell elements are judged, so
    the composition is not guessed without one."""
    shell_elements = [element for element in elements if _has_d_or_f_shell(element)]
    if not shell_elements:
        return (), {}
    guesses = structure.composition.oxi_state_guesses()
    guess = guesses[0] if guesses else {}
    moment_elements: list[str] = []
    shell_counts: dict[str, float] = {}
    undecided: list[Element] = []
    for element in shell_elements:
        if element.symbol in guess:
            count = _shell_count(element, guess[element.symbol])
            shell_counts[element.symbol] = count
            if _is_open(element, count):
                moment_elements.append(element.symbol)
        elif _open_in_every_common_state(element):
            moment_elements.append(element.symbol)
        else:
            undecided.append(element)
    if undecided:
        return Unavailable(reason=_undecided_reason(undecided))
    return tuple(moment_elements), shell_counts


def _metallic_moments(elements: tuple[Element, ...]) -> tuple[str, ...]:
    compound = len(elements) > 1
    return tuple(
        element.symbol
        for element in elements
        if element.symbol in _METALLIC_MOMENTS
        or (compound and element.symbol in _OPEN_5F_IN_COMPOUNDS)
    )


def _has_d_or_f_shell(element: Element) -> bool:
    return element.is_transition_metal or element.is_lanthanoid or element.is_actinoid


def _capacity(element: Element) -> float:
    return 14.0 if element.is_lanthanoid or element.is_actinoid else 10.0


def _shell_count(element: Element, oxidation_state: float) -> float:
    """The 4f, 5f or d electron count at ``oxidation_state``, capped at a
    full shell: electrons past it fill the next s shell (Hg+ is 5d10 6s1)."""
    if element.is_lanthanoid:
        count = element.Z - 54 - oxidation_state
    elif element.is_actinoid:
        count = element.Z - 86 - oxidation_state
    else:
        count = element.group - oxidation_state
    return min(float(count), _capacity(element))


def _is_open(element: Element, count: float) -> bool:
    return 0 < count < _capacity(element)


def _open_in_every_common_state(element: Element) -> bool:
    states = element.common_oxidation_states
    return bool(states) and all(
        _is_open(element, _shell_count(element, state)) for state in states
    )


def _undecided_reason(elements: list[Element]) -> str:
    described = ", ".join(
        f"{element.symbol} ({_signed(element.common_oxidation_states) or 'none'})"
        for element in elements
    )
    return (
        "no oxidation-state guess for this composition, and not every common "
        f"oxidation state of {described} leaves an open d or f shell"
    )


def _signed(states: tuple[int, ...]) -> str:
    return ", ".join(f"{state:+d}" for state in states)


def _radical(structure: Structure) -> bool | Unavailable:
    """Whether an open-shell main-group atom of ``structure`` has no bonded
    neighbour, or is half of an O2/S2 molecule bonded only to its partner."""
    indices = [
        index
        for index, site in enumerate(structure)
        if Element(site.specie.symbol).group in _OPEN_SHELL_MAIN_GROUPS
    ]
    if not indices:
        return False
    missing = sorted(
        {site.specie.symbol for site in structure} - CovalentRadius.radius.keys()
    )
    if missing:
        return Unavailable(
            reason=f"no covalent radius for {', '.join(missing)} to test "
            "open-shell main-group atoms for isolation"
        )
    bonded = _bonded_neighbours(structure, indices)
    return any(
        not partners or _triplet_dimer(structure[index].specie.symbol, partners, bonded)
        for index, partners in bonded.items()
    )


def _bonded_neighbours(
    structure: Structure, indices: list[int]
) -> dict[int, list[PeriodicNeighbor]]:
    """The neighbours of each site in ``indices`` within ``_BOND_TOLERANCE``
    times the covalent-radius sum."""
    radius = CovalentRadius.radius
    reach = _BOND_TOLERANCE * 2 * max(radius[site.specie.symbol] for site in structure)
    found = structure.get_all_neighbors(
        reach, sites=[structure[index] for index in indices]
    )
    return {
        index: [
            neighbour
            for neighbour in neighbours
            if neighbour.nn_distance
            <= _BOND_TOLERANCE
            * (radius[structure[index].specie.symbol] + radius[neighbour.specie.symbol])
        ]
        for index, neighbours in zip(indices, found, strict=True)
    }


def _triplet_dimer(
    symbol: str,
    partners: list[PeriodicNeighbor],
    bonded: dict[int, list[PeriodicNeighbor]],
) -> bool:
    """An O or S atom whose one bonded neighbour is an atom of the same
    element bonded only to it."""
    if symbol not in _TRIPLET_DIMERS or len(partners) != 1:
        return False
    (partner,) = partners
    return partner.specie.symbol == symbol and len(bonded[partner.index]) == 1
