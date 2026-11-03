"""rank_orderings: mMACE-relaxed energies pick a magnetic ordering (#87).

Each ranking relaxes its candidates in a fresh process, one ranking at a
time, so mace's process-wide torch settings never reach the caller (#130).
Tests that stub goldilocks-ml's relaxation run that process's function
inline, in this process, where the stubs are visible.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import threading
import time
from importlib.machinery import ModuleSpec

import numpy as np
import pytest
from pymatgen.core import Lattice, Species, Structure

from goldilocks_core.advisors import magnetic_ordering_ml
from goldilocks_core.advisors.magnetic_ordering_ml import (
    CHECKPOINT_ENV,
    MagneticOrderingMlUnavailable,
    checkpoint_path,
    rank_orderings,
)
from goldilocks_core.service import (
    _magnetic_orderings as magnetic_orderings_module,
    list_magnetic_orderings,
    report_to_json,
)
from goldilocks_core.worker_process import WorkerDied

_IRON = Structure(Lattice.cubic(2.87), ["Fe"], [[0.0, 0.0, 0.0]])
_IRON_PAIR = Structure(
    Lattice.cubic(2.87), ["Fe", "Fe"], [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]]
)
_BCC_IRON = Structure.from_spacegroup(
    "Im-3m", Lattice.cubic(2.87), ["Fe"], [[0.0, 0.0, 0.0]]
)
# bcc Fe's simplest compensated antiferromagnetic candidate (corner and
# body-centre spins opposed), spin-decorated the way
# magnetic_config.enumerate_magnetic_orderings lists an enumerated candidate.
_BCC_IRON_AFM = Structure(
    Lattice.cubic(2.87),
    [Species("Fe", spin=1), Species("Fe", spin=-1)],
    [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
    labels=["Fe1", "Fe2"],
)


def test_checkpoint_path_requires_the_environment_variable(monkeypatch) -> None:
    monkeypatch.delenv(CHECKPOINT_ENV, raising=False)

    with pytest.raises(MagneticOrderingMlUnavailable, match=CHECKPOINT_ENV):
        checkpoint_path()


def test_checkpoint_path_rejects_a_missing_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(CHECKPOINT_ENV, str(tmp_path / "missing.model"))

    with pytest.raises(MagneticOrderingMlUnavailable, match="does not exist"):
        checkpoint_path()


def test_checkpoint_path_accepts_a_real_file(monkeypatch, tmp_path) -> None:
    checkpoint = tmp_path / "backbone.model"
    checkpoint.write_bytes(b"stub")
    monkeypatch.setenv(CHECKPOINT_ENV, str(checkpoint))

    assert checkpoint_path() == checkpoint


def test_checkpoint_path_resolves_a_relative_path_against_the_cwd(
    monkeypatch, tmp_path
) -> None:
    """The child processes that load the checkpoint start in the system
    temporary directory, where a relative path names nothing (#130)."""
    (tmp_path / "backbone.model").write_bytes(b"stub")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(CHECKPOINT_ENV, "backbone.model")

    assert checkpoint_path() == tmp_path / "backbone.model"


def test_rank_orderings_needs_at_least_one_candidate(monkeypatch, tmp_path) -> None:
    checkpoint = tmp_path / "backbone.model"
    checkpoint.write_bytes(b"stub")
    monkeypatch.setenv(CHECKPOINT_ENV, str(checkpoint))

    with pytest.raises(ValueError, match="at least one candidate"):
        rank_orderings([])


def test_rank_orderings_checks_the_checkpoint_before_anything_else(monkeypatch) -> None:
    """The checkpoint is resolved before any candidate is touched, per the
    docstring's "always before relaxing any candidate, never partway
    through the list" promise -- this failure must not depend on whether
    goldilocks-ml happens to be installed."""
    monkeypatch.delenv(CHECKPOINT_ENV, raising=False)

    with pytest.raises(MagneticOrderingMlUnavailable, match=CHECKPOINT_ENV):
        rank_orderings([("fm", _IRON)])


def _report_mace_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """``find_spec`` finds mace, e3nn and sphericart (CI installs none)."""
    monkeypatch.setattr(
        magnetic_ordering_ml, "find_spec", lambda name: ModuleSpec(name, None)
    )


def _stub_relax_seam(
    monkeypatch: pytest.MonkeyPatch, fake_relax
) -> list[tuple[object, ...]]:
    """Replace goldilocks-ml's own relax/domain_limits/safe_load, so
    rank_orderings()'s winner-selection logic can be exercised without the
    real mace/e3nn/sphericart stack -- these modules import fine without it
    (only calling into them needs it, see their own docstrings), so
    monkeypatching the real functions directly, not injecting fake modules,
    is enough here.

    The ranking's fresh process runs inline, so the stubs apply; returns the
    arguments of every process the ranking started."""
    started: list[tuple[object, ...]] = []

    def run_inline(fn, *args):
        started.append(args)
        return fn(*args)

    _report_mace_installed(monkeypatch)
    monkeypatch.setattr(magnetic_ordering_ml, "run_in_fresh_process", run_inline)
    monkeypatch.setattr(
        "goldilocks_ml.models.magnetism._mace_backbone.safe_load",
        lambda checkpoint, device: object(),
    )
    monkeypatch.setattr(
        "goldilocks_ml.models.magnetism.magnetic_moments.fm_fim_relax."
        "relax.domain_limits",
        lambda raw_model: {},
    )
    monkeypatch.setattr(
        "goldilocks_ml.models.magnetism.magnetic_moments.fm_fim_relax.relax.relax",
        fake_relax,
    )
    return started


def test_rank_orderings_never_recommends_a_candidate_relax_flagged_invalid(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Confirmed empirically (2026-09-21) against real Fe bcc candidates: a
    diverged relaxation relax() itself flags INVALID can land at an
    enormously negative energy (observed: -1.27e9 eV/atom) that would win a
    naive ``min()`` over every physically reasonable candidate. An invalid
    result must never become the winner, even though it is still reported
    in ``candidates`` for a caller to see."""
    from goldilocks_ml.models.magnetism.magnetic_moments.fm_fim_relax.relax import (
        INVALID,
        OK,
        MomentRelaxationResult,
    )

    checkpoint = tmp_path / "backbone.model"
    checkpoint.write_bytes(b"stub")
    monkeypatch.setenv(CHECKPOINT_ENV, str(checkpoint))

    def fake_relax(structure, initial_moments, *, checkpoint, device):
        if len(structure) == 1:
            return MomentRelaxationResult(
                moments=np.zeros((1, 3)), energy_ev=-1_000_000_000.0, status=INVALID
            )
        return MomentRelaxationResult(
            moments=np.zeros((len(structure), 3)),
            energy_ev=-48.0,
            status=OK,
        )

    _stub_relax_seam(monkeypatch, fake_relax)

    result = rank_orderings([("fm", _IRON), ("afm-1", _IRON_PAIR)])

    assert result.winner.label == "afm-1"
    assert result.winner.status == OK
    assert {candidate.label for candidate in result.candidates} == {"fm", "afm-1"}


def test_rank_orderings_degrades_when_every_candidate_is_invalid(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from goldilocks_ml.models.magnetism.magnetic_moments.fm_fim_relax.relax import (
        INVALID,
        MomentRelaxationResult,
    )

    checkpoint = tmp_path / "backbone.model"
    checkpoint.write_bytes(b"stub")
    monkeypatch.setenv(CHECKPOINT_ENV, str(checkpoint))

    def fake_relax(structure, initial_moments, *, checkpoint, device):
        return MomentRelaxationResult(
            moments=np.zeros((len(structure), 3)),
            energy_ev=-1_000_000_000.0,
            status=INVALID,
        )

    _stub_relax_seam(monkeypatch, fake_relax)

    with pytest.raises(MagneticOrderingMlUnavailable, match="invalid"):
        rank_orderings([("fm", _IRON)])


def _stub_a_non_finite_ferromagnetic_relaxation(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """relax() returns the ferromagnetic candidate's NaN energy flagged
    INVALID, as goldilocks-ml does for a non-finite energy, and relaxes the
    spin-decorated antiferromagnetic candidate to -16.5 eV (-8.25 eV/atom)."""
    from goldilocks_ml.models.magnetism.magnetic_moments.fm_fim_relax.relax import (
        INVALID,
        OK,
        MomentRelaxationResult,
    )

    checkpoint = tmp_path / "backbone.model"
    checkpoint.write_bytes(b"stub")
    monkeypatch.setenv(CHECKPOINT_ENV, str(checkpoint))

    def fake_relax(structure, initial_moments, *, checkpoint, device):
        moments = np.zeros((len(structure), 3))
        if any(getattr(site.specie, "spin", None) for site in structure):
            return MomentRelaxationResult(moments=moments, energy_ev=-16.5, status=OK)
        return MomentRelaxationResult(
            moments=moments, energy_ev=math.nan, status=INVALID
        )

    _stub_relax_seam(monkeypatch, fake_relax)


def test_rank_orderings_reports_no_energy_for_a_non_finite_relaxation(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A non-finite relaxed energy is reported as None, not NaN, which
    strict JSON cannot carry (#137); the candidate stays listed as INVALID
    and the valid candidate wins."""
    _stub_a_non_finite_ferromagnetic_relaxation(monkeypatch, tmp_path)

    result = rank_orderings([("fm", _BCC_IRON), ("afm-1", _BCC_IRON_AFM)])

    by_label = {candidate.label: candidate for candidate in result.candidates}
    assert by_label["fm"].energy_per_atom_ev is None
    assert by_label["fm"].status == "invalid"
    assert result.winner.label == "afm-1"
    assert result.winner.energy_per_atom_ev == -8.25


def test_a_ranked_listing_with_a_non_finite_energy_is_strict_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """``magnetic-orderings --rank-with-mmace --json`` and
    ``/magnetic-orderings`` serialise this document strictly: an INVALID
    candidate's missing energy is null (#137)."""
    _stub_a_non_finite_ferromagnetic_relaxation(monkeypatch, tmp_path)
    monkeypatch.setattr(
        magnetic_orderings_module,
        "enumerate_magnetic_orderings",
        lambda structure, moments: (
            (("fm", structure), ("afm-1", _BCC_IRON_AFM)),
            None,
        ),
    )

    report = list_magnetic_orderings(_BCC_IRON, rank_with_mmace=True)
    document = json.loads(json.dumps(report_to_json(report), allow_nan=False))

    assert document["ranked"] is True
    assert [
        (candidate["label"], candidate["energy_per_atom_ev"], candidate["status"])
        for candidate in document["candidates"]
    ] == [("fm", None, "invalid"), ("afm-1", -8.25, "ok")]
    assert [
        candidate["label"]
        for candidate in document["candidates"]
        if candidate["is_recommended"]
    ] == ["afm-1"]


def _ok_relaxation(structure, initial_moments, *, checkpoint, device):
    from goldilocks_ml.models.magnetism.magnetic_moments.fm_fim_relax.relax import (
        OK,
        MomentRelaxationResult,
    )

    return MomentRelaxationResult(
        moments=np.zeros((len(structure), 3)), energy_ev=-8.0, status=OK
    )


def _configure_checkpoint(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    checkpoint = tmp_path / "backbone.model"
    checkpoint.write_bytes(b"stub")
    monkeypatch.setenv(CHECKPOINT_ENV, str(checkpoint))


@pytest.mark.parametrize("missing", ["mace", "e3nn", "sphericart"])
def test_rank_orderings_needs_the_mace_packages_before_starting_a_process(
    missing: str, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _configure_checkpoint(monkeypatch, tmp_path)
    monkeypatch.setattr(
        magnetic_ordering_ml,
        "find_spec",
        lambda name: None if name == missing else ModuleSpec(name, None),
    )

    def no_process(fn, *args):
        raise AssertionError("no ranking process may start without mace")

    monkeypatch.setattr(magnetic_ordering_ml, "run_in_fresh_process", no_process)

    with pytest.raises(
        MagneticOrderingMlUnavailable, match=f"^{missing} not installed"
    ):
        rank_orderings([("fm", _BCC_IRON)])


def test_rank_orderings_relaxes_every_candidate_in_one_fresh_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _configure_checkpoint(monkeypatch, tmp_path)
    started = _stub_relax_seam(monkeypatch, _ok_relaxation)
    candidates = [("fm", _BCC_IRON), ("afm-1", _BCC_IRON_AFM)]

    rank_orderings(candidates, device="cpu")

    assert started == [(tuple(candidates), tmp_path / "backbone.model", "cpu")]


def test_a_relaxation_that_fails_degrades_the_ranking(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A library failure inside the ranking process, such as a mace fork
    that lacks a keyword goldilocks-ml passes, still degrades to an unranked
    listing."""
    _configure_checkpoint(monkeypatch, tmp_path)

    def failing_relax(structure, initial_moments, *, checkpoint, device):
        raise TypeError("unexpected keyword argument 'use_collinear'")

    _stub_relax_seam(monkeypatch, failing_relax)

    with pytest.raises(MagneticOrderingMlUnavailable, match="use_collinear"):
        rank_orderings([("fm", _BCC_IRON)])


def test_a_ranking_process_that_dies_fails_the_listing(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A killed ranking process is not a missing feature: the request fails
    instead of silently listing the candidates unranked."""
    _configure_checkpoint(monkeypatch, tmp_path)
    _report_mace_installed(monkeypatch)

    def killed(fn, *args):
        raise WorkerDied("worker process exited with code -9")

    monkeypatch.setattr(magnetic_ordering_ml, "run_in_fresh_process", killed)
    monkeypatch.setattr(
        magnetic_orderings_module,
        "enumerate_magnetic_orderings",
        lambda structure, moments: (
            (("fm", structure), ("afm-1", _BCC_IRON_AFM)),
            None,
        ),
    )

    with pytest.raises(WorkerDied):
        list_magnetic_orderings(_BCC_IRON, rank_with_mmace=True)


def test_rankings_run_one_at_a_time(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Each ranking process holds torch and the 84 MB backbone, so concurrent
    requests queue for one ranking slot rather than multiplying them."""
    _configure_checkpoint(monkeypatch, tmp_path)
    _report_mace_installed(monkeypatch)
    lock = threading.Lock()
    running = 0
    most_at_once = []

    def slow_process(fn, *args):
        nonlocal running
        with lock:
            running += 1
            most_at_once.append(running)
        time.sleep(0.2)
        with lock:
            running -= 1
        return (
            magnetic_ordering_ml.OrderingCandidate(
                label="fm", structure=_BCC_IRON, energy_per_atom_ev=-8.0, status="ok"
            ),
        )

    monkeypatch.setattr(magnetic_ordering_ml, "run_in_fresh_process", slow_process)
    rankings = [
        threading.Thread(target=rank_orderings, args=([("fm", _BCC_IRON)],))
        for _ in range(3)
    ]
    for ranking in rankings:
        ranking.start()
    for ranking in rankings:
        ranking.join()

    assert most_at_once == [1, 1, 1]


@pytest.mark.skipif(
    not os.environ.get("GOLDILOCKS_MACE_BACKBONE")
    or importlib.util.find_spec("goldilocks_ml") is None
    or importlib.util.find_spec("mace") is None,
    reason=(
        "needs a real mMACE backbone checkpoint (GOLDILOCKS_MACE_BACKBONE) and "
        "goldilocks-ml with mace-torch"
    ),
)
def test_rank_orderings_ranks_antiferromagnetic_nio_below_ferromagnetic() -> None:
    """A coarse sanity check against the real backbone, when it is present.

    Never runs in CI, which has no backbone checkpoint (84 MB). Verified
    manually (2026-09-19 on the mace-torch fork; 2026-11-03 on mace-torch
    0.3.17 with the v2.0 backbone of PSDI record sgk1t-48m42, #240): NiO's
    antiferromagnetic candidates rank below its ferromagnetic guess,
    matching NiO's real, well-established antiferromagnetic ground state.
    """
    nio_fm = Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(4.17), ["Ni", "O"], [[0, 0, 0], [0.5, 0.5, 0.5]]
    )
    # A hand-built compensated AFM candidate: alternating +/-z spin on the
    # rocksalt Ni sublattice, oxygen unsigned -- the same shape
    # ``magnetic_config.enumerate_magnetic_orderings`` lists for a real
    # enumerator candidate, built here directly since this test does not
    # need enumlib.
    ni_up, ni_down = Species("Ni", spin=1), Species("Ni", spin=-1)
    nio_afm = Structure(
        nio_fm.lattice,
        [
            ni_up if site.specie.symbol == "Ni" and index % 2 == 0 else site.specie
            for index, site in enumerate(nio_fm)
        ],
        nio_fm.frac_coords,
    )
    for index, site in enumerate(nio_fm):
        if site.specie.symbol == "Ni" and index % 2 == 1:
            nio_afm.replace(index, ni_down)

    result = rank_orderings([("fm", nio_fm), ("afm-1", nio_afm)])

    assert result.winner.label == "afm-1"
    assert result.winner.energy_per_atom_ev < next(
        c.energy_per_atom_ev for c in result.candidates if c.label == "fm"
    )
