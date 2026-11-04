"""``TASK_PHASES``: each task's service functions, keyed by
``types.CalcTask`` (#118).

``explain`` and ``run`` on every transport (``cli/_explain.py``,
``cli/_run.py``, ``server/_handlers.py``) look a task's functions up here:
``explain`` calls ``advise`` and ``check``, ``run`` all five in order. A
task has exactly one row, so one without a row raises ``KeyError`` instead
of running another task's functions.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any

from goldilocks_core.service._band import (
    advise_band,
    check_band,
    generate_band,
    render_submission_band,
    to_bundle_input_band,
)
from goldilocks_core.service._bundle import render_submission, to_bundle_input
from goldilocks_core.service._dos import (
    advise_dos,
    check_dos,
    generate_dos,
    render_submission_dos,
    to_bundle_input_dos,
)
from goldilocks_core.service._generate import generate
from goldilocks_core.service._phonon import (
    advise_phonon,
    check_phonon,
    generate_phonon,
    render_submission_phonon,
    to_bundle_input_phonon,
)
from goldilocks_core.service._pipeline import advise, check
from goldilocks_core.service._relax import (
    advise_relax,
    check_relax,
    generate_relax,
    render_submission_relax,
    to_bundle_input_relax,
)
from goldilocks_core.types import CalcTask


@dataclass(frozen=True, slots=True)
class TaskPhases:
    """One task's service functions, in the order ``run`` calls them. Every
    function after ``advise`` takes the advice that task's ``advise``
    returns (``Advice``, ``DosAdvice``, ``BandAdvice``, ``RelaxAdvice`` or
    ``PhononAdvice``):

    - ``advise(structure, *, code, hpc, overrides, store, fetch_missing)``:
      the advice;
    - ``check(advice)``: the gate's ``checks.CheckReport``;
    - ``generate(advice, report, *, ctx)``: the rendered ``Step``s, raising
      ``AdviceIncomplete`` when ``report`` is not ok;
    - ``render_submission(advice, hpc, code, steps)``: the submission
      script;
    - ``to_bundle_input(advice, steps, script, ctx, *, code, hpc,
      assignments, source)``: the ``bundle.BundleInput``."""

    advise: Callable[..., Any]
    check: Callable[..., Any]
    generate: Callable[..., Any]
    render_submission: Callable[..., str]
    to_bundle_input: Callable[..., Any]


TASK_PHASES: Mapping[CalcTask, TaskPhases] = {
    "scf_single_point": TaskPhases(
        advise, check, generate, render_submission, to_bundle_input
    ),
    "dos": TaskPhases(
        advise_dos, check_dos, generate_dos, render_submission_dos, to_bundle_input_dos
    ),
    "band": TaskPhases(
        advise_band,
        check_band,
        generate_band,
        render_submission_band,
        to_bundle_input_band,
    ),
    "relax": TaskPhases(
        partial(advise_relax, calculation="relax"),
        check_relax,
        generate_relax,
        render_submission_relax,
        to_bundle_input_relax,
    ),
    "vc-relax": TaskPhases(
        partial(advise_relax, calculation="vc-relax"),
        check_relax,
        generate_relax,
        render_submission_relax,
        to_bundle_input_relax,
    ),
    "phonon": TaskPhases(
        partial(advise_phonon, task="phonon"),
        check_phonon,
        generate_phonon,
        render_submission_phonon,
        to_bundle_input_phonon,
    ),
    "relax-phonon": TaskPhases(
        partial(advise_phonon, task="relax-phonon"),
        check_phonon,
        generate_phonon,
        render_submission_phonon,
        to_bundle_input_phonon,
    ),
    "vc-relax-phonon": TaskPhases(
        partial(advise_phonon, task="vc-relax-phonon"),
        check_phonon,
        generate_phonon,
        render_submission_phonon,
        to_bundle_input_phonon,
    ),
}
"""One row per ``types.CalcTask``. The ``relax`` and ``vc-relax`` rows bind
``advise_relax``'s ``calculation`` to their own task, and the three phonon
rows ``advise_phonon``'s ``task``, which decides their first pw.x step."""
