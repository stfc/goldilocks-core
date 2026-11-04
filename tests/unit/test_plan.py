from __future__ import annotations

from typing import get_args

import pytest

from goldilocks_core.plan import PlannedStep, expand_task
from goldilocks_core.types import CalcTask


def test_scf_single_point_expands_to_exactly_one_step() -> None:
    steps = expand_task("scf_single_point")

    assert steps == (PlannedStep(purpose="scf", program="pw.x"),)


def test_dos_expands_to_scf_then_nscf_then_dos_in_order() -> None:
    steps = expand_task("dos")

    assert steps == (
        PlannedStep(purpose="scf", program="pw.x"),
        PlannedStep(purpose="nscf", program="pw.x"),
        PlannedStep(purpose="dos", program="dos.x"),
    )


def test_band_expands_to_scf_then_bands_then_bands_x_in_order() -> None:
    """#118: pw.x's bands run reads the scf's save, and bands.x the bands
    run's."""
    steps = expand_task("band")

    assert steps == (
        PlannedStep(purpose="scf", program="pw.x"),
        PlannedStep(purpose="bands", program="pw.x"),
        PlannedStep(purpose="bands_x", program="bands.x"),
    )


def test_relax_expands_to_exactly_one_step() -> None:
    steps = expand_task("relax")

    assert steps == (PlannedStep(purpose="relax", program="pw.x"),)


def test_vc_relax_expands_to_exactly_one_step() -> None:
    steps = expand_task("vc-relax")

    assert steps == (PlannedStep(purpose="vc-relax", program="pw.x"),)


@pytest.mark.parametrize(
    ("task", "first_step"),
    [("phonon", "scf"), ("relax-phonon", "relax"), ("vc-relax-phonon", "vc-relax")],
)
def test_a_phonon_task_expands_to_its_first_pw_x_step_then_ph_q2r_and_matdyn(
    task: CalcTask, first_step: str
) -> None:
    """#215: ph.x reads the save of the first pw.x step, which keeps its own
    purpose, q2r.x ph.x's dynamical matrices and matdyn.x q2r.x's force
    constants twice, for the phonon DOS and along the band path. d3hess.x has
    no row: the writer inserts it for DFT-D3."""
    steps = expand_task(task)

    assert steps == (
        PlannedStep(purpose=first_step, program="pw.x"),
        PlannedStep(purpose="ph", program="ph.x"),
        PlannedStep(purpose="q2r", program="q2r.x"),
        PlannedStep(purpose="phonon_dos", program="matdyn.x"),
        PlannedStep(purpose="dispersion", program="matdyn.x"),
    )


def test_every_task_expands_to_steps_with_distinct_purposes() -> None:
    """A request scopes a setting to a step by its purpose
    (``steps.<purpose>.<key>``), so no two steps of one task share one."""
    for task in get_args(CalcTask):
        purposes = [step.purpose for step in expand_task(task)]

        assert purposes, task
        assert len(set(purposes)) == len(purposes), task


def test_a_task_without_a_row_has_no_steps_to_fall_into() -> None:
    """#118: the last branch used to return dos's steps for any task the
    branches before it did not name."""
    with pytest.raises(KeyError):
        expand_task("no_such_task")  # type: ignore[arg-type]
