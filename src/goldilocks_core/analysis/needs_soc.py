"""needs_soc: whether spin-orbit coupling is worth turning on, from composition.

Fixes the bug in stfc/goldilocks-core#175 (v2 epic 4, #1): v1's
``heavy_elements`` set is ``element.row >= 5`` -- periodic-table row, not
atomic number -- so Rb/Sr/Ba (light despite being "row 5"/"row 6") get
flagged alongside Bi/Pb/I. A single atomic-number cutoff can't fix this
either: Ba (Z=56) is heavier than I (Z=53), which the old rule correctly
flags, so raising or lowering one threshold cannot separate the two.

The actual physics: spin-orbit coupling is an L.S interaction, and s
orbitals have zero orbital angular momentum (L=0), so they carry no
first-order spin-orbit splitting at all -- heavy s-block elements (Rb, Sr,
Cs, Ba, ...) show negligible SOC in their valence/conduction states even
though the bare atom is heavy. Elements with p/d/f valence character and a
high enough atomic number do show it. So this flags any element at or above
the old rule's own first flagged element (Rb, Z=37) whose valence block is
not s, using ``pymatgen``'s per-element ``block``.

Reads ``composition`` rather than ``structure`` directly, per
goldilocks-core-design.md's folder layout ("needs_soc.py: reads composition")
-- and demonstrates the tri-state ``Blocked`` propagation pattern for real: if
composition is ``Unavailable``/``Blocked``, needs_soc cannot compute at all
and says so the same way (goldilocks-core-design.md:299-310).

needs_soc is advice and takes no human value (#186): its only reader is the
``magnetic.soc_suggested`` notice, and ``spin_orbit_coupling`` alone enables
spin-orbit coupling, so a human needs_soc changed no generated file. No
override reaches the LLM input either (``AnalysisOverrides`` carries none), so
the composition heuristic decides it, which keeps that notice's reason --
heavy, non-s-block elements are present -- true.
"""

from __future__ import annotations

from pymatgen.core.periodic_table import Element

from goldilocks_core.analysis.composition import CompositionFacts
from goldilocks_core.inputs.overrides import LlmInput
from goldilocks_core.resolution import (
    Blocked,
    FieldState,
    Provenance,
    Resolved,
    blocked_by,
)

_MIN_ATOMIC_NUMBER = 37
"""Rb (Z=37): the first element the old, wrong row>=5 rule flagged. Kept as
the threshold so this fix narrows false positives (s-block) without also
narrowing true positives -- nothing below Rb needed this heuristic's
attention under the old rule either."""


class NeedsSocLlmInput(LlmInput):
    needs_soc: bool | None = None


def needs_soc(
    composition: FieldState[CompositionFacts],
    llm: NeedsSocLlmInput | None = None,
) -> FieldState[bool]:
    llm = llm or NeedsSocLlmInput()
    ml_value: bool | None = None  # no ml model wired yet; stubbed until epic 11
    if ml_value is not None:
        return Resolved(ml_value, Provenance(source="ml"))
    if llm.needs_soc is not None:
        return Resolved(llm.needs_soc, Provenance(source="llm"))
    if not composition.ok:
        return Blocked(by=blocked_by(composition))
    return _heuristic(composition.value)


def _heuristic(facts: CompositionFacts) -> FieldState[bool]:
    needs_it = any(
        Element(symbol).Z >= _MIN_ATOMIC_NUMBER and Element(symbol).block != "s"
        for symbol in facts.elements
    )
    return Resolved(needs_it, Provenance(source="heuristic"))
