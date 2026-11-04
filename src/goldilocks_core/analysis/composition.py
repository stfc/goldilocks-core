"""composition: which elements are present, and which periodic-table
families they belong to.

Ported as content from v1's ``legacy_analysis.py:104-123`` (v2 epic 4, #1) --
the element/transition-metal/lanthanide/actinide classification itself is
correct, reusable domain knowledge; only the failure handling of the rest of
v1's ``analyze_structure`` was wrong (see ``symmetry.py``/``geometry.py``).

No ``heavy_elements`` field here, unlike v1: "heavy" means different things
to different consumers -- ``needs_soc.py`` needs atomic-number-and-block
awareness specifically for spin-orbit relevance, not a generic label every
caller would reuse the same way. One ambiguous shared definition was the
actual bug; giving each consumer its own is the fix, not renaming the same
mistake.

No ``human``/``llm`` override here, unlike ``is_metal.py``/``is_magnetic.py``/
``needs_soc.py``: which elements a structure contains is directly observable
from the structure, not a judgement call anything would plausibly want to
override.
"""

from __future__ import annotations

from dataclasses import dataclass

from pymatgen.core import Structure
from pymatgen.core.periodic_table import Element

from goldilocks_core.resolution import FieldState, Provenance, Resolved


@dataclass(frozen=True, slots=True)
class CompositionFacts:
    elements: tuple[str, ...]
    transition_metals: tuple[str, ...]
    lanthanides: tuple[str, ...]
    actinides: tuple[str, ...]


def composition(structure: Structure) -> FieldState[CompositionFacts]:
    """Always resolves: element classification is exact, structure-derived
    computation with no external dependency and no failure mode. Each
    element is listed once, however its sites are decorated (a spin from
    an applied magnetic ordering, or an oxidation state from a CIF that
    types Fe2+ and Fe3+ separately)."""
    elements = tuple(
        sorted({element.symbol for element in structure.composition.elements})
    )
    periodic_elements = tuple(Element(symbol) for symbol in elements)
    facts = CompositionFacts(
        elements=elements,
        transition_metals=tuple(
            element.symbol
            for element in periodic_elements
            if element.is_transition_metal
        ),
        lanthanides=tuple(
            element.symbol for element in periodic_elements if element.is_lanthanoid
        ),
        actinides=tuple(
            element.symbol for element in periodic_elements if element.is_actinoid
        ),
    )
    return Resolved(facts, Provenance(source="heuristic"))
