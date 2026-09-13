from __future__ import annotations

import multiprocessing
import os
import sys
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any

CGROUP_ROOT = Path("/sys/fs/cgroup")
MEMORY_BUDGET_SHARE = 0.6
WORKERS_ENV = "GOLDILOCKS_WEB_WORKERS"
MIN_THREADPOOL_TOKENS = 2
MAX_THREADPOOL_TOKENS = 8

__all__ = [
    "available_cpus",
    "configure_threadpool",
    "create_worker_app",
    "default_workers",
    "memory_budget_bytes",
    "plan_workers",
    "serve",
    "threadpool_tokens",
]


def serve(
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    static_root: str | Path | None = None,
    workers: int | None = None,
) -> None:
    try:
        import uvicorn
    except ImportError as error:
        from goldilocks_core.server.http import MISSING_HTTP_EXTRA

        raise ImportError(MISSING_HTTP_EXTRA) from error
    if static_root is not None:
        from goldilocks_core.server.http import WORKBENCH_STATIC_ROOT_ENV

        os.environ[WORKBENCH_STATIC_ROOT_ENV] = str(static_root)
    uvicorn.run(
        "goldilocks_core.server.workers:create_worker_app",
        factory=True,
        host=host,
        port=port,
        workers=workers if workers is not None else default_workers(),
    )


def create_worker_app() -> Any:
    from goldilocks_core.server.http import create_app

    app = create_app()
    app.state.goldilocks.prewarm()
    return app


def configure_threadpool() -> None:
    import anyio.to_thread

    limiter = anyio.to_thread.current_default_thread_limiter()
    limiter.total_tokens = threadpool_tokens()


def threadpool_tokens() -> int:
    return max(MIN_THREADPOOL_TOKENS, min(MAX_THREADPOOL_TOKENS, available_cpus()))


def plan_workers(
    cpus: int,
    memory_budget_bytes: int | None,
    worker_cost_bytes: int | None,
) -> int:
    if cpus <= 1:
        return 1
    memory_known = memory_budget_bytes is not None and memory_budget_bytes > 0
    cost_known = worker_cost_bytes is not None and worker_cost_bytes > 0
    if not memory_known or not cost_known:
        return cpus
    budget = int(memory_budget_bytes * MEMORY_BUDGET_SHARE // worker_cost_bytes)
    return max(1, min(cpus, budget))


def default_workers() -> int:
    override = os.environ.get(WORKERS_ENV)
    if override:
        return max(1, int(override))
    return plan_workers(
        available_cpus(),
        memory_budget_bytes(),
        measured_worker_cost_bytes(),
    )


def available_cpus() -> int:
    try:
        cpus = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        cpus = os.cpu_count() or 1
    quota = _cgroup_cpu_quota()
    if quota is not None:
        cpus = min(cpus, quota)
    return max(1, cpus)


def memory_budget_bytes(root: Path = CGROUP_ROOT) -> int | None:
    budgets = [
        value
        for value in (_cgroup_memory_limit_bytes(root), _available_memory_bytes())
        if value is not None
    ]
    return min(budgets) if budgets else None


def measured_worker_cost_bytes() -> int | None:
    try:
        context = multiprocessing.get_context("fork")
    except ValueError:
        return None
    receiver, sender = multiprocessing.Pipe(False)
    process = context.Process(target=_measure_in_child, args=(sender,), daemon=True)
    process.start()
    sender.close()
    try:
        kind, value = receiver.recv()
    finally:
        receiver.close()
        process.join()
    if kind == "unavailable":
        return None
    return max(int(value), 0)


def _measure_in_child(sender: Connection) -> None:
    try:
        from goldilocks_core.advice.kdistance import QrfBackend

        baseline = _peak_rss_bytes()
        QrfBackend().prewarm()
        sender.send(("cost", _peak_rss_bytes() - baseline))
    except Exception as error:
        if isinstance(error, _asset_not_installed_type()):
            sender.send(("unavailable", None))
        else:
            raise
    finally:
        sender.close()


def _asset_not_installed_type() -> type:
    from goldilocks_core.assets.store import AssetNotInstalled

    return AssetNotInstalled


def _cgroup_cpu_quota(root: Path = CGROUP_ROOT) -> int | None:
    v2 = root / "cpu.max"
    if v2.is_file():
        fields = v2.read_text().split()
        if len(fields) != 2 or fields[0] == "max":
            return None
        return _quota_to_cpus(int(fields[0]), int(fields[1]))
    quota_path = root / "cpu" / "cpu.cfs_quota_us"
    period_path = root / "cpu" / "cpu.cfs_period_us"
    if quota_path.is_file() and period_path.is_file():
        return _quota_to_cpus(int(quota_path.read_text()), int(period_path.read_text()))
    return None


def _quota_to_cpus(quota: int, period: int) -> int | None:
    if quota <= 0 or period <= 0:
        return None
    return max(1, -(-quota // period))


def _cgroup_memory_limit_bytes(root: Path = CGROUP_ROOT) -> int | None:
    v2 = root / "memory.max"
    if v2.is_file():
        value = v2.read_text().strip()
        return None if value == "max" else int(value)
    v1 = root / "memory" / "memory.limit_in_bytes"
    if v1.is_file():
        value = int(v1.read_text())
        return None if value >= 1 << 60 else value
    return None


def _available_memory_bytes() -> int | None:
    try:
        with open("/proc/meminfo") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    try:
        return os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (AttributeError, OSError, ValueError):
        return None


def _peak_rss_bytes() -> int:
    try:
        with open("/proc/self/status") as handle:
            for line in handle:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024
