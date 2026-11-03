"""magnetic_ordering_ml: pick a magnetic ordering by mMACE-relaxed energy.

New (v2, #87). ``magnetic_config.py``'s ``enumerate_magnetic_orderings``
lists candidate magnetic orderings (a plain ferromagnetic guess, plus
whatever compensated antiferromagnetic candidates enumlib finds) but never
picks a winner by energy -- finding the true ground state needs comparing
total energies, which that module's own docstring assigns to "an
agent-level job" rather than its stateless heuristic tier. This module is
that job, made real: relax every candidate's magnetic moments on a frozen
mMACE potential energy surface
(``goldilocks_ml.models.magnetism.magnetic_moments.fm_fim_relax.relax``,
the same SCF-like moment relaxation a real DFT study would use total
energies from) and rank them by energy per atom.

Verified against a real published checkpoint (2026-09-19): for NiO, this
correctly ranks antiferromagnetic candidates below the ferromagnetic guess,
matching NiO's real, well-established antiferromagnetic ground state.

Needs ``mace``, ``e3nn`` and ``sphericart``, which goldilocks-ml installs
with ``mace-torch[magnetic]`` (#240), and an mMACE backbone checkpoint,
configured via ``GOLDILOCKS_MACE_BACKBONE`` (docs/mmace-setup.md). A missing
one surfaces as :class:`MagneticOrderingMlUnavailable` naming what is
missing.

mace changes process-wide state (torch's default dtype, ``os.environ``,
stdout; see ``ml/mace_process.py``), so this process never imports it: each
ranking relaxes its candidates in a fresh process, and one ranking runs at a
time, since each process holds torch and the 84 MB backbone (#130).
"""

from __future__ import annotations

import math
import os
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from goldilocks_core.worker_process import run_in_fresh_process

if TYPE_CHECKING:
    from pymatgen.core import Structure

CHECKPOINT_ENV = "GOLDILOCKS_MACE_BACKBONE"
_MACE_PACKAGES = ("mace", "e3nn", "sphericart")
_RANKING_SLOT = threading.BoundedSemaphore(1)


class MagneticOrderingMlUnavailable(Exception):
    """The mMACE-based ordering comparison could not run.

    Never a reason to fail a caller's own request: a caller comparing
    candidates by energy should catch this and fall back to reporting the
    candidates unranked, the same way ``magnetic_config.py``'s own heuristic
    tier degrades on a missing dependency rather than raising."""


@dataclass(frozen=True, slots=True)
class OrderingCandidate:
    """One candidate's relaxed energy, for reporting alongside the winner.

    ``energy_per_atom_ev`` is ``None`` when the relaxation ended at a
    non-finite energy, which ``relax()`` flags INVALID: there is no number
    to report, and strict JSON could not carry NaN or inf (#137)."""

    label: str
    structure: Structure
    energy_per_atom_ev: float | None
    status: str


@dataclass(frozen=True, slots=True)
class OrderingMlResult:
    winner: OrderingCandidate
    candidates: tuple[OrderingCandidate, ...]
    model_id: str


def checkpoint_path() -> Path:
    """Resolve the configured mMACE backbone checkpoint to an absolute path,
    or say why it is not usable.

    A relative ``GOLDILOCKS_MACE_BACKBONE`` is resolved against the current
    directory, here: the child processes that load the checkpoint start in
    the system temporary directory (``worker_process``).

    Shared by two callers: this module's own :func:`rank_orderings`, and
    ``ml.predict``'s ``is_magnetic`` classification (its published record
    declares no automatic download for this checkpoint -- see that
    module's docstring), so the same manually-configured file backs both
    rather than being fetched twice."""
    raw = os.environ.get(CHECKPOINT_ENV)
    if not raw:
        raise MagneticOrderingMlUnavailable(
            f"set {CHECKPOINT_ENV} to the mMACE backbone checkpoint path to "
            "enable mMACE-based magnetism predictions (ordering ranking or "
            "is_magnetic classification)"
        )
    path = Path(raw).expanduser().resolve()
    if not path.is_file():
        raise MagneticOrderingMlUnavailable(
            f"{CHECKPOINT_ENV} points at {path}, which does not exist"
        )
    return path


def require_mace_packages() -> None:
    """Raise :class:`MagneticOrderingMlUnavailable` naming whichever of
    mace, e3nn and sphericart is not installed.

    Shared by :func:`rank_orderings` and ``ml.predict``'s is_magnetic
    classification. Looks the top-level packages up with ``find_spec``, which
    imports none of them: only the child processes that run mMACE import
    mace."""
    missing = [name for name in _MACE_PACKAGES if find_spec(name) is None]
    if missing:
        raise MagneticOrderingMlUnavailable(
            f"{', '.join(missing)} not installed: mMACE-based magnetism "
            "predictions need mace, e3nn and sphericart, which goldilocks-ml "
            "installs with mace-torch[magnetic] (see docs/mmace-setup.md)"
        )


