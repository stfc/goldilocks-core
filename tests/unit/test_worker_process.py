"""Worker processes keep process-wide state out of the caller (#136).

Every call runs a stdlib function, so the child never has to import a test
module.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
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
