"""Generate-stage dispatch-table tests."""

from __future__ import annotations

from goldilocks_core.generation import available_codes, available_tasks


def test_available_codes_and_tasks_reflect_registered_writers() -> None:
    """The public code/task listings mirror the dispatch table defaults."""
    assert available_codes() == ("quantum_espresso",)
    assert available_tasks() == ("scf_single_point",)
