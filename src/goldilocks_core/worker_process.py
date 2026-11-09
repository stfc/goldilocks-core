"""Run a call in a child process, so whatever process-wide state it changes
(the working directory, a library's global settings) never reaches the caller
or the caller's other threads (#136).

``WorkerProcess`` keeps one child alive across calls and runs them one at a
time; ``run_in_fresh_process`` starts a child for a single call. A child is a
new interpreter, never a ``fork`` of the caller (which can be a threaded
server with torch loaded), started in the system temporary directory with the
caller's ``sys.path``. Unlike ``multiprocessing``'s ``spawn``, it never
imports the caller's ``__main__`` module, so neither a script's unguarded
top-level code nor a host program's entry point (pytest, mutmut, uvicorn)
runs again in the child. Its stdin is empty and its stdout is the caller's
stderr, so it can never read or write a transport's stdio stream.

A call's function must be importable by module and name, and its arguments
and result picklable. An exception it raises is re-raised in the caller, with
the child's traceback as a note. A child exits when its caller does, however
the caller ends: it reads its next call from a pipe only the caller writes
to.

A child can keep memory a call's native code allocated after the call
returns, which only its exit releases: ``WorkerProcess.replace_when_idle``
swaps in a fresh, warmed child once the worker is idle (#260).
"""

from __future__ import annotations

import logging
import os
import pickle
import subprocess
import sys
import tempfile
import threading
import traceback
from collections.abc import Callable
from multiprocessing import Pipe
from multiprocessing.connection import Connection

__all__ = ["WorkerDied", "WorkerProcess", "run_in_fresh_process"]

_LOG = logging.getLogger(__name__)

_BOOTSTRAP = """\
import sys
from multiprocessing.connection import Connection

requests = Connection(int(sys.argv[1]), writable=False)
replies = Connection(int(sys.argv[2]), readable=False)
sys.path[:] = requests.recv()
from goldilocks_core.worker_process import _serve

_serve(requests, replies)
"""


class WorkerDied(RuntimeError):
    """The child process ended before answering a call."""


class WorkerProcess:
    """One long-lived child process that runs calls one at a time.

    The child starts on the first call; concurrent callers wait for the call
    in progress. If the child dies, the call that finds out raises
    ``WorkerDied`` and the next call starts a new child. A caller interrupted
    while waiting also discards the child."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._child: _Child | None = None
        self._calling: _Child | None = None
        self._killed = False
        self._calls = 0
        """Calls started so far: a pending replacement acts only if no call
        has started since it was scheduled."""

    def run[T](self, fn: Callable[..., T], /, *args: object) -> T:
        request = pickle.dumps((fn, args))
        self._calls += 1
        with self._lock:
            if self._killed:
                raise WorkerDied("worker process was killed")
            child = self._child if self._child is not None else _Child()
            self._child = None
            self._calling = child
            try:
                if self._killed:  # killed while the child started
                    raise WorkerDied("worker process was killed")
                reply = child.call(request)
            except BaseException:
                child.kill()
                raise
            finally:
                self._calling = None
            self._child = child
        return _result(reply)

    def replace_when_idle(
        self, after_s: float, warm_up: Callable[..., object], /, *args: object
    ) -> None:
        """Once no call has started for ``after_s`` seconds, start a new
        child, run ``warm_up(*args)`` on it, and make it this worker's child;
        the old child then exits, and with it all the memory it held. A call
        started first cancels the replacement. Calls keep going to the old
        child until the new one is warm, so none waits for the warm-up.

        For a child that keeps memory after a call no matter what it frees
        (#260). A warm-up that fails leaves the old child in place."""
        request = pickle.dumps((warm_up, args))
        timer = threading.Timer(after_s, self._replace, (self._calls, request))
        timer.daemon = True
        timer.start()

    def _replace(self, calls: int, request: bytes) -> None:
        if calls != self._calls or self._killed:
            return
        child = _Child()
        try:
            succeeded, error = child.call(request)
        except WorkerDied:
            child.kill()
            return
        if not succeeded:
            child.kill()
            _LOG.error("worker warm-up failed; keeping the old child: %s", error)
            return
        with self._lock:
            old, self._child = self._child, child
            if self._killed:
                old, self._child = child, None
        if old is not None:
            old.close()

    def close(self) -> None:
        """End the child once the call in progress, if any, returns."""
        with self._lock:
            if self._child is not None:
                self._child.close()
                self._child = None

    def kill(self) -> None:
        """End the child now, without waiting; safe from any thread. The
        call in progress and every later call raise ``WorkerDied``: a killed
        worker is finished."""
        self._killed = True
        calling = self._calling
        if calling is not None:
            calling.end_process()
        elif self._lock.acquire(blocking=False):
            try:
                if self._child is not None:
                    self._child.kill()
                    self._child = None
            finally:
                self._lock.release()
        # Otherwise a call holds the lock without a child yet, and stops on
        # the flag; or it is returning, and the next call stops on it.


def run_in_fresh_process[T](fn: Callable[..., T], /, *args: object) -> T:
    """Run ``fn(*args)`` in a child process started for this call alone."""
    request = pickle.dumps((fn, args))
    child = _Child()
    try:
        reply = child.call(request)
    except BaseException:
        child.kill()
        raise
    child.close()
    return _result(reply)


class _Child:
    """A child interpreter answering pickled ``(fn, args)`` requests."""

    def __init__(self) -> None:
        request_reader, self._requests = Pipe(duplex=False)
        self._replies, reply_writer = Pipe(duplex=False)
        child_ends = (request_reader.fileno(), reply_writer.fileno())
        try:
            self._process = subprocess.Popen(
                [sys.executable, "-P", "-c", _BOOTSTRAP, *map(str, child_ends)],
                pass_fds=child_ends,
                stdin=subprocess.DEVNULL,
                stdout=2,
                cwd=tempfile.gettempdir(),
            )
        finally:
            request_reader.close()
            reply_writer.close()
        self._send(pickle.dumps([os.path.abspath(entry) for entry in sys.path]))

    def call(self, request: bytes) -> tuple[bool, object]:
        self._send(request)
        try:
            return self._replies.recv()
        except EOFError:
            raise self._died() from None

    def close(self) -> None:
        self._requests.close()
        self._process.wait()
        self._replies.close()

    def kill(self) -> None:
        self._process.kill()
        self.close()

    def end_process(self) -> None:
        """Kill the process and leave the pipes to the caller blocked on
        them, whose read then fails."""
        self._process.kill()

    def _send(self, message: bytes) -> None:
        try:
            self._requests.send_bytes(message)
        except BrokenPipeError:
            raise self._died() from None

    def _died(self) -> WorkerDied:
        return WorkerDied(f"worker process exited with code {self._process.wait()}")


def _result[T](reply: tuple[bool, T | BaseException]) -> T:
    succeeded, value = reply
    if not succeeded:
        raise value
    return value


def _serve(requests: Connection, replies: Connection) -> None:
    """Child side: answer each request until the caller's end of the pipe
    closes."""
    while True:
        try:
            request = requests.recv_bytes()
        except EOFError:
            return
        try:
            fn, args = pickle.loads(request)
            reply = (True, fn(*args))
        except BaseException as error:  # noqa: BLE001 -- re-raised in the caller
            error.add_note(
                f"Raised in worker process {os.getpid()}:\n"
                + "".join(traceback.format_exception(error))
            )
            reply = (False, error)
        replies.send(reply)
