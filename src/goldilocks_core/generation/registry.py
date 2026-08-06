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

_WRITERS: dict[tuple[CodeName, CalcTask], Writer] = {
    ("quantum_espresso", "scf_single_point"): write_qe_scf,
}


def register_writer(code: CodeName, task: CalcTask, writer: Writer) -> None:
    """Register or replace the writer for one ``(code, task)`` dispatch key."""
    _WRITERS[(code, task)] = writer


def writer_for(code: CodeName, task: CalcTask) -> Writer:
    """Return the writer registered for ``(code, task)``.

    Raises:
        ValueError: If no writer is registered for the requested pair.
    """
    try:
        return _WRITERS[(code, task)]
    except KeyError:
        available = ", ".join(f"{c}/{t}" for c, t in sorted(_WRITERS))
        raise ValueError(
            f"No input writer registered for code={code!r}, task={task!r}. "
            f"Available: {available}"
        ) from None


def available_codes() -> tuple[CodeName, ...]:
    """Return the deduplicated, sorted codes with registered writers."""
    return tuple(sorted({code for code, _ in _WRITERS}))


def available_tasks() -> tuple[CalcTask, ...]:
    """Return the deduplicated, sorted tasks with registered writers."""
    return tuple(sorted({task for _, task in _WRITERS}))


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
