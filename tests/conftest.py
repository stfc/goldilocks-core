from __future__ import annotations

import pytest

from goldilocks_core import reset_default_runtime


@pytest.fixture(autouse=True)
def isolate_process_default_runtime():
    """Prevent process-level model resources from leaking between tests."""
    reset_default_runtime()
    yield
    reset_default_runtime()
