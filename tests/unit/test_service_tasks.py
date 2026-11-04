"""``service.TASK_PHASES``: the one table every transport looks a task's
service functions up in (#118)."""

from __future__ import annotations

from typing import get_args

import pytest

from goldilocks_core.service import (
    TASK_PHASES,
    advise_phonon,
    check_phonon,
    generate_phonon,
    render_submission_phonon,
    to_bundle_input_phonon,
)
from goldilocks_core.types import CalcTask


def test_every_task_has_exactly_one_row() -> None:
    """The CLI, HTTP and MCP ``explain``/``run`` dispatch through this
    table, so a task without a row raises ``KeyError`` instead of running
    another task's functions, as their old ``else`` branches ran scf."""
    assert TASK_PHASES.keys() == set(get_args(CalcTask))


@pytest.mark.parametrize("task", ["phonon", "relax-phonon", "vc-relax-phonon"])
def test_each_phonon_row_binds_its_own_task(task: CalcTask) -> None:
    """#215: the three phonon tasks share one service and differ only in the
    task their row binds, which decides the first pw.x step."""
    phases = TASK_PHASES[task]

    assert (phases.advise.func, phases.advise.keywords) == (
        advise_phonon,
        {"task": task},
    )
    assert (
        phases.check,
        phases.generate,
        phases.render_submission,
        phases.to_bundle_input,
    ) == (
        check_phonon,
        generate_phonon,
        render_submission_phonon,
        to_bundle_input_phonon,
    )
