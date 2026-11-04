"""``PlannedStep``/``expand_task``: one task becomes an ordered step
sequence.

New in v2 (v2 epic 9, #9). ``steps.py``'s own docstring named this gap
and deferred it deliberately: "the design doc's layer 1 (``PlannedStep``
+ ``expand_task``, goldilocks-core-design.md:1072-1083) exists to turn
one task into an *ordered sequence* of steps (e.g. ``dos -> [scf, nscf,
dos]``)... add ``PlannedStep``/``plan.py`` once a second task actually
needs step sequencing." ``dos`` (``types.CalcTask``, this epic) is that
second task.

Lives top-level next to ``steps.py``/``step_settings.py``, same
reasoning as both of those modules' own docstrings: used across
multiple packages (``service/``, ``generation/``), no single owner.

**Scope, per this epic's own acceptance bar** (goldilocks-implementation
-plan.md's five-scenario table, scenario 5 -- "DOS multi-step"): prove
the type-level split and a real multi-step path actually work end to
end, not full DOS science. ``expand_task`` only decides *how many steps,
in what order, running what program* -- never a scientific value (that
stays ``advisors/``'s job, per every other module in this codebase).
Its table holds one row per ``types.CalcTask`` (#118), so a task without
a row raises ``KeyError`` instead of running another task's steps.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from goldilocks_core.types import CalcTask

SCF_LIKE_PURPOSES = frozenset({"scf", "relax", "vc-relax"})
"""``PlannedStep.purpose``s whose ``pw.x`` run has its own SCF loop:
``relax``/``vc-relax`` re-run it at every ionic step, while ``nscf``
and ``bands`` read an already-converged density. ``checks.py`` scopes its
fixed-occupations rules to these, and ``advisors/size.py`` counts
several passes over their k-points in a step's workload."""


@dataclass(frozen=True, slots=True)
class PlannedStep:
    """One step in a task's sequence, before any settings are resolved
    for it -- just *what* runs and *why* (``purpose``), not yet *how*.
    ``purpose`` is deliberately not ``types.CalcTask``: a multi-step task
    like ``dos`` has steps with purposes (``"scf"``, ``"nscf"``) that are
    not tasks in their own right, only ever ingredients of one. ``relax``/
    ``vc-relax`` (v2 epic 10, #10) *are* both a task and their own single
    step's purpose -- one ``pw.x`` run does the whole task. A ``bands``
    step is ``pw.x`` with ``calculation='bands'`` and ``bands_x`` the
    ``bands.x`` run after it (#118). A phonon task's first step keeps its
    pw.x purpose, ``scf``, ``relax`` or ``vc-relax``, and ``ph``, ``q2r``,
    ``phonon_dos`` and ``dispersion`` are the ph.x run on its save, q2r.x on
    ph.x's dynamical matrices and matdyn.x on q2r.x's force constants, once
    for the phonon DOS and once along the band task's path (#215).
    d3hess.x, which runs before ph.x for DFT-D3, has no row: the writer
    inserts it (``generation/quantum_espresso/phonon.py``), as it inserts
    one bands.x step per spin channel."""

    purpose: Literal[
        "scf",
        "nscf",
        "dos",
        "bands",
        "bands_x",
        "relax",
        "vc-relax",
        "ph",
        "q2r",
        "phonon_dos",
        "dispersion",
    ]
    program: Literal["pw.x", "dos.x", "bands.x", "ph.x", "q2r.x", "matdyn.x"]


_TASK_STEPS: Mapping[CalcTask, tuple[PlannedStep, ...]] = {
    "scf_single_point": (PlannedStep(purpose="scf", program="pw.x"),),
    "dos": (
        PlannedStep(purpose="scf", program="pw.x"),
        PlannedStep(purpose="nscf", program="pw.x"),
        PlannedStep(purpose="dos", program="dos.x"),
    ),
    "band": (
        PlannedStep(purpose="scf", program="pw.x"),
        PlannedStep(purpose="bands", program="pw.x"),
        PlannedStep(purpose="bands_x", program="bands.x"),
    ),
    "relax": (PlannedStep(purpose="relax", program="pw.x"),),
    "vc-relax": (PlannedStep(purpose="vc-relax", program="pw.x"),),
    "phonon": (
        PlannedStep(purpose="scf", program="pw.x"),
        PlannedStep(purpose="ph", program="ph.x"),
        PlannedStep(purpose="q2r", program="q2r.x"),
        PlannedStep(purpose="phonon_dos", program="matdyn.x"),
        PlannedStep(purpose="dispersion", program="matdyn.x"),
    ),
    "relax-phonon": (
        PlannedStep(purpose="relax", program="pw.x"),
        PlannedStep(purpose="ph", program="ph.x"),
        PlannedStep(purpose="q2r", program="q2r.x"),
        PlannedStep(purpose="phonon_dos", program="matdyn.x"),
        PlannedStep(purpose="dispersion", program="matdyn.x"),
    ),
    "vc-relax-phonon": (
        PlannedStep(purpose="vc-relax", program="pw.x"),
        PlannedStep(purpose="ph", program="ph.x"),
        PlannedStep(purpose="q2r", program="q2r.x"),
        PlannedStep(purpose="phonon_dos", program="matdyn.x"),
        PlannedStep(purpose="dispersion", program="matdyn.x"),
    ),
}


def expand_task(task: CalcTask) -> tuple[PlannedStep, ...]:
    """The steps ``task`` runs, in order: its row of the table above. Their
    purposes are also the step names a request scopes a setting to
    (``steps.<purpose>.<key>``, ``set_overrides``, #154). A task from a
    request is checked against ``types.CalcTask`` before it gets here
    (``set_overrides.build_overrides`` refuses any other); a task without
    a row raises ``KeyError``."""
    return _TASK_STEPS[task]
