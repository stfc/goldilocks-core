"""ranking_jobs: rankings queue in order, report where they stand, and can be
cancelled (#261).

The queue's rank function is a stub each test controls: it waits on an event
per job, or sleeps on the job's real worker process where killing that
process is what is under test.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable

from goldilocks_core.server.ranking_jobs import RankingQueue
from goldilocks_core.worker_process import WorkerProcess


class _GatedRank:
    """Ranks a structure (here a name) by reporting ``(0, 2)``, waiting for
    the test to open its gate, reporting ``(1, 2)``, waiting again, and
    returning ``{"ranked": name}``."""

    def __init__(self) -> None:
        self.gates: dict[str, threading.Semaphore] = {}
        self.started: list[str] = []

    def gate(self, name: str) -> threading.Semaphore:
        return self.gates.setdefault(name, threading.Semaphore(0))

    def __call__(
        self, name, worker: WorkerProcess, progress: Callable[[int, int], None]
    ) -> dict:
        self.started.append(name)
        progress(0, 2)
        self.gate(name).acquire()
        progress(1, 2)
        self.gate(name).acquire()
        return {"ranked": name}


def _until(queue: RankingQueue, job_id: str, predicate) -> dict:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        status = queue.status(job_id)
        if predicate(status):
            return status
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} never reached the state: {status}")


def test_a_second_ranking_waits_one_place_back_then_runs_with_progress() -> None:
    rank = _GatedRank()
    queue = RankingQueue(rank)
    first = queue.submit("first")["job_id"]
    second = queue.submit("second")["job_id"]
    _until(
        queue, first, lambda status: status.get("progress") == {"done": 0, "total": 2}
    )

    assert queue.status(second) == {"job_id": second, "state": "queued", "position": 1}

    rank.gate("first").release()
    _until(
        queue, first, lambda status: status.get("progress") == {"done": 1, "total": 2}
    )
    assert queue.status(second)["position"] == 1
    rank.gate("first").release()
    assert _until(queue, first, lambda status: status["state"] == "done") == {
        "job_id": first,
        "state": "done",
        "report": {"ranked": "first"},
    }
    assert _until(queue, second, lambda status: status["state"] == "running") == {
        "job_id": second,
        "state": "running",
        "progress": {"done": 0, "total": 2},
    }
    rank.gate("second").release()
    rank.gate("second").release()
    assert _until(queue, second, lambda status: status["state"] == "done")[
        "report"
    ] == {"ranked": "second"}


def test_a_cancelled_queued_job_is_dropped_without_running() -> None:
    rank = _GatedRank()
    queue = RankingQueue(rank)
    first = queue.submit("first")["job_id"]
    second = queue.submit("second")["job_id"]
    third = queue.submit("third")["job_id"]
    _until(queue, first, lambda status: status["state"] == "running")

    assert queue.cancel(second)

    assert queue.status(second) is None
    assert queue.status(third)["position"] == 1
    for _ in range(2):
        rank.gate("first").release()
    _until(queue, third, lambda status: status["state"] == "running")
    assert rank.started == ["first", "third"]
    assert not queue.cancel(second)


def test_a_cancelled_running_job_has_its_process_killed_and_the_next_starts() -> None:
    calling = threading.Event()

    def rank(name, worker: WorkerProcess, progress) -> dict:
        if name == "slow":
            worker.run(os.getpid)  # the child is up
            calling.set()
            worker.run(time.sleep, 60)
        return {"ranked": name}

    queue = RankingQueue(rank)
    slow = queue.submit("slow")["job_id"]
    quick = queue.submit("quick")["job_id"]
    assert calling.wait(timeout=10)

    started = time.monotonic()
    assert queue.cancel(slow)

    assert queue.status(slow) is None
    assert _until(queue, quick, lambda status: status["state"] == "done")["report"] == {
        "ranked": "quick"
    }
    assert time.monotonic() - started < 10


def test_a_ranking_that_raises_reports_its_error() -> None:
    def rank(name, worker, progress) -> dict:
        raise RuntimeError("enumlib is not installed")

    queue = RankingQueue(rank)
    job = queue.submit("broken")["job_id"]

    assert _until(queue, job, lambda status: status["state"] == "failed") == {
        "job_id": job,
        "state": "failed",
        "error": "enumlib is not installed",
    }


def test_a_job_nobody_asks_about_is_dropped_when_another_client_calls() -> None:
    """A closed browser tab stops polling; its jobs must not hold up the
    rankings queued behind them."""
    now = [0.0]
    rank = _GatedRank()
    queue = RankingQueue(rank, abandoned_after_s=10, clock=lambda: now[0])
    running = queue.submit("running")["job_id"]
    queued = queue.submit("queued")["job_id"]
    watched = queue.submit("watched")["job_id"]
    _until(queue, running, lambda status: status["state"] == "running")
    now[0] = 5.0
    queue.status(watched)

    now[0] = 12.0
    # The dropped run is no longer ahead of anyone, though it still has to
    # return before the next job starts.
    assert queue.status(watched)["position"] == 0

    assert (queue.status(running), queue.status(queued)) == (None, None)
    rank.gate("running").release()  # the abandoned run returns to nothing
    _until(queue, watched, lambda status: status["state"] == "running")


def test_only_the_newest_finished_jobs_are_kept() -> None:
    queue = RankingQueue(
        lambda name, worker, progress: {"ranked": name}, keep_finished=1
    )
    older = queue.submit("older")["job_id"]
    _until(queue, older, lambda status: status["state"] == "done")
    newer = queue.submit("newer")["job_id"]
    _until(queue, newer, lambda status: status["state"] == "done")

    assert queue.status(older) is None