def _seed_moments(candidate: Structure, limits: dict[str, float]) -> np.ndarray:
    """Signed initial moments for one candidate: magnitude from the same
    oxidation-state heuristic for every candidate (so the energy comparison
    is apples to apples), sign from whatever spin decoration the candidate
    already carries -- all-positive for the plain ferromagnetic guess,
    alternating for an antiferromagnetic candidate, whose sites
    ``magnetic_config.enumerate_magnetic_orderings`` decorates with their
    spin sign."""
    from goldilocks_ml.models.magnetism.magnetic_moments.fm_fim_relax import (
        seed_moments as seed_moments_module,
    )

    magnitudes = seed_moments_module.seed_moments_fm_fim(
        candidate, max_moment_by_symbol=limits
    )
    for index, site in enumerate(candidate):
        spin = getattr(site.specie, "spin", None) or 0.0
        if spin < 0:
            magnitudes[index, 2] *= -1.0
    return magnitudes


def rank_orderings(
    candidates: Sequence[tuple[str, Structure]], *, device: str = "cpu"
) -> OrderingMlResult:
    """Relax every candidate and rank by energy per atom, lowest first.

    ``candidates`` is ``(label, structure)`` pairs, typically
    ``magnetic_config.enumerate_magnetic_orderings``'s own output. Each
    candidate's cell size may differ (a compensated antiferromagnetic
    ordering can need a larger -- or, if the input cell was redundant,
    smaller -- cell than another candidate), so candidates are compared by
    energy *per atom*, never by total energy.

    The relaxations run in a fresh process; a concurrent call waits for the
    ranking in progress.

    Raises :class:`MagneticOrderingMlUnavailable` if the checkpoint is not
    configured or mace, e3nn or sphericart is not installed, before any
    process starts -- and also if relaxing a candidate itself fails at
    runtime, which no precondition here can check up front (a library
    error inside the ranking process, such as a goldilocks-ml/mace-torch
    version mismatch). Either way, the caller sees the same
    "ranking unavailable, degrade to unranked" signal -- this is never a
    reason to fail the caller's own request, precondition or not. A ranking
    process that dies raises ``worker_process.WorkerDied``.
    """
    if not candidates:
        raise ValueError("rank_orderings needs at least one candidate")
    checkpoint = checkpoint_path()
    require_mace_packages()
    with _RANKING_SLOT:
        results = run_in_fresh_process(
            _relax_candidates, tuple(candidates), checkpoint, device
        )

    from goldilocks_ml.models.magnetism.magnetic_moments.fm_fim_relax.relax import (
        INVALID,
    )

    # A candidate relax() itself flagged INVALID has an energy that failed
    # relax.py's own physicality checks (non-finite, |E/atom| past a sane
    # bound, or a moment past the backbone's learned domain) -- confirmed
    # empirically (2026-09-21): a diverged relaxation tends to land at an
    # enormously negative energy (observed: -1.27e9 eV/atom on real Fe bcc
    # candidates), which would otherwise always "win" a plain min() over
    # physically reasonable candidates a few eV/atom apart. Never let an
    # invalid number decide the winner, even though it is still reported
    # (unfiltered) in ``candidates`` for the caller to see and discard.
    # Only INVALID candidates can have no energy (None), so every candidate
    # left has a finite one.
    reliable = [result for result in results if result.status != INVALID]
    if not reliable:
        raise MagneticOrderingMlUnavailable(
            "every candidate's mMACE relaxation was flagged invalid "
            "(non-finite or unphysical energy/moments); no reliable energy "
            "comparison is possible"
        )
    winner = min(reliable, key=lambda result: result.energy_per_atom_ev)
    return OrderingMlResult(winner=winner, candidates=results, model_id=checkpoint.name)


def _relax_candidates(
    candidates: tuple[tuple[str, Structure], ...], checkpoint: Path, device: str
) -> tuple[OrderingCandidate, ...]:
    """Ranking-process side of :func:`rank_orderings`: relax every candidate's
    moments on the backbone at ``checkpoint``, in order."""
    from goldilocks_ml.models.magnetism._mace_backbone import safe_load
    from goldilocks_ml.models.magnetism.magnetic_moments.fm_fim_relax.relax import (
        domain_limits,
        relax,
    )

    try:
        raw_model = safe_load(checkpoint, device)
        limits = domain_limits(raw_model)

        results = []
        for label, candidate in candidates:
            initial_moments = _seed_moments(candidate, limits)
            relaxed = relax(
                candidate, initial_moments, checkpoint=checkpoint, device=device
            )
            energy_per_atom = relaxed.energy_ev / len(candidate)
            results.append(
                OrderingCandidate(
                    label=label,
                    structure=candidate,
                    energy_per_atom_ev=(
                        energy_per_atom if math.isfinite(energy_per_atom) else None
                    ),
                    status=relaxed.status,
                )
            )
    except Exception as error:
        raise MagneticOrderingMlUnavailable(
            f"mMACE-based magnetic ordering ranking failed to run: {error}"
        ) from error
    return tuple(results)
