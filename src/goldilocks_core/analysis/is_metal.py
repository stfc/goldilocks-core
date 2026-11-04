"""is_metal: whether the structure is metallic (zero DFT band gap).

Tiers, first resolved wins: a human override, the published CGCNN
classifier (``_ml_is_metal``), an LLM override, then the composition
heuristic (``_heuristic``).

The heuristic asserts ``metal`` only for a composition made entirely of
metallic elements by pymatgen's ``Element.is_metal`` (elements and
intermetallics; ``all_metallic``, which the phonon tasks' metallicity rule
in ``checks.py`` reads too). Any non-metal element leaves it ``Unavailable``:
whether a compound with non-metals conducts depends on its band filling, so
insulating NaCl, MgO and ZnO and metallic RuO2, ReO3, TiN, LaNiO3 and CrO2
look alike to composition (#164). This reverses stfc/goldilocks-core#175,
which stripped common anions and asked whether the remaining elements were
metals, and so called nearly every ionic insulator a metal. Generated
inputs do not change: occupations and k_sampling treat ``Unavailable``
like ``metal``.

The heuristic never guesses ``non_metal``: composition cannot rule out a
metal that looks insulator-like. An all-metal ``metal`` can still be wrong,
for intermetallic semiconductors such as CsAu or Mg2Sn.

The human and LLM overrides take the record's own values, ``metal`` or
``non_metal``, the values ``/capabilities`` advertises; a boolean is
refused (#139).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pymatgen.core import Structure
from pymatgen.core.periodic_table import Element

from goldilocks_core.inputs.overrides import HumanInput, LlmInput
from goldilocks_core.resolution import FieldState, Provenance, Resolved, Unavailable

if TYPE_CHECKING:
    from goldilocks_core.ml.predict import MlPrediction

Metallicity = Literal["metal", "non_metal"]


class IsMetalHumanInput(HumanInput):
    is_metal: Metallicity | None = None


class IsMetalLlmInput(LlmInput):
    is_metal: Metallicity | None = None


def is_metal(
    structure: Structure,
    human: IsMetalHumanInput | None = None,
    llm: IsMetalLlmInput | None = None,
) -> FieldState[Metallicity]:
    human = human or IsMetalHumanInput()
    llm = llm or IsMetalLlmInput()
    if human.is_metal is not None:
        return Resolved(human.is_metal, Provenance(source="human"))
    prediction = _ml_is_metal(structure)
    if prediction is not None:
        return Resolved(
            "metal" if prediction.value else "non_metal", prediction.provenance
        )
    if llm.is_metal is not None:
        return Resolved(llm.is_metal, Provenance(source="llm"))
    return _heuristic(structure)


def _ml_is_metal(structure: Structure) -> MlPrediction | None:
    """The published CGCNN classifier's prediction (v2 epic 11, #11), whose
    ``provenance`` the record carries (#156), or ``None`` if it is not set up
    (its model asset is not installed or fails verification), in which case
    ``is_metal()`` falls back to its next tier. A model that is set up but
    fails to load or predict raises, failing ``is_metal()`` itself: a silent
    heuristic answer would change the generated input (#130)."""
    from goldilocks_core.ml.predict import MlModelUnavailable, predict

    try:
        return predict("is_metal", structure)
    except MlModelUnavailable:
        return None


def all_metallic(structure: Structure) -> bool:
    """Whether every element of ``structure`` is metallic by pymatgen's
    ``Element.is_metal``, species split by spin read as their element: the
    compositions the heuristic calls ``metal`` (module docstring)."""
    return not _non_metals(structure)


def _non_metals(structure: Structure) -> list[str]:
    """The symbols of ``structure``'s non-metal elements, sorted."""
    elements = sorted({e.symbol for e in structure.composition.elements})
    return [symbol for symbol in elements if not Element(symbol).is_metal]


def _heuristic(structure: Structure) -> FieldState[Metallicity]:
    """``metal`` when every element is metallic, otherwise ``Unavailable``
    naming the non-metal elements."""
    if all_metallic(structure):
        return Resolved("metal", Provenance(source="heuristic"))
    listed = ", ".join(_non_metals(structure))
    return Unavailable(
        reason=f"composition contains non-metal elements ({listed}); whether "
        "such a compound conducts depends on its band filling, which "
        "composition alone cannot settle"
    )
