"""``advise_phonon()``/``check_phonon()``/``generate_phonon()``: the
``phonon``, ``relax-phonon`` and ``vc-relax-phonon`` tasks (#215).

**One service, three first steps.** The tasks differ only in their first
pw.x step, which keeps its own purpose (``plan.expand_task``): an scf for
``phonon``, a fixed-cell relax for ``relax-phonon`` and a vc-relax for
``vc-relax-phonon``, whose save ph.x reads in place of a separate scf. Then
``d3hess.x`` for DFT-D3, ``ph.x`` on a q-point mesh, ``q2r.x``, and
``matdyn.x`` for the phonon DOS and for the dispersion along the band task's
path run in the same job, on one ``SharedContext``. ``TASK_PHASES`` binds
each task's ``task`` to ``advise_phonon``; every other function reads it off
the advice.

**The first step is advised as any pw.x step**, by ``advise_steps`` under
``phonon_step_protocol`` (``_step_protocol.py``): its k-mesh is constrained
by the ph step's q-mesh, the job runs a timer in place of any
``max_seconds``, and a relaxation converges to the phonon tasks' force
threshold. ``phonon_steps_advice`` (``_phonon_steps.py``) decides the rest on
that step's advice: the relax record, the FFT grid ph.x accepts, the
q-mesh, and the ph, q2r, phonon_dos and dispersion steps' records.

**Each step gets its own overrides** (#154). ``set_overrides`` routes a
phonon task's request to its steps: the pw.x settings to the first step,
which is the task's only pw.x step, so no setting lands on two steps; the
q-mesh and linear-response settings to ``ph``, the acoustic sum rule to
``q2r``, the DOS spacing to ``phonon_dos`` and the path spacing to
``dispersion``. ``steps.scf.*`` is an unknown step in the relaxation tasks.

**The gate** is ``check()`` on the first step, with its purpose and relax
record, followed by ``checks.with_phonon_findings``, which adds the phonon
steps' ``Blocked`` records and the phonon tasks' own refusals.

**Generation** writes the first step as ``generate()`` does for its purpose,
with the grid ph.x accepts as nr1-nr3 where ph.x would refuse pw.x's own,
and, with DFT-D3, ``dftd3_threebody = .false.``: d3hess.x's Hessian has
two-body terms only, so the energy, the forces and the relaxed geometry use
the same D3. The same fact, ``vdw.use_vdw``, inserts the d3hess step, so a
two-body first step and d3hess.x always go together.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from pymatgen.core import Structure

from goldilocks_core.assets.store import AssetStore
from goldilocks_core.bundle import BundleInput, StructureIdentity
from goldilocks_core.checks import CheckReport, with_phonon_findings
from goldilocks_core.generation.quantum_espresso.phonon import write_qe_phonon
from goldilocks_core.inputs.hpc import HpcProfile
from goldilocks_core.plan import expand_task
from goldilocks_core.resolution import FieldState, Warning
from goldilocks_core.service._advice import Advice, RecordTiers, RunOverrides
from goldilocks_core.service._bundle import (
    assemble_bundle_input,
    render_submission,
    request_identity,
)
from goldilocks_core.service._generate import AdviceIncomplete, generate
from goldilocks_core.service._phonon_steps import (
    PhononStepsAdvice,
    phonon_step_settings,
    phonon_steps_advice,
)
from goldilocks_core.service._pipeline import advise_steps, check
from goldilocks_core.service._step_protocol import phonon_step_protocol
from goldilocks_core.steps import SharedContext, Step, default_shared_context

PhononTask = Literal["phonon", "relax-phonon", "vc-relax-phonon"]


@dataclass(frozen=True, slots=True)
class PhononAdvice:
    """A phonon task's advice: ``first``, its first pw.x step's ``Advice``,
    and ``steps``, the records decided on it (``PhononStepsAdvice``).
    ``routing`` is the request's routing notices
    (``RunOverrides.warnings``)."""

    task: PhononTask
    first: Advice
    steps: PhononStepsAdvice
    routing: tuple[Warning, ...]

    @property
    def first_step(self) -> Literal["scf", "relax", "vc-relax"]:
        """The purpose of the task's first pw.x step: ``scf``, ``relax`` or
        ``vc-relax``."""
        return expand_task(self.task)[0].purpose

    def tiers(self) -> RecordTiers:
        """``first``'s records, its step named ``first_step`` and holding the
        relax record of a relaxation and ``fft_grid`` too, then the ph step's
        ``q_sampling`` and ``phonon``, the q2r step's ``q2r``, the phonon_dos
        step's ``phonon_dos`` and the dispersion step's ``k_path``. d3hess.x
        has no records."""
        tiers = self.first.tiers(self.first_step).with_records(
            self.first_step, self.steps.first_step_records()
        )
        for name, records in self.steps.step_records().items():
            tiers = tiers.with_records(name, records)
        return tiers

    def records(self) -> dict[str, FieldState[object]]:
        return self.tiers().records()

    def warnings(self) -> list[dict[str, object]]:
        """Every record's warnings, then the routing notices, tagged with
        the record ``overrides``."""
        return self.tiers().warnings() + [
            {**notice.model_dump(), "record": "overrides"} for notice in self.routing
        ]


def advise_phonon(
    structure: Structure,
    *,
    task: PhononTask,
    code: str = "quantum_espresso",
    hpc: HpcProfile,
    overrides: RunOverrides | None = None,
    store: AssetStore | None = None,
    fetch_missing: bool = False,
) -> PhononAdvice:
    """Diagnosis for every step of ``task``, under the same contract as
    ``advise()``: an undecided field degrades, a fault raises. The first
    step is advised under ``phonon_step_protocol`` with the q request of the
    ph step's overrides, then the phonon steps on its advice (module
    docstring)."""
    overrides = overrides or RunOverrides()
    purposes = tuple(step.purpose for step in expand_task(task))
    first_step = purposes[0]
    steps = overrides.for_steps(purposes)
    protocol = phonon_step_protocol(first_step, steps["ph"].ph.q_sampling)
    first = advise_steps(
        structure,
        code=code,
        hpc=hpc,
        overrides=overrides,
        steps={first_step: steps[first_step]},
        protocols={first_step: protocol},
        store=store,
        fetch_missing=fetch_missing,
    )[first_step]
    return PhononAdvice(
        task=task,
        first=first,
        steps=phonon_steps_advice(first_step, first, steps, protocol.relax),
        routing=overrides.warnings,
    )


def check_phonon(advice: PhononAdvice) -> CheckReport:
    """``advise_phonon()``/``generate_phonon()``'s boundary: ``check()`` on
    the first step, with its purpose and relax record, then the phonon
    tasks' rules on the first step's records, its is_metal fact included,
    and the phonon steps' (``checks.with_phonon_findings``), which keeps one
    finding per root cause."""
    first = advice.first
    steps = advice.steps
    return with_phonon_findings(
        check(first, purpose=advice.first_step, relax=steps.relax),
        *steps.field_states(),
        purpose=advice.first_step,
        occupations=first.step.kpoints.occupations,
        is_metal=first.analysis.is_metal,
        electron_count=first.system.electron_count,
        magnetic=first.system.magnetic,
        boundary=first.system.boundary,
        relax=steps.relax,
        hubbard=first.system.hubbard,
        q_sampling=steps.q_sampling,
        fft_grid=steps.fft_grid,
    )


def generate_phonon(
    advice: PhononAdvice, report: CheckReport, *, ctx: SharedContext | None = None
) -> tuple[Step, ...]:
    """Delivery: the first pw.x step, then d3hess.x for DFT-D3, ph.x, q2r.x
    and matdyn.x for the phonon DOS and the dispersion, on one
    ``SharedContext`` (module docstring). Raises
    ``AdviceIncomplete`` when ``report`` is not ``ok``; ``report`` holds every
    step's findings (``check_phonon``), so the inner ``generate()`` call is
    passed an ``ok`` report."""
    if not report.ok:
        raise AdviceIncomplete(report)
    shared_ctx = ctx or default_shared_context()
    steps = advice.steps
    d3 = advice.first.system.vdw.value.use_vdw
    first = generate(
        advice.first,
        CheckReport(),
        ctx=shared_ctx,
        purpose=advice.first_step,
        relax=None if steps.relax is None else steps.relax.value,
        fft_grid=steps.fft_grid.value.written,
        dftd3_threebody=False if d3 else None,
    )
    phonon = write_qe_phonon(
        *phonon_step_settings(steps, advice.first), shared_ctx, d3hess=d3
    )
    return first + tuple(phonon)


def render_submission_phonon(
    advice: PhononAdvice,
    hpc: HpcProfile,
    code: str,
    steps: tuple[Step, ...],
) -> str:
    """One script for every step of a phonon task, from the job its first
    step holds: the job timer and the resume switch follow from that job and
    from what the steps declare (``submission/slurm.py``)."""
    return render_submission(advice.first, hpc, code, steps)


def to_bundle_input_phonon(
    advice: PhononAdvice,
    steps: tuple[Step, ...],
    submission_script: str,
    ctx: SharedContext,
    *,
    code: str,
    hpc: HpcProfile,
    assignments: Mapping[str, object],
    source: StructureIdentity,
) -> BundleInput:
    """``service/_bundle.py``'s ``to_bundle_input``, for a phonon task: the
    pseudopotential files and their licence come from the first step's
    system advice, and the request names ``advice.task``."""
    return assemble_bundle_input(
        advice.first.system.pseudo,
        steps,
        submission_script,
        ctx,
        advice.records(),
        advice.warnings(),
        request_identity(
            advice.task,
            code=code,
            hpc=hpc,
            assignments=assignments,
            source=source,
        ),
    )
