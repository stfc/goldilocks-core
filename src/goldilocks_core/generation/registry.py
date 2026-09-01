from __future__ import annotations

from typing import Callable

from pymatgen.core import Structure

from goldilocks_core.contracts import (
    CalcTask,
    CalculationIntent,
    CodeName,
    GeneratedFile,
    KPointSelection,
    ParameterAdvice,
    SelectionRecord,
)
from goldilocks_core.generation.errors import GenerationError
from goldilocks_core.generation.qe.scf import write_qe_scf

Writer = Callable[
    [Structure, CalculationIntent, ParameterAdvice, SelectionRecord, KPointSelection],
    tuple[GeneratedFile, ...],
]

_WRITERS: tuple[tuple[CodeName, CalcTask, Writer], ...] = (
    ("quantum_espresso", "scf_single_point", write_qe_scf),
)


def writer_for(code: CodeName, task: CalcTask) -> Writer:
    for entry_code, entry_task, writer in _WRITERS:
        if entry_code == code and entry_task == task:
            return writer
    pairs = sorted({(code, task) for code, task, _ in _WRITERS})
    available = ", ".join(f"{code}/{task}" for code, task in pairs)
    raise GenerationError(
        f"No input writer registered for code={code!r}, task={task!r}. "
        f"Available: {available}"
    )


def available_codes() -> tuple[CodeName, ...]:
    return tuple(sorted({code for code, _, _ in _WRITERS}))


def available_tasks() -> tuple[CalcTask, ...]:
    return tuple(sorted({task for _, task, _ in _WRITERS}))


def generate_inputs(
    structure: Structure,
    intent: CalculationIntent,
    advice: ParameterAdvice,
    selection: SelectionRecord,
    k_points: KPointSelection,
) -> tuple[GeneratedFile, ...]:
    return writer_for(intent.code, intent.task)(
        structure, intent, advice, selection, k_points
    )
