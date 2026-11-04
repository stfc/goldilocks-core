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
"""

from __future__ import annotations

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

    def run[T](self, fn: Callable[..., T], /, *args: object) -> T:
        request = pickle.dumps((fn, args))
        with self._lock:
            child = self._child if self._child is not None else _Child()
            self._child = None
            try:
                reply = child.call(request)
            except BaseException:
                child.kill()
                raise
            self._child = child
        return _result(reply)


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
