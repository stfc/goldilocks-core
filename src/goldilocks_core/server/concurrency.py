"""Bounded per-process computation gate for the Workbench transport.

Recommend/generate/compute each acquire a slot before running the heavy Core
computation; health, task descriptions, and structure parsing stay ungated.
There is no durable queue and no claim that work is scheduled: when capacity is
full beyond a short configured wait, the caller receives a loud retryable
``server_busy`` failure.
"""

from __future__ import annotations

import threading

__all__ = ["ComputeBusyError", "ComputeGate", "RETRY_AFTER_SECONDS"]

RETRY_AFTER_SECONDS = 1


class ComputeBusyError(Exception):
    """Raised when computation capacity is saturated after a bounded wait."""

    def __init__(self, retry_after: int = RETRY_AFTER_SECONDS) -> None:
        super().__init__("The server is at full computation capacity. Retry shortly.")
        self.retry_after = retry_after


class ComputeGate:
    """Bound concurrent Core computations while allowing many HTTP connections.

    Each computation operation acquires a slot before running. When every slot
    is busy, a caller waits up to ``wait_seconds`` for one to free; if none
    frees in time it raises ``ComputeBusyError``, which the transport maps to a
    retryable ``server_busy`` 503 with a ``Retry-After`` header. The gate is a
    plain thread-safe semaphore: one shared instance per application, safe
    across the sync endpoints FastAPI runs in its threadpool.
    """

    def __init__(self, limit: int, wait_seconds: float) -> None:
        if limit < 1:
            raise ValueError("compute_limit must be >= 1.")
        if wait_seconds < 0:
            raise ValueError("compute_wait_seconds must be >= 0.")
        self._semaphore = threading.BoundedSemaphore(limit)
        self._wait_seconds = wait_seconds

    def acquire(self) -> "ComputeGate":
        """Block for a slot or raise ``ComputeBusyError`` after the bound."""
        acquired = self._semaphore.acquire(timeout=self._wait_seconds)
        if not acquired:
            raise ComputeBusyError()
        return self

    def release(self) -> None:
        self._semaphore.release()

    def __enter__(self) -> "ComputeGate":
        return self.acquire()

    def __exit__(self, *exc: object) -> None:
        self.release()
