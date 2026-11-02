"""is_magnetic: magnetic | non_magnetic -- whether the structure has local
moments a spin-polarized calculation should seed.

Resolves ``human > ml > llm > heuristic``. The heuristic tier (#142) reads
``analysis/local_moments.py``, the package's one open-shell model: magnetic
when an element carries a local d or f moment or the structure holds an
open-shell radical, non-magnetic otherwise, and ``Unavailable`` -- never a
guessed answer -- when that model cannot decide (an oxidation state it
cannot pin down, an element without a covalent radius).
``advisors/magnetic_config.py`` then defaults the run to spin-polarized
under a warning.

It replaces a rule that counted d electrons as group minus a guessed
oxidation state for every transition metal (stfc/goldilocks-core#175's fix
for v1, which spin-polarized any transition-metal presence): elemental Ni
read as Ni0 d10, FePt and FeCo had no guess, metallic TiN and WC read as
Ti3+ d1 and W4+ d2, any lanthanide or actinide counted as magnetic (f0
ThO2), and no p-block radical ever did (solid O2).

The human and LLM overrides take the record's own values, ``magnetic`` or
``non_magnetic``, the values ``/capabilities`` advertises; a boolean is
refused (#139).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pymatgen.core import Structure

from goldilocks_core.analysis.local_moments import local_moments
from goldilocks_core.inputs.overrides import HumanInput, LlmInput
from goldilocks_core.resolution import FieldState, Provenance, Resolved

if TYPE_CHECKING:
    from goldilocks_core.ml.predict import MlPrediction

Magnetism = Literal["magnetic", "non_magnetic"]


class IsMagneticHumanInput(HumanInput):
    is_magnetic: Magnetism | None = None


class IsMagneticLlmInput(LlmInput):
    is_magnetic: Magnetism | None = None


def is_magnetic(
    structure: Structure,
    human: IsMagneticHumanInput | None = None,
    llm: IsMagneticLlmInput | None = None,
) -> FieldState[Magnetism]:
    human = human or IsMagneticHumanInput()
    llm = llm or IsMagneticLlmInput()
    if human.is_magnetic is not None:
        return Resolved(human.is_magnetic, Provenance(source="human"))
    prediction = _ml_is_magnetic(structure)
    if prediction is not None:
        return Resolved(
            "magnetic" if prediction.value else "non_magnetic", prediction.provenance
        )
    if llm.is_magnetic is not None:
        return Resolved(llm.is_magnetic, Provenance(source="llm"))
    return _heuristic(structure)


def _ml_is_magnetic(structure: Structure) -> MlPrediction | None:
    """The published mMACE-embedding MLP classifier's prediction (v2 epic 11,
    #11), whose ``provenance`` the record carries (#156), or
    ``None`` if it is not set up: its model asset is not installed or fails
    verification, ``mace``/``e3nn``/``sphericart`` are not installed (manual
    installs -- goldilocks-ml has no extra for these; see its own README's
    "Use the is_magnetic classifier"), or ``GOLDILOCKS_MACE_BACKBONE`` is not
    configured. ``is_magnetic()`` then falls back to its next tier.

    The backbone is a real requirement, not an aspiration: confirmed
    empirically (2026-09-21) against the real published record
    (1g8rw-q8128) that its own ``model.json`` declares no automatic
    download for the mMACE backbone its embedding needs --
    ``goldilocks_ml.inference.load_model`` requires it passed explicitly
    as an ``artifacts={"mace_backbone": path}`` override, which
    ``ml.predict`` supplies from the same manually-configured
    ``GOLDILOCKS_MACE_BACKBONE`` checkpoint
    ``advisors/magnetic_ordering_ml.py``'s ranking feature already uses,
    reused rather than downloaded a second time.

    The prediction runs on a worker process (``ml/mace_process.py``). A
    model that is set up but fails to load or predict raises, failing
    ``is_magnetic()`` itself: a silent heuristic answer would change the
    generated input (#130)."""
    from goldilocks_core.ml.predict import MlModelUnavailable, predict

    try:
        return predict("is_magnetic", structure)
    except MlModelUnavailable:
        return None


def _heuristic(structure: Structure) -> FieldState[Magnetism]:
    moments = local_moments(structure)
    if not moments.ok:
        return moments
    facts = moments.value
    magnetic = bool(facts.moment_elements) or facts.radical
    return Resolved(
        "magnetic" if magnetic else "non_magnetic", Provenance(source="heuristic")
    )
