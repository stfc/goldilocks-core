from __future__ import annotations

import math
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager

COMPUTE_WAIT_ENV = "GOLDILOCKS_COMPUTE_WAIT_SECONDS"
DEFAULT_COMPUTE_WAIT_SECONDS = 1.0


class ServerBusy(RuntimeError):
    def __init__(self, retry_after_seconds: float) -> None:
        super().__init__("The computation slot is busy; retry this request.")
        self.retry_after_seconds = retry_after_seconds


class ComputationCapacity:
    def __init__(self, wait_seconds: float) -> None:
        if (
            isinstance(wait_seconds, bool)
            or not isinstance(wait_seconds, (int, float))
            or not math.isfinite(wait_seconds)
            or wait_seconds < 0
        ):
            raise ValueError("compute wait must be a finite non-negative number")
        self.wait_seconds = float(wait_seconds)
        self._slot = threading.BoundedSemaphore(value=1)

    @contextmanager
    def acquire(self) -> Iterator[None]:
        if not self._slot.acquire(timeout=self.wait_seconds):
            raise ServerBusy(self.wait_seconds)
        try:
            yield
        finally:
            self._slot.release()


def configured_compute_wait_seconds(value: float | None) -> float:
    if value is not None:
        return value
    configured = os.environ.get(COMPUTE_WAIT_ENV)
    if configured is None:
        return DEFAULT_COMPUTE_WAIT_SECONDS
    try:
        return float(configured)
    except ValueError as error:
        raise ValueError(f"{COMPUTE_WAIT_ENV} must be a number") from error
