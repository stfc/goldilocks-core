"""Table-driven dispatch from ``(code, task)`` to a Generate-stage writer."""

from __future__ import annotations

from typing import Callable

from pymatgen.core import Structure

from goldilocks_core.contracts import (
    CalcTask,
    CalculationIntent,
    CodeName,
    GeneratedFile,
    ParameterAdvice,
    SelectionRecord,
)
from goldilocks_core.generation.qe.scf import write_qe_scf

Writer = Callable[
    [Structure, CalculationIntent, ParameterAdvice, SelectionRecord],
    tuple[GeneratedFile, ...],
]
"""Generate-stage writer signature.

Each writer renders the input text for one ``(code, task)`` pair and owns the
``GeneratedFile`` records it returns, including their relative paths.
"""

# Static dispatch table: one (code, task, writer) triple per supported pair.
_WRITERS: tuple[tuple[CodeName, CalcTask, Writer], ...] = (
    ("quantum_espresso", "scf_single_point", write_qe_scf),
)


def writer_for(code: CodeName, task: CalcTask) -> Writer:
    """Return the writer for ``(code, task)``.

    Raises:
        ValueError: If no writer is registered for the requested pair.
    """
    for entry_code, entry_task, writer in _WRITERS:
        if entry_code == code and entry_task == task:
            return writer
    pairs = sorted({(code, task) for code, task, _ in _WRITERS})
    available = ", ".join(f"{code}/{task}" for code, task in pairs)
    raise ValueError(
        f"No input writer registered for code={code!r}, task={task!r}. "
        f"Available: {available}"
    )


def available_codes() -> tuple[CodeName, ...]:
    """Return the deduplicated, sorted codes with registered writers."""
    return tuple(sorted({code for code, _, _ in _WRITERS}))


def available_tasks() -> tuple[CalcTask, ...]:
    """Return the deduplicated, sorted tasks with registered writers."""
    return tuple(sorted({task for _, task, _ in _WRITERS}))


def generate_inputs(
    structure: Structure,
    intent: CalculationIntent,
    advice: ParameterAdvice,
    selection: SelectionRecord,
) -> tuple[GeneratedFile, ...]:
    """Dispatch to the writer registered for ``intent.code``/``intent.task``.

    Args:
        structure: Loaded structure for the calculation.
        intent: Target code and task to generate.
        advice: Completed parameter advice.
        selection: Concrete k-points, pseudopotentials, and cutoffs.

    Returns:
        Generated input files for the requested code/task.

    Raises:
        ValueError: If no writer is registered for the requested code/task,
            or if the target writer rejects its inputs.
    """
    return writer_for(intent.code, intent.task)(structure, intent, advice, selection)
