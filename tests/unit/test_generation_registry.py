from __future__ import annotations

import pytest

from goldilocks_core.generation.errors import GenerationError
from goldilocks_core.generation.registry import (
    available_codes,
    available_tasks,
    writer_for,
)


def test_available_codes_and_tasks_reflect_registered_writers() -> None:
    assert available_codes() == ("quantum_espresso",)
    assert available_tasks() == ("scf_single_point",)


def test_writer_for_rejects_unregistered_code_and_lists_available_writers() -> None:
    with pytest.raises(GenerationError, match="No input writer registered") as exc:
        writer_for("vasp", "scf_single_point")
    message = str(exc.value)
    assert "Available:" in message
    assert "quantum_espresso/scf_single_point" in message


def test_writer_for_rejects_unregistered_task_and_lists_available_writers() -> None:
    with pytest.raises(GenerationError, match="No input writer registered") as exc:
        writer_for("quantum_espresso", "relax")
    message = str(exc.value)
    assert "Available:" in message
    assert "quantum_espresso/scf_single_point" in message
