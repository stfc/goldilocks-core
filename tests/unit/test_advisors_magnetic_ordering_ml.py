"""rank_orderings: mMACE-relaxed energies pick a magnetic ordering (#87).

Each ranking relaxes its candidates, one call each, on a child process of
its own, one ranking at a time, so mace's process-wide torch settings never
reach the caller (#130, #261). Tests that stub goldilocks-ml's relaxation
replace that process with an inline worker, which runs each call in this
process, where the stubs are visible.
"""

from __future__ import annotations

import importlib.util
import json
import math
import re
import shutil
import threading
import time
from importlib.machinery import ModuleSpec
from types import SimpleNamespace

import numpy as np
import pytest
from pymatgen.core import Lattice, Species, Structure

from goldilocks_core.advisors import magnetic_ordering_ml
from goldilocks_core.advisors.magnetic_ordering_ml import (
    CHECKPOINT_ENV,
    DEVICE_ENV,
    MAX_ATOMS_ENV,
    MagneticOrderingMlUnavailable,
    checkpoint_path,
    max_atoms,
    mmace_device,
    rank_orderings,
    warm_ranking_worker,
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


def test_checkpoint_path_needs_the_variable_or_the_installed_asset(
    monkeypatch,
) -> None:
    """Neither set nor installed: the message names both remedies."""
    monkeypatch.delenv(CHECKPOINT_ENV, raising=False)

    with pytest.raises(MagneticOrderingMlUnavailable) as raised:
        checkpoint_path()

    install = "goldilocks assets install models/is-magnetic-classifier"
    assert install in str(raised.value)
    assert CHECKPOINT_ENV in str(raised.value)


def _install_is_magnetic_asset(monkeypatch, root) -> None:
    """is_magnetic's asset resolves to ``root``, as if installed and
    verified (CI installs no assets)."""
    installed = SimpleNamespace(resolve_spec=lambda spec: SimpleNamespace(root=root))
    monkeypatch.setattr(magnetic_ordering_ml, "AssetStore", lambda: installed)


def test_checkpoint_path_uses_the_backbone_installed_with_the_asset(
    monkeypatch, tmp_path
) -> None:
    """#244: the registry installs the backbone with is_magnetic's asset."""
    monkeypatch.delenv(CHECKPOINT_ENV, raising=False)
    _install_is_magnetic_asset(monkeypatch, tmp_path)

    assert checkpoint_path() == tmp_path / "mmace-matpes-pbe-pretrained.model"


def test_the_variable_overrides_the_installed_backbone(monkeypatch, tmp_path) -> None:
    checkpoint = tmp_path / "other.model"
    checkpoint.write_bytes(b"stub")
    monkeypatch.setenv(CHECKPOINT_ENV, str(checkpoint))
    _install_is_magnetic_asset(monkeypatch, tmp_path / "asset")

    assert checkpoint_path() == checkpoint


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


class _InlineWorker:
    """A ``WorkerProcess`` stand-in: runs each call in this process and
    records the calls and whether it was closed."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.closed = False

    def run(self, fn, *args):
        self.calls.append(args)
        return fn(*args)

    def close(self) -> None:
        self.closed = True


def _no_worker() -> None:
    raise AssertionError("no ranking process may start")


def _stub_relax_seam(
    monkeypatch: pytest.MonkeyPatch, fake_relax
) -> list[_InlineWorker]:
    """Replace goldilocks-ml's own relax/domain_limits/safe_load, so
    rank_orderings()'s winner-selection logic can be exercised without the
    real mace/e3nn/sphericart stack -- these modules import fine without it
    (only calling into them needs it, see their own docstrings), so
    monkeypatching the real functions directly, not injecting fake modules,
    is enough here.

    The ranking's process is an inline worker, so the stubs apply; returns
    every worker a ranking started."""
    workers: list[_InlineWorker] = []

    def start_worker() -> _InlineWorker:
        workers.append(_InlineWorker())
        return workers[-1]

    _report_mace_installed(monkeypatch)
    magnetic_ordering_ml._domain_limits.cache_clear()
    monkeypatch.setattr(magnetic_ordering_ml, "WorkerProcess", start_worker)
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
    return workers


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

    monkeypatch.setattr(magnetic_ordering_ml, "WorkerProcess", _no_worker)

    with pytest.raises(
        MagneticOrderingMlUnavailable, match=f"^{missing} not installed"
    ):
        rank_orderings([("fm", _BCC_IRON)])


def test_rank_orderings_relaxes_each_candidate_in_turn_on_a_process_of_its_own(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """One call per candidate, so the caller hears after each one (#261);
    the process is the ranking's own and ends with it."""
    _configure_checkpoint(monkeypatch, tmp_path)
    workers = _stub_relax_seam(monkeypatch, _ok_relaxation)
    progress = []

    rank_orderings(
        [("fm", _BCC_IRON), ("afm-1", _BCC_IRON_AFM)],
        device="cpu",
        on_progress=lambda done, total: progress.append((done, total)),
    )

    checkpoint = tmp_path / "backbone.model"
    assert [(worker.calls, worker.closed) for worker in workers] == [
        (
            [
                ("fm", _BCC_IRON, checkpoint, "cpu"),
                ("afm-1", _BCC_IRON_AFM, checkpoint, "cpu"),
            ],
            True,
        )
    ]
    assert progress == [(0, 2), (1, 2), (2, 2)]


def test_rank_orderings_runs_on_the_worker_it_is_given_and_leaves_it_open(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A ranking job owns its worker, to kill it on cancel (#261)."""
    _configure_checkpoint(monkeypatch, tmp_path)
    started = _stub_relax_seam(monkeypatch, _ok_relaxation)
    worker = _InlineWorker()

    rank_orderings([("fm", _BCC_IRON)], worker=worker)

    assert (len(worker.calls), worker.closed, started) == (1, False, [])


@pytest.mark.parametrize(("raw", "limit"), [(None, 200), ("", 200), (" 50 ", 50)])
def test_max_atoms_reads_the_variable_with_a_default_of_200(
    raw: str | None, limit: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    if raw is None:
        monkeypatch.delenv(MAX_ATOMS_ENV, raising=False)
    else:
        monkeypatch.setenv(MAX_ATOMS_ENV, raw)

    assert max_atoms() == limit


@pytest.mark.parametrize("raw", ["0", "-5", "1.5", "lots"])
def test_max_atoms_refuses_a_value_that_is_not_a_positive_whole_number(
    raw: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(MAX_ATOMS_ENV, raw)

    with pytest.raises(ValueError, match=f"^{MAX_ATOMS_ENV}="):
        max_atoms()


@pytest.fixture
def torch_cuda(monkeypatch: pytest.MonkeyPatch):
    """Sets what torch reports about CUDA, and forgets mmace_device's cached
    answer before and after the test."""
    import torch

    def report(*, available: bool, build: str | None) -> None:
        monkeypatch.setattr(torch.cuda, "is_available", lambda: available)
        monkeypatch.setattr(torch.version, "cuda", build)

    magnetic_ordering_ml._cuda_or_cpu.cache_clear()
    yield report
    magnetic_ordering_ml._cuda_or_cpu.cache_clear()


@pytest.mark.parametrize("raw", [None, "", " cpu "])
def test_mmace_device_is_the_cpu_unless_set_to_cuda(
    raw: str | None, monkeypatch: pytest.MonkeyPatch, torch_cuda
) -> None:
    torch_cuda(available=True, build="13.0")
    if raw is None:
        monkeypatch.delenv(DEVICE_ENV, raising=False)
    else:
        monkeypatch.setenv(DEVICE_ENV, raw)

    assert mmace_device() == "cpu"


@pytest.mark.parametrize("raw", ["gpu", "CUDA", "cuda:0", "mps"])
def test_mmace_device_refuses_a_value_other_than_cpu_or_cuda(
    raw: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DEVICE_ENV, raw)

    with pytest.raises(ValueError, match=f"^{DEVICE_ENV}=.* is neither cpu nor cuda$"):
        mmace_device()


def test_mmace_device_is_cuda_when_torch_sees_a_cuda_device(
    monkeypatch: pytest.MonkeyPatch, torch_cuda, caplog: pytest.LogCaptureFixture
) -> None:
    torch_cuda(available=True, build="13.0")
    monkeypatch.setenv(DEVICE_ENV, "cuda")

    assert mmace_device() == "cuda"
    assert caplog.records == []


@pytest.mark.parametrize(
    ("build", "reason"),
    [
        (
            None,
            "this torch build (.*) has no CUDA; install it with "
            "`uv sync --no-group cpu --group cu130`",
        ),
        ("13.0", "torch sees no CUDA device"),
    ],
)
def test_mmace_device_falls_back_to_the_cpu_once_saying_why(
    build: str | None,
    reason: str,
    monkeypatch: pytest.MonkeyPatch,
    torch_cuda,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """#268: Junwen's call -- a server set up for a GPU it cannot reach
    still ranks, on the CPU, and says so once rather than per ranking."""
    torch_cuda(available=False, build=build)
    monkeypatch.setenv(DEVICE_ENV, "cuda")

    assert [mmace_device(), mmace_device()] == ["cpu", "cpu"]
    assert [record.levelname for record in caplog.records] == ["WARNING"]
    assert re.fullmatch(
        f"{DEVICE_ENV}=cuda, but {reason}.*, so mMACE runs on the CPU",
        caplog.records[0].getMessage(),
    )


def test_rank_orderings_relaxes_on_the_configured_device_unless_given_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path, torch_cuda
) -> None:
    _configure_checkpoint(monkeypatch, tmp_path)
    workers = _stub_relax_seam(monkeypatch, _ok_relaxation)
    torch_cuda(available=True, build="13.0")
    monkeypatch.setenv(DEVICE_ENV, "cuda")

    rank_orderings([("fm", _IRON)])
    rank_orderings([("fm", _IRON)], device="cpu")

    assert [worker.calls[0][-1] for worker in workers] == ["cuda", "cpu"]


class _RecordingWorker:
    """A ``WorkerProcess`` stand-in that records its calls without running them."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def run(self, fn, *args):
        self.calls.append((fn, *args))


def test_warm_ranking_worker_relaxes_once_on_the_configured_device(
    monkeypatch: pytest.MonkeyPatch, tmp_path, torch_cuda
) -> None:
    """#285: the ranking job that takes it starts no process, imports
    nothing and loads no checkpoint, on the device its ranking will use."""
    _configure_checkpoint(monkeypatch, tmp_path)
    _report_mace_installed(monkeypatch)
    torch_cuda(available=True, build="13.0")
    monkeypatch.setenv(DEVICE_ENV, "cuda")
    monkeypatch.setattr(magnetic_ordering_ml, "WorkerProcess", _RecordingWorker)

    worker = warm_ranking_worker()

    assert worker.calls == [
        (magnetic_ordering_ml._warm_up, tmp_path / "backbone.model", "cuda")
    ]


def test_warm_ranking_worker_leaves_the_worker_cold_where_ranking_cannot_run(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The ranking given the cold worker then degrades to an unranked
    listing, as it would have anyway."""

    def no_checkpoint():
        raise MagneticOrderingMlUnavailable("no mMACE backbone checkpoint")

    monkeypatch.setattr(magnetic_ordering_ml, "checkpoint_path", no_checkpoint)
    monkeypatch.setattr(magnetic_ordering_ml, "WorkerProcess", _RecordingWorker)
    caplog.set_level("INFO", logger=magnetic_ordering_ml.__name__)

    worker = warm_ranking_worker()

    assert worker.calls == []
    assert [r.getMessage() for r in caplog.records] == [
        "ranking worker left cold: no mMACE backbone checkpoint"
    ]


def test_serve_stops_on_a_bad_device_before_either_transport_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import argparse

    from goldilocks_core.cli import _serve
    from goldilocks_core.server import http, mcp

    started = []
    monkeypatch.setattr(http, "serve", lambda **kwargs: started.append("http"))
    monkeypatch.setattr(mcp, "serve", lambda: started.append("mcp"))
    monkeypatch.setenv(DEVICE_ENV, "gpu")

    for transport in ("http", "mcp"):
        with pytest.raises(ValueError, match=f"^{DEVICE_ENV}="):
            _serve.run(
                argparse.Namespace(
                    transport=transport, host="127.0.0.1", port=8000, static_root=None
                )
            )

    monkeypatch.setenv(DEVICE_ENV, "cpu")
    _serve.run(argparse.Namespace(transport="mcp"))
    assert started == ["mcp"]


def test_rank_orderings_refuses_a_candidate_above_the_atom_limit_before_a_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """#259: the largest candidate decides, since a candidate's cell can be
    larger than the input's."""
    _configure_checkpoint(monkeypatch, tmp_path)
    _report_mace_installed(monkeypatch)
    monkeypatch.setenv(MAX_ATOMS_ENV, "1")

    monkeypatch.setattr(magnetic_ordering_ml, "WorkerProcess", _no_worker)

    with pytest.raises(MagneticOrderingMlUnavailable) as raised:
        rank_orderings([("fm", _IRON), ("afm-1", _BCC_IRON_AFM)])

    assert str(raised.value) == (
        "mMACE ranking was not run: candidate afm-1 has 2 atoms, above this "
        "server's 1-atom limit for mMACE (GOLDILOCKS_MMACE_MAX_ATOMS)"
    )


def test_rank_orderings_runs_with_every_candidate_at_the_atom_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _configure_checkpoint(monkeypatch, tmp_path)
    workers = _stub_relax_seam(monkeypatch, _ok_relaxation)
    monkeypatch.setenv(MAX_ATOMS_ENV, "2")

    rank_orderings([("fm", _IRON), ("afm-1", _BCC_IRON_AFM)])

    assert [len(worker.calls) for worker in workers] == [2]


def test_a_listing_above_the_atom_limit_comes_back_unranked_saying_why(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _configure_checkpoint(monkeypatch, tmp_path)
    _report_mace_installed(monkeypatch)
    monkeypatch.setenv(MAX_ATOMS_ENV, "1")
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    monkeypatch.setattr(magnetic_ordering_ml, "WorkerProcess", _no_worker)

    report = list_magnetic_orderings(_BCC_IRON, rank_with_mmace=True)

    assert not report.ranked
    assert [candidate.label for candidate in report.candidates] == ["fm"]
    assert [
        warning.message
        for warning in report.warnings
        if warning.code == "magnetic.ordering_ranking_unavailable"
    ] == [
        "mMACE ranking was not run: candidate fm has 2 atoms, above this "
        "server's 1-atom limit for mMACE (GOLDILOCKS_MMACE_MAX_ATOMS)"
    ]


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

    class KilledWorker(_InlineWorker):
        def run(self, fn, *args):
            raise WorkerDied("worker process exited with code -9")

    monkeypatch.setattr(magnetic_ordering_ml, "WorkerProcess", KilledWorker)
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

    class SlowWorker(_InlineWorker):
        def run(self, fn, *args):
            nonlocal running
            with lock:
                running += 1
                most_at_once.append(running)
            time.sleep(0.2)
            with lock:
                running -= 1
            return magnetic_ordering_ml.OrderingCandidate(
                label="fm", structure=_BCC_IRON, energy_per_atom_ev=-8.0, status="ok"
            )

    monkeypatch.setattr(magnetic_ordering_ml, "WorkerProcess", SlowWorker)
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
    importlib.util.find_spec("mace") is None,
    reason="needs goldilocks-ml with mace-torch",
)
def test_rank_orderings_ranks_antiferromagnetic_nio_below_ferromagnetic(
    real_assets: None,
) -> None:
    """A coarse sanity check against the real backbone, when it is present.

    Never runs in CI, which installs no assets: the backbone (84 MB) comes
    with the default profile's is_magnetic asset (#244). Verified
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
