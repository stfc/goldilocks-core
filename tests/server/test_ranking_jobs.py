"""ranking_jobs: rankings queue in order, report where they stand, and can be
cancelled (#261), each on a worker warmed ahead of it (#285).

The queue's rank function is a stub each test controls: it waits on an event
per job, or sleeps on the job's real worker process where killing that
process is what is under test. Workers are plain, cold ``WorkerProcess``es,
or recording stand-ins where warming is what is under test.
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
    queue = RankingQueue(rank, warm_worker=WorkerProcess)
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
    queue = RankingQueue(rank, warm_worker=WorkerProcess)
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

    queue = RankingQueue(rank, warm_worker=WorkerProcess)
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

    queue = RankingQueue(rank, warm_worker=WorkerProcess)
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
    queue = RankingQueue(
        rank, warm_worker=WorkerProcess, abandoned_after_s=10, clock=lambda: now[0]
    )
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
        lambda name, worker, progress: {"ranked": name},
        warm_worker=WorkerProcess,
        keep_finished=1,
    )
    older = queue.submit("older")["job_id"]
    _until(queue, older, lambda status: status["state"] == "done")
    newer = queue.submit("newer")["job_id"]
    _until(queue, newer, lambda status: status["state"] == "done")

    assert queue.status(older) is None


class _Worker:
    """A stand-in for a warmed ``WorkerProcess`` that records its lifecycle."""

    def __init__(self, number: int) -> None:
        self.number = number
        self.closed = False
        self.killed = False

    def close(self) -> None:
        self.closed = True

    def kill(self) -> None:
        self.killed = True


class _Warmer:
    """Makes numbered ``_Worker``s; ``hold`` blocks warming until released."""

    def __init__(self) -> None:
        self.made: list[_Worker] = []
        self.hold = threading.Event()
        self.hold.set()
        self.lock = threading.Lock()

    def __call__(self) -> _Worker:
        self.hold.wait()
        with self.lock:
            worker = _Worker(len(self.made) + 1)
            self.made.append(worker)
        return worker


def _until_true(predicate) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition never held")


def test_start_warms_the_first_worker_before_any_job() -> None:
    warmer = _Warmer()
    queue = RankingQueue(lambda name, worker, progress: {}, warm_worker=warmer)

    queue.start()

    _until_true(lambda: len(warmer.made) == 1)


def test_each_job_takes_a_worker_warmed_ahead_and_closes_it_when_done() -> None:
    """#285: no job starts its own worker, and none inherits another's."""
    warmer = _Warmer()
    used: list[_Worker] = []
    queue = RankingQueue(
        lambda name, worker, progress: used.append(worker) or {"ranked": name},
        warm_worker=warmer,
    )
    queue.start()

    first = queue.submit("first")["job_id"]
    _until(queue, first, lambda status: status["state"] == "done")
    second = queue.submit("second")["job_id"]
    _until(queue, second, lambda status: status["state"] == "done")

    _until_true(lambda: len(warmer.made) == 3)  # the next job's is ready
    standby = [w for w in warmer.made if w not in used]
    assert len(used) == len(set(map(id, used))) == 2
    assert [(w.closed, w.killed) for w in used] == [(True, False), (True, False)]
    assert [(w.closed, w.killed) for w in standby] == [(False, False)]


def test_a_job_dropped_while_its_worker_warms_never_runs() -> None:
    warmer = _Warmer()
    warmer.hold.clear()
    ranked: list[str] = []
    queue = RankingQueue(
        lambda name, worker, progress: ranked.append(name) or {},
        warm_worker=warmer,
    )
    job = queue.submit("doomed")["job_id"]
    _until(queue, job, lambda status: status["state"] == "running")

    assert queue.cancel(job)
    warmer.hold.set()

    # The job's worker and the next standby warm at once, in either order:
    # the one the dropped job took is closed unused, the other waits.
    _until_true(lambda: any(w.closed for w in warmer.made))
    _until_true(lambda: len(warmer.made) == 2)
    assert sorted(w.closed for w in warmer.made) == [False, True]
    assert ranked == []
    assert queue.status(job) is None


def test_a_worker_that_cannot_be_warmed_fails_the_job_saying_why() -> None:
    def broken() -> WorkerProcess:
        raise ValueError("GOLDILOCKS_MMACE_DEVICE='gpu' is neither cpu nor cuda")

    queue = RankingQueue(lambda name, worker, progress: {}, warm_worker=broken)
    job = queue.submit("any")["job_id"]

    status = _until(queue, job, lambda status: status["state"] == "failed")

    assert status["error"] == "GOLDILOCKS_MMACE_DEVICE='gpu' is neither cpu nor cuda"
