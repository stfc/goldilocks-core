"""ranking_jobs: mMACE ordering rankings as jobs, for the HTTP transport (#261).

A ranking takes minutes and rankings run one at a time, so
``POST /magnetic-orderings/rank`` queues one and returns at once, and the
client polls it: its position in the queue while it waits, the candidates
relaxed so far while it runs, then the ranked listing or the error. One
runner thread takes the jobs in the order they arrived; each runs on a
``WorkerProcess`` of its own, which cancelling the job kills.

A job's worker is warmed ahead of it (#285): one standby worker, mace
imported, checkpoint loaded and device initialised, waits for the next job,
and as a job takes it the next standby starts warming. A worker exits when
its job ends, and with it every byte the job left behind, so nothing carries
over between jobs. The HTTP server warms the first standby as it starts.

Jobs live in this process's memory, so the HTTP server must be one process;
a restart forgets them. A queued or running job that nobody has asked about
for ``abandoned_after_s`` seconds is dropped the next time any client calls,
and killed if it runs, so a closed browser tab does not hold up the rankings
queued behind it. Finished jobs are kept until ``keep_finished`` newer ones
have finished.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, Literal

from pymatgen.core import Structure

from goldilocks_core.advisors.magnetic_ordering_ml import warm_ranking_worker
from goldilocks_core.service import list_magnetic_orderings, report_to_json
from goldilocks_core.worker_process import WorkerProcess

__all__ = ["Rank", "RankingQueue", "rank_orderings_report"]

JobState = Literal["queued", "running", "done", "failed"]

Rank = Callable[[Structure, WorkerProcess, Callable[[int, int], None]], Any]
"""Ranks a structure's orderings on the worker given, reporting
``(done, total)`` candidates through the callback; returns the JSON
document a finished job holds."""

_LOG = logging.getLogger(__name__)


class _Cancelled(Exception):
    """Raised from the progress callback of a job that was cancelled."""


@dataclass(eq=False)
class _Job:
    id: str
    structure: Structure
    seen: float
    state: JobState = "queued"
    progress: tuple[int, int] | None = None
    report: Any = None
    error: str | None = None
    worker: WorkerProcess | None = None
    cancelled: bool = False


def rank_orderings_report(
    structure: Structure,
    worker: WorkerProcess,
    on_progress: Callable[[int, int], None],
) -> dict[str, Any]:
    """The ranked listing of ``structure``'s orderings, as
    ``/magnetic-orderings`` documents a listing: the work of a job."""
    report = list_magnetic_orderings(
        structure, rank_with_mmace=True, worker=worker, on_progress=on_progress
    )
    return report_to_json(report)


class _Standby:
    """The worker the next job takes, warmed in the background (#285)."""

    def __init__(self, warm: Callable[[], WorkerProcess]) -> None:
        self._warm = warm
        self._next = self._prepare()

    def _prepare(self) -> Future[WorkerProcess]:
        future: Future[WorkerProcess] = Future()

        def build() -> None:
            try:
                future.set_result(self._warm())
            except BaseException as error:  # noqa: BLE001 -- take() re-raises it
                future.set_exception(error)

        threading.Thread(target=build, name="ranking-standby", daemon=True).start()
        return future

    def take(self) -> WorkerProcess:
        """The warm worker, once it is ready; the next one starts warming."""
        future, self._next = self._next, self._prepare()
        return future.result()


class RankingQueue:
    """Ranking jobs, run one at a time in submission order, each on a worker
    ``warm_worker()`` prepared ahead of it."""

    def __init__(
        self,
        rank: Rank = rank_orderings_report,
        *,
        warm_worker: Callable[[], WorkerProcess] = warm_ranking_worker,
        keep_finished: int = 64,
        abandoned_after_s: float = 120.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._rank = rank
        self._warm_worker = warm_worker
        self._standby: _Standby | None = None
        self._keep_finished = keep_finished
        self._abandoned_after_s = abandoned_after_s
        self._clock = clock
        self._lock = threading.Condition()
        self._jobs: dict[str, _Job] = {}
        self._queued: deque[_Job] = deque()
        self._running: _Job | None = None
        self._finished: deque[_Job] = deque()
        self._runner: threading.Thread | None = None

    def start(self) -> None:
        """Warm the first job's worker now, ahead of any job."""
        with self._lock:
            self._ready_standby()

    def _ready_standby(self) -> _Standby:
        if self._standby is None:
            self._standby = _Standby(self._warm_worker)
        return self._standby

    def submit(self, structure: Structure) -> dict[str, Any]:
        """Queue a ranking of ``structure``; returns its status."""
        with self._lock:
            doomed = self._drop_abandoned()
            job = _Job(id=uuid.uuid4().hex, structure=structure, seen=self._clock())
            self._jobs[job.id] = job
            self._queued.append(job)
            if self._runner is None:
                self._runner = threading.Thread(
                    target=self._run, name="ranking-jobs", daemon=True
                )
                self._runner.start()
            self._lock.notify()
            status = self._status(job)
        _kill(doomed)
        return status

    def status(self, job_id: str) -> dict[str, Any] | None:
        """The job's status, or ``None`` for a job this queue does not hold.

        ``{"job_id", "state"}`` plus, by state: ``position``, the number of
        rankings ahead (queued); ``progress``, ``{"done", "total"}``
        candidates or ``None`` before the relaxations start (running);
        ``report`` (done); ``error`` (failed)."""
        with self._lock:
            doomed = self._drop_abandoned()
            job = self._jobs.get(job_id)
            if job is not None:
                job.seen = self._clock()
            status = None if job is None else self._status(job)
        _kill(doomed)
        return status

    def cancel(self, job_id: str) -> bool:
        """Drop the job, killing its process if it runs; ``False`` if this
        queue does not hold it."""
        with self._lock:
            job = self._jobs.get(job_id)
            doomed = [] if job is None else self._drop(job)
        _kill(doomed)
        return job is not None

    def _status(self, job: _Job) -> dict[str, Any]:
        status: dict[str, Any] = {"job_id": job.id, "state": job.state}
        if job.state == "queued":
            running = self._running is not None and not self._running.cancelled
            status["position"] = self._queued.index(job) + running
        elif job.state == "running":
            status["progress"] = (
                None
                if job.progress is None
                else {"done": job.progress[0], "total": job.progress[1]}
            )
        elif job.state == "done":
            status["report"] = job.report
        else:
            status["error"] = job.error
        return status

    def _drop(self, job: _Job) -> list[WorkerProcess]:
        """Forget ``job``; returns the worker to kill once the lock is
        released, since killing an idle worker waits for its lock."""
        del self._jobs[job.id]
        if job.state == "queued":
            self._queued.remove(job)
        elif job.state == "running":
            job.cancelled = True
            return [job.worker] if job.worker is not None else []
        else:
            self._finished.remove(job)
        return []

    def _drop_abandoned(self) -> list[WorkerProcess]:
        cutoff = self._clock() - self._abandoned_after_s
        abandoned = [
            job
            for job in self._jobs.values()
            if job.state in ("queued", "running") and job.seen < cutoff
        ]
        return [worker for job in abandoned for worker in self._drop(job)]

    def _run(self) -> None:
        while True:
            with self._lock:
                while not self._queued:
                    self._lock.wait()
                job = self._queued.popleft()
                job.state = "running"
                self._running = job
                standby = self._ready_standby()
            try:
                worker = standby.take()
            except Exception as failure:  # noqa: BLE001 -- the job reports it
                self._finish(job, None, str(failure))
                continue
            with self._lock:
                if job.cancelled:  # dropped while its worker warmed
                    self._running = None
                else:
                    job.worker = worker
            if job.worker is None:
                worker.close()
                continue
            self._run_job(job, worker)

    def _run_job(self, job: _Job, worker: WorkerProcess) -> None:
        def progress(done: int, total: int) -> None:
            with self._lock:
                if job.cancelled:
                    raise _Cancelled
                job.progress = (done, total)

        report, error = None, None
        try:
            report = self._rank(job.structure, worker, progress)
        except Exception as failure:  # noqa: BLE001 -- the job reports it
            error = str(failure)
        finally:
            worker.close()
        self._finish(job, report, error)

    def _finish(self, job: _Job, report: Any, error: str | None) -> None:
        with self._lock:
            self._running = None
            job.worker = None
            if job.cancelled:
                return
            if error is not None:
                _LOG.error("ranking job %s failed: %s", job.id, error)
            job.state = "failed" if error is not None else "done"
            job.report, job.error = report, error
            self._finished.append(job)
            while len(self._finished) > self._keep_finished:
                del self._jobs[self._finished.popleft().id]


def _kill(workers: list[WorkerProcess]) -> None:
    for worker in workers:
        worker.kill()
