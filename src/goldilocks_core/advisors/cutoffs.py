"""cutoffs: ecutwfc/ecutrho, from the selected pseudopotentials' own
published recommendations.

New in v2 (v2 epic 7, #7). No advisor computed this before -- v1 picked
these cutoffs *inside* `generation/qe/scf.py`
(`max(p["ecutwfc_ry"] for p in selected_pseudos)`, same for `ecutrho_ry`):
a scientific choice made in the layer this rewrite requires to be pure
translation. Moved here unchanged in substance -- max across the
structure's selected pseudopotentials -- matching aiida-pseudo's own
`RecommendedCutoffMixin.get_recommended_cutoffs()`, which does exactly
this (checked against its source 2026-09-14): look up each present
element's own `cutoff_wfc`/`cutoff_rho`, take the max of each
independently. The two maxima are not required to come from the same
element or preserve any particular ratio to each other -- that is
`aiida-pseudo`'s own behaviour too, not a shortcut taken here.

**Where `ecutrho_ry` comes from when a provider publishes none.** SSSP
tables publish both `ecutwfc_ry`/`ecutrho_ry` per element. This codebase's
default provider, PseudoDojo (`advisors/pseudo_selection.py`'s
`requires_sssp`: SSSP is the exception, only for lanthanides/actinides),
publishes only wavefunction cutoff hints, so its files carry
`cutoffs["ecutrho_ry"] = None` (`importers._published_cutoffs`) and this
module is the one place the density cutoff is derived (#180): the table's
`PseudoTable.charge_density_dual` (`registry.toml`: `4.0` for every
PseudoDojo table, QE's own default for norm-conserving pseudopotentials and
aiida-pseudo's `dual_mapping` for them) times the *resolved* ecutwfc, so a
human `ecutwfc_ry` moves it too, as QE's own `ecutrho` default does. It is
taken as the max with any element's published density cutoff and reported
once per decision as `cutoffs.ecutrho_derived_from_dual`.

If a pseudopotential publishes no `ecutrho_ry` and the table has no
`charge_density_dual` to derive one from, that is a genuine gap this module
cannot safely paper over with an invented number -- it returns `Blocked`
naming the element, not a guess.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import Field

from goldilocks_core.assets.pseudopotentials.registry import PseudoTable
from goldilocks_core.assets.pseudopotentials.upf import PseudoMetadata
from goldilocks_core.inputs.overrides import HumanInput
from goldilocks_core.resolution import (
    Blocked,
    FieldState,
    Provenance,
    Resolved,
    Warning,
    blocked_by,
)

WARNING_CATALOGUE = (
    Warning(
        code="cutoffs.ecutrho_derived_from_dual",
        level="info",
        category="cutoffs",
        message=(
            "ecutrho derived as the table's charge_density_dual x the resolved "
            "ecutwfc: the selected pseudopotentials publish no density cutoff "
            "(PseudoDojo)."
        ),
    ),
)
"""Every warning code this module can emit -- ``capabilities.py``'s
``warnings[]`` catalogue aggregates one of these tuples per advisor. The
real, per-occurrence message (naming the dual, the cutoffs, the table and
the elements) is built at the call site in ``_density_cutoff`` below; this
entry is the generic description of the code, for a caller that has not
seen it fire."""


@dataclass(frozen=True, slots=True)
class CutoffsDecision:
    ecutwfc_ry: float
    ecutrho_ry: float
    warnings: tuple[Warning, ...] = ()


class CutoffsHumanInput(HumanInput):
    ecutwfc_ry: float | None = Field(default=None, gt=0)
    ecutrho_ry: float | None = Field(default=None, gt=0)


def cutoffs(
    pseudos: FieldState[tuple[PseudoMetadata, ...]],
    table: FieldState[PseudoTable] | None = None,
    human: CutoffsHumanInput | None = None,
) -> FieldState[CutoffsDecision]:
    """``ecutwfc``: the human value, else the largest the selected
    pseudopotentials publish. ``ecutrho``: the human value, else
    ``_density_cutoff`` at that ``ecutwfc``. ``source`` is ``human`` once
    either value is."""
    human = human or CutoffsHumanInput()

    if human.ecutwfc_ry is not None and human.ecutrho_ry is not None:
        decision = CutoffsDecision(human.ecutwfc_ry, human.ecutrho_ry)
        return Resolved(decision, Provenance(source="human"))

    if isinstance(pseudos, Blocked):
        return Blocked(by=pseudos)
    if not pseudos.ok:
        return Blocked(by=blocked_by(pseudos))

    published_ecutwfc = _largest_ecutwfc(pseudos.value)
    if isinstance(published_ecutwfc, Blocked):
        return published_ecutwfc
    ecutwfc_ry = published_ecutwfc if human.ecutwfc_ry is None else human.ecutwfc_ry
    decision = (
        _density_cutoff(pseudos.value, ecutwfc_ry, table)
        if human.ecutrho_ry is None
        else CutoffsDecision(ecutwfc_ry, human.ecutrho_ry)
    )
    if isinstance(decision, Blocked):
        return decision
    if human.ecutwfc_ry is None and human.ecutrho_ry is None:
        return Resolved(decision, Provenance(source="heuristic"))
    return Resolved(decision, Provenance(source="human"))


def _largest_ecutwfc(pseudos: tuple[PseudoMetadata, ...]) -> float | Blocked:
    values: list[float] = []
    for metadata in pseudos:
        wfc = metadata.cutoffs.get("ecutwfc_ry") if metadata.cutoffs else None
        if wfc is None:
            return Blocked(
                by=f"no recommended ecutwfc for pseudopotential {metadata.element!r}"
            )
        values.append(wfc)
    return max(values)


def _density_cutoff(
    pseudos: tuple[PseudoMetadata, ...],
    ecutwfc_ry: float,
    table: FieldState[PseudoTable] | None,
) -> CutoffsDecision | Blocked:
    """The decision at ``ecutwfc_ry`` with the largest published ``ecutrho``.
    Pseudopotentials that publish none take the table's
    ``charge_density_dual`` x ``ecutwfc_ry``, reported in one
    ``cutoffs.ecutrho_derived_from_dual`` notice naming them."""
    published: list[float] = []
    unpublished: list[str] = []
    for metadata in pseudos:
        rho = metadata.cutoffs.get("ecutrho_ry") if metadata.cutoffs else None
        if rho is None:
            unpublished.append(str(metadata.element))
        else:
            published.append(rho)
    if not unpublished:
        return CutoffsDecision(ecutwfc_ry, max(published))

    selected = table.value if table is not None and table.ok else None
    if selected is None or selected.charge_density_dual is None:
        return Blocked(
            by=f"no recommended ecutrho for {unpublished[0]!r} and no "
            "charge_density_dual to derive one from"
        )
    dual = selected.charge_density_dual
    derived = dual * ecutwfc_ry
    notice = Warning(
        code="cutoffs.ecutrho_derived_from_dual",
        level="info",
        category="cutoffs",
        message=(
            "ecutrho derived as charge_density_dual x ecutwfc = "
            f"{dual:g} x {ecutwfc_ry:g} = {derived:g} Ry: table {selected.id} "
            f"publishes no density cutoff for {', '.join(sorted(unpublished))}"
        ),
    )
    return CutoffsDecision(ecutwfc_ry, max([*published, derived]), (notice,))
