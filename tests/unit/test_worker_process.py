"""Worker processes keep process-wide state out of the caller (#136).

Every call runs a stdlib function, so the child never has to import a test
module.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from goldilocks_core.worker_process import (
    WorkerDied,
    WorkerProcess,
    run_in_fresh_process,
)

_ORPHANING_SCRIPT = """
import os, sys
from goldilocks_core.worker_process import WorkerProcess

with open(sys.argv[1], "w") as pid_file:
    pid_file.write(str(WorkerProcess().run(os.getpid)))
os._exit(0)
"""
"""Starts a worker, records its PID, then ends without interpreter shutdown,
as a SIGKILL or a forked test runner's ``os._exit`` does."""

_UNGUARDED_SCRIPT = """
import os, sys
from goldilocks_core.worker_process import WorkerProcess

with open(sys.argv[1], "a") as log:
    log.write("top level ran\\n")
WorkerProcess().run(os.getpid)
"""
"""A script with no ``if __name__ == "__main__":`` guard, which
``multiprocessing``'s ``spawn`` would run again in its child."""

_STDIO_SCRIPT = """
import os, sys
from goldilocks_core.worker_process import WorkerProcess

worker = WorkerProcess()
read = worker.run(os.read, 0, 64)
worker.run(os.write, 1, b"written by the worker\\n")
sys.stdout.write(repr(read))
"""
"""Starts a worker under a caller whose stdin holds data, reads stdin and
writes to fd 1 in the worker, then prints what the worker read."""


def test_a_call_runs_in_another_process() -> None:
    assert WorkerProcess().run(os.getpid) != os.getpid()


def test_consecutive_calls_share_one_long_lived_process() -> None:
    worker = WorkerProcess()

    assert worker.run(os.getpid) == worker.run(os.getpid)


def test_a_chdir_in_the_worker_leaves_the_callers_cwd_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    caller_cwd = os.getcwd()
    worker = WorkerProcess()

    worker.run(os.chdir, "/")

    assert worker.run(os.getcwd) == "/"
    assert os.getcwd() == caller_cwd


def test_an_exception_in_the_call_is_re_raised_and_the_worker_lives_on(
    tmp_path: Path,
) -> None:
    worker = WorkerProcess()
    pid = worker.run(os.getpid)

    with pytest.raises(FileNotFoundError):
        worker.run(os.chdir, str(tmp_path / "missing"))

    assert worker.run(os.getpid) == pid


def test_a_killed_worker_fails_the_next_call_and_the_one_after_restarts_it() -> None:
    worker = WorkerProcess()
    killed = worker.run(os.getpid)

    os.kill(killed, signal.SIGKILL)

    with pytest.raises(WorkerDied):
        worker.run(os.getpid)
    assert worker.run(os.getpid) not in {killed, os.getpid()}


def test_close_ends_the_idle_child_and_the_next_call_starts_another() -> None:
    worker = WorkerProcess()
    closed = worker.run(os.getpid)

    worker.close()

    with pytest.raises(ProcessLookupError):
        os.kill(closed, 0)
    assert worker.run(os.getpid) != closed


def test_kill_from_another_thread_ends_the_call_in_progress() -> None:
    """A ranking job is cancelled from a request thread while its runner
    thread waits on the worker (#261)."""
    worker = WorkerProcess()
    worker.run(os.getpid)
    outcome: list[BaseException] = []

    def sleep_in_worker() -> None:
        try:
            worker.run(time.sleep, 30)
        except BaseException as error:  # noqa: BLE001 -- asserted below
            outcome.append(error)

    caller = threading.Thread(target=sleep_in_worker)
    caller.start()
    time.sleep(0.5)
    worker.kill()
    caller.join(timeout=10)

    assert not caller.is_alive()
    assert [type(error) for error in outcome] == [WorkerDied]
    with pytest.raises(WorkerDied, match="killed"):
        worker.run(os.getpid)


def _until_exited(pid: int) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    raise AssertionError(f"process {pid} did not exit")


def test_an_idle_worker_is_replaced_by_a_warmed_child_and_the_old_one_exits() -> None:
    """#260: the only sure way to release what a call's native code keeps
    is to end the process; the replacement is warm before it serves."""
    worker = WorkerProcess()
    old = worker.run(os.getpid)

    worker.replace_when_idle(0.1, os.chdir, "/")
    _until_exited(old)

    assert worker.run(os.getcwd) == "/"  # the warm-up ran on this child
    assert worker.run(os.getpid) != old


def test_a_call_before_the_worker_is_idle_cancels_its_replacement() -> None:
    worker = WorkerProcess()
    pid = worker.run(os.getpid)
    worker.replace_when_idle(0.3, os.getpid)

    assert worker.run(os.getpid) == pid
    time.sleep(0.6)

    assert worker.run(os.getpid) == pid


def test_a_failed_warm_up_keeps_the_old_child(
    caplog: pytest.LogCaptureFixture,
) -> None:
    worker = WorkerProcess()
    pid = worker.run(os.getpid)

    worker.replace_when_idle(0.1, os.chdir, "/no/such/directory")
    deadline = time.monotonic() + 10
    while "warm-up failed" not in caplog.text and time.monotonic() < deadline:
        time.sleep(0.05)

    assert "warm-up failed" in caplog.text
    assert worker.run(os.getpid) == pid


def test_the_worker_reads_no_stdin_and_writes_to_the_callers_stderr() -> None:
    """``serve mcp`` speaks JSON-RPC on stdin/stdout and the CLI's --json
    document goes to stdout, so a worker must touch neither. The caller is a
    separate process because pytest's capture already points this one's
    stdin at /dev/null."""
    completed = subprocess.run(
        [sys.executable, "-c", _STDIO_SCRIPT],
        input=b"a JSON-RPC request",
        capture_output=True,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == b"b''"
    assert b"written by the worker" in completed.stderr


def test_a_worker_exits_when_its_caller_dies_without_shutting_it_down(
    tmp_path: Path,
) -> None:
    """The worker writes to the script's stderr pipe, so reading that pipe to
    its end also waits for the worker to exit."""
    pid_file = tmp_path / "worker.pid"

    try:
        completed = subprocess.run(
            [sys.executable, "-c", _ORPHANING_SCRIPT, str(pid_file)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        os.kill(int(pid_file.read_text()), signal.SIGKILL)
        raise

    assert completed.returncode == 0, completed.stderr


def test_the_worker_never_runs_the_callers_main_module_again(tmp_path: Path) -> None:
    script = tmp_path / "unguarded.py"
    script.write_text(_UNGUARDED_SCRIPT)
    log = tmp_path / "top-level.log"

    subprocess.run(
        [sys.executable, str(script), str(log)],
        capture_output=True,
        check=True,
        timeout=60,
    )

    assert log.read_text() == "top level ran\n"


def test_run_in_fresh_process_starts_a_new_process_for_every_call() -> None:
    first = run_in_fresh_process(os.getpid)
    second = run_in_fresh_process(os.getpid)

    assert len({first, second, os.getpid()}) == 3
