"""list_magnetic_orderings: enumerate, and optionally mMACE-rank, magnetic
orderings for one structure (v2, #87).

Deliberately not part of ``advise()``/``generate()``: those decide one
simulated cell per calculation (``MagneticCell``), but this is a
listing capability a caller consults *before* deciding which ordering(s)
to actually generate input files for -- "give me FM and AFM input files"
and "let mMACE recommend one" both start here. Each listed candidate
names itself: its ``overrides`` (``{"magnetic_ordering": label}``) sent
with the *listed* structure to ``/run`` generate exactly that candidate,
through the same magnetic step as ``magnetic_ordering=afm``, so its seeds
and symmetry cannot differ from that path's (#170). A candidate used to
carry its own CIF with seeds remapped onto the CIF's labels: seeded at the
flat 0.1 and counted for symmetry on the spin-less CIF. See issue #87 for
the full three-layer design (enumerate -> optionally rank -> generate)
this is the first layer of.

Enumeration never needs mMACE (it is
``advisors/magnetic_config.enumerate_magnetic_orderings``, the same
enumlib-backed path the existing heuristic tier already uses, run on a
worker process in a private directory, #136, over the sites
``analysis/local_moments.py`` says carry a local moment, #143, keeping only
the orderings that keep a slab's, wire's or boxed molecule's vacuum
vectors, #144) and returns
at least the plain ferromagnetic candidate, with a warning naming why when
a structure with local moments gets no antiferromagnetic one; an
enumeration fault (a scratch-directory
``OSError``, a dead worker) propagates instead of looking like a
ferromagnetic-only answer. Ranking is opt-in and can fail independently
(no backbone checkpoint, mace/e3nn/sphericart not installed, a library
error inside the ranking process, or every candidate's relaxation flagged
invalid) without failing the listing itself -- a caller who asked for
ranking still gets every candidate back, just unranked, with a warning
naming why. A ranking process that dies (``worker_process.WorkerDied``,
#130) propagates.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pymatgen.core import Structure

from goldilocks_core.advisors.magnetic_config import enumerate_magnetic_orderings
from goldilocks_core.advisors.magnetic_ordering_ml import (
    MagneticOrderingMlUnavailable,
    rank_orderings,
)
from goldilocks_core.analysis.local_moments import LocalMomentFacts, local_moments
from goldilocks_core.inputs.structure import require_ordered
from goldilocks_core.resolution import FieldState, Warning

if TYPE_CHECKING:
    from goldilocks_core.worker_process import WorkerProcess


@dataclass(frozen=True, slots=True)
class MagneticOrderingCandidate:
    """One listed candidate, ranked or not: ``structure`` is the listed
    structure for ``fm``, otherwise the cell ``magnetic_ordering=<label>``
    writes for it (``enumerate_magnetic_orderings``)."""

    label: str
    structure: Structure
    natoms: int
    energy_per_atom_ev: float | None
    status: str | None
    is_recommended: bool

    @property
    def overrides(self) -> dict[str, str]:
        """The setting that generates this candidate from the listed
        structure (#170)."""
        return {"magnetic_ordering": self.label}


@dataclass(frozen=True, slots=True)
class MagneticOrderingsReport:
    candidates: tuple[MagneticOrderingCandidate, ...]
    ranked: bool
    warnings: tuple[Warning, ...] = ()


def candidate_to_json(candidate: MagneticOrderingCandidate) -> dict[str, Any]:
    """The JSON-safe projection of one candidate -- shared by
    ``cli/_magnetic_orderings.py`` and ``server/_handlers.py`` so both
    transports report the same shape.

    ``overrides`` is what a caller adds to its own settings to generate
    DFT input files for *this exact* candidate: run the structure it
    listed with them (``/run``, ``goldilocks run --set
    magnetic_ordering=afm-3``). The run enumerates again and applies the
    candidate of that label, numbered in the same canonical order (#170),
    and records the applied label next to the cell's formula and atom
    count in ``records.magnetic``."""
    return {
        "label": candidate.label,
        "formula": candidate.structure.composition.reduced_formula,
        "natoms": candidate.natoms,
        "energy_per_atom_ev": candidate.energy_per_atom_ev,
        "status": candidate.status,
        "is_recommended": candidate.is_recommended,
        "overrides": candidate.overrides,
    }


def report_to_json(report: MagneticOrderingsReport) -> dict[str, Any]:
    return {
        "ranked": report.ranked,
        "candidates": [candidate_to_json(candidate) for candidate in report.candidates],
        "warnings": [warning.model_dump() for warning in report.warnings],
    }


def _unranked(
    candidates: tuple[tuple[str, Structure], ...],
) -> tuple[MagneticOrderingCandidate, ...]:
    return tuple(
        MagneticOrderingCandidate(
            label=label,
            structure=candidate,
            natoms=len(candidate),
            energy_per_atom_ev=None,
            status=None,
            is_recommended=False,
        )
        for label, candidate in candidates
    )


def _has_moments_to_order(moments: FieldState[LocalMomentFacts]) -> bool:
    """Whether a ferromagnetic-only listing needs explaining: the local
    moments are undecidable, or an element carries one, or a radical
    does."""
    if not moments.ok:
        return True
    return bool(moments.value.moment_elements) or moments.value.radical


def list_magnetic_orderings(
    structure: Structure,
    *,
    rank_with_mmace: bool = False,
    device: str = "cpu",
    worker: WorkerProcess | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> MagneticOrderingsReport:
    """List every magnetic-ordering candidate for ``structure``.

    ``rank_with_mmace=True`` additionally relaxes every candidate's moments
    on the mMACE potential energy surface and marks the lowest
    energy-per-atom candidate as ``is_recommended``. If the ``magnetism``
    extra or its checkpoint is not configured, the candidates are still
    returned (unranked), with a warning naming why -- ranking is an
    enhancement to this listing, never a precondition for it. ``worker`` and
    ``on_progress`` go to ``rank_orderings``: the process the candidates are
    relaxed on, and the ranking's progress.

    Also warns (rather than silently listing "fm" alone, indistinguishable
    from "this structure genuinely has no AFM candidates") whenever
    ``structure`` has local moments but no AFM candidate came back: AFM
    enumeration could not run or find one (the common real case being
    enumlib not installed), no site carries a local d or f moment to order
    (a radical such as solid O2, #143), or which sites carry one could not
    be determined. A closed-shell structure (Si) lists "fm" alone silently.
    Raises ``StructureInputError`` for a disordered ``structure``
    (``inputs.structure.require_ordered``).
    """
    require_ordered(structure)
    moments = local_moments(structure)
    candidates, afm_warning = enumerate_magnetic_orderings(structure, moments)
    warnings = (
        (afm_warning,)
        if afm_warning is not None and _has_moments_to_order(moments)
        else ()
    )

    if not rank_with_mmace:
        return MagneticOrderingsReport(
            candidates=_unranked(candidates), ranked=False, warnings=warnings
        )

    try:
        ranked = rank_orderings(
            candidates, device=device, worker=worker, on_progress=on_progress
        )
    except MagneticOrderingMlUnavailable as error:
        return MagneticOrderingsReport(
            candidates=_unranked(candidates),
            ranked=False,
            warnings=(
                *warnings,
                Warning(
                    code="magnetic.ordering_ranking_unavailable",
                    level="warning",
                    category="magnetic",
                    message=str(error),
                ),
            ),
        )

    by_label = {result.label: result for result in ranked.candidates}
    candidates_out = tuple(
        MagneticOrderingCandidate(
            label=label,
            structure=candidate,
            natoms=len(candidate),
            energy_per_atom_ev=by_label[label].energy_per_atom_ev,
            status=by_label[label].status,
            is_recommended=label == ranked.winner.label,
        )
        for label, candidate in candidates
    )
    return MagneticOrderingsReport(
        candidates=candidates_out, ranked=True, warnings=warnings
    )
