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
with ``mace-torch[magnetic]`` (#240), and the mMACE backbone checkpoint,
installed with the is_magnetic classifier asset (#244) or named by
``GOLDILOCKS_MACE_BACKBONE``. A missing one surfaces as
:class:`MagneticOrderingMlUnavailable` naming what is missing.

mace changes process-wide state (torch's default dtype, ``os.environ``,
stdout; see ``ml/mace_process.py``), so this process never imports it: each
ranking relaxes its candidates, one call each, on a child process of its own,
and one ranking runs at a time, since each process holds torch and the 84 MB
backbone (#130). The call per candidate lets a caller follow the ranking's
progress and kill its process (#261).

mMACE's memory grows with the number of atoms, so neither mMACE use runs on
a structure above :func:`max_atoms` (#259).
"""

from __future__ import annotations

import math
import os
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import cache
from importlib.util import find_spec
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from goldilocks_core.assets.store import AssetCorrupt, AssetNotInstalled, AssetStore
from goldilocks_core.ml.models import load_ml_classifier
from goldilocks_core.worker_process import WorkerProcess

if TYPE_CHECKING:
    from pymatgen.core import Structure

CHECKPOINT_ENV = "GOLDILOCKS_MACE_BACKBONE"
MAX_ATOMS_ENV = "GOLDILOCKS_MMACE_MAX_ATOMS"
DEFAULT_MAX_ATOMS = 200
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
    """The mMACE backbone checkpoint as an absolute path: the file
    ``GOLDILOCKS_MACE_BACKBONE`` names, else the one installed with the
    is_magnetic classifier asset (#244); or say why neither is usable.

    A relative ``GOLDILOCKS_MACE_BACKBONE`` is resolved against the current
    directory, here: the child processes that load the checkpoint start in
    the system temporary directory (``worker_process``).

    Shared by two callers: this module's own :func:`rank_orderings`, and
    ``ml.predict``'s ``is_magnetic`` classification, so one file backs
    both."""
    raw = os.environ.get(CHECKPOINT_ENV)
    if not raw:
        return _installed_checkpoint()
    path = Path(raw).expanduser().resolve()
    if not path.is_file():
        raise MagneticOrderingMlUnavailable(
            f"{CHECKPOINT_ENV} points at {path}, which does not exist"
        )
    return path


def _installed_checkpoint() -> Path:
    """The backbone file of the installed is_magnetic classifier asset."""
    asset = load_ml_classifier("is_magnetic").asset
    backbone = next(file.path for file in asset.files if file.role == "backbone")
    try:
        root = AssetStore().resolve_spec(asset).root
    except (AssetNotInstalled, AssetCorrupt) as error:
        raise MagneticOrderingMlUnavailable(
            f"no mMACE backbone checkpoint: run 'goldilocks assets install "
            f"{asset.id}' (part of the default assets), or set {CHECKPOINT_ENV} "
            "to a checkpoint"
        ) from error
    return root / backbone


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


def max_atoms() -> int:
    """The most atoms this server runs an mMACE model on:
    ``GOLDILOCKS_MMACE_MAX_ATOMS`` if set, else 200.

    Shared by :func:`rank_orderings` and ``ml.predict``'s is_magnetic
    classification. Their memory grows with the atom count: the is_magnetic
    embedding peaked at 3.5, 6.4 and 11.8 GB for 54, 128 and 250 atoms, and a
    ranking at 2.3 GB for a 16-atom bcc Fe supercell (core 0.3.0, macOS,
    2026-11-09). On Linux with goldilocks-ml 0.3.3, the is_magnetic worker
    peaked at 6.3 GB at this default, from a 0.7 GB baseline (#259).

    Raises ``ValueError`` for a value that is not a positive whole number."""
    raw = os.environ.get(MAX_ATOMS_ENV)
    if not raw:
        return DEFAULT_MAX_ATOMS
    text = raw.strip()
    if not text.isdecimal() or int(text) == 0:
        raise ValueError(f"{MAX_ATOMS_ENV}={raw!r} is not a positive whole number")
    return int(text)


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
    candidates: Sequence[tuple[str, Structure]],
    *,
    device: str = "cpu",
    worker: WorkerProcess | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> OrderingMlResult:
    """Relax every candidate and rank by energy per atom, lowest first.

    ``candidates`` is ``(label, structure)`` pairs, typically
    ``magnetic_config.enumerate_magnetic_orderings``'s own output. Each
    candidate's cell size may differ (a compensated antiferromagnetic
    ordering can need a larger -- or, if the input cell was redundant,
    smaller -- cell than another candidate), so candidates are compared by
    energy *per atom*, never by total energy.

    The candidates are relaxed one call each on ``worker``, else on a child
    process started for this ranking and ended after it; a concurrent call
    waits for the ranking in progress. ``on_progress(done, total)`` is called
    before the first relaxation and after each, with the number of candidates
    relaxed so far.

    Raises :class:`MagneticOrderingMlUnavailable` if the checkpoint is not
    configured, mace, e3nn or sphericart is not installed, or a candidate
    has more atoms than :func:`max_atoms`, before any process starts -- and
    also if relaxing a candidate itself fails at
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
    limit = max_atoms()
    label, largest = max(candidates, key=lambda candidate: len(candidate[1]))
    if len(largest) > limit:
        raise MagneticOrderingMlUnavailable(
            f"mMACE ranking was not run: candidate {label} has {len(largest)} "
            f"atoms, above this server's {limit}-atom limit for mMACE "
            f"({MAX_ATOMS_ENV})"
        )
    with _RANKING_SLOT:
        results = _relax_all(candidates, checkpoint, device, worker, on_progress)

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


def _relax_all(
    candidates: Sequence[tuple[str, Structure]],
    checkpoint: Path,
    device: str,
    worker: WorkerProcess | None,
    on_progress: Callable[[int, int], None] | None,
) -> tuple[OrderingCandidate, ...]:
    """Every candidate's relaxation, one call each on ``worker`` (or on a
    worker of its own, ended afterwards), in order."""
    process = worker or WorkerProcess()
    report = on_progress or (lambda done, total: None)
    results: list[OrderingCandidate] = []
    try:
        report(0, len(candidates))
        for label, candidate in candidates:
            results.append(
                process.run(_relax_candidate, label, candidate, checkpoint, device)
            )
            report(len(results), len(candidates))
    finally:
        if worker is None:
            process.close()
    return tuple(results)


def _relax_candidate(
    label: str, candidate: Structure, checkpoint: Path, device: str
) -> OrderingCandidate:
    """Ranking-process side of :func:`rank_orderings`: relax one candidate's
    moments on the backbone at ``checkpoint``."""
    from goldilocks_ml.models.magnetism.magnetic_moments.fm_fim_relax.relax import (
        relax,
    )

    try:
        initial_moments = _seed_moments(candidate, _domain_limits(checkpoint, device))
        relaxed = relax(
            candidate, initial_moments, checkpoint=checkpoint, device=device
        )
    except Exception as error:
        raise MagneticOrderingMlUnavailable(
            f"mMACE-based magnetic ordering ranking failed to run: {error}"
        ) from error
    energy_per_atom = relaxed.energy_ev / len(candidate)
    return OrderingCandidate(
        label=label,
        structure=candidate,
        energy_per_atom_ev=energy_per_atom if math.isfinite(energy_per_atom) else None,
        status=relaxed.status,
    )


@cache
def _domain_limits(checkpoint: Path, device: str) -> dict[str, float]:
    """The backbone's moment limits per element, loaded once per ranking
    process."""
    from goldilocks_ml.models.magnetism._mace_backbone import safe_load
    from goldilocks_ml.models.magnetism.magnetic_moments.fm_fim_relax.relax import (
        domain_limits,
    )

    return domain_limits(safe_load(checkpoint, device))
