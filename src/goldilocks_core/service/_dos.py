"""``advise_dos()``/``check_dos()``/``generate_dos()``: the ``dos`` task's
multi-step path (v2 epic 9, #9) -- goldilocks-implementation-plan.md's
five-scenario table, scenario 5 ("DOS multi-step"), and the design doc's
own admission that step-sequencing has never once been exercised before
this epic.

**One task, one ``Advice`` per ``pw.x`` step.** ``plan.py``'s own
``expand_task`` already says how many steps a task needs and what
program each runs; nothing about *how* a single ``pw.x`` step's own
settings get resolved changes between an scf task and dos's scf/nscf
steps, so ``advise_dos`` asks ``advise_steps`` for both steps at once.
That runs analysis and system advice once, and sizes one job for the task
(#169): the three steps share one allocation, so its ``#SBATCH`` request
covers the larger ``pw.x`` step, and the scf and nscf each get their own
``max_seconds`` share of the walltime (pw.x counts it from its own
start). ``dos.x`` has no ``max_seconds`` and runs in the remainder.

**Each step gets its own overrides** (#154). ``set_overrides`` routes a
request for the dos task to its scf, nscf and dos steps: a setting given
without a step lands on every step it applies to (``k_grid`` on both pw.x
steps, with a notice ``DosAdvice.warnings()`` publishes), and
``steps.nscf.k_grid`` on the nscf step only. The dos step's overrides are
``dos.x``'s own settings (``advisors/dos.py``).

**The nscf protocol is its own tier** (#174). The nscf step also gets
``DOS_NSCF_PROTOCOL`` (``_step_protocol.py``: aiida-quantumespresso's
``pdos.yaml``, a denser k-mesh and ``tetrahedra_opt``), which ranks below
the request and above the ML tier for that step only. A request value
replaces the protocol field by field and reads ``human``; the protocol's
own values read ``heuristic``, naming the protocol in ``source_note``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pymatgen.core import Structure

from goldilocks_core.advisors.dos import DosDecision, dos_settings
from goldilocks_core.assets.store import AssetStore
from goldilocks_core.bundle import BundleInput, StructureIdentity
from goldilocks_core.checks import CheckReport, collect_blocked
from goldilocks_core.generation.quantum_espresso.dos import write_qe_dos
from goldilocks_core.inputs.hpc import HpcProfile
from goldilocks_core.resolution import FieldState, Warning
from goldilocks_core.service._advice import Advice, RecordTiers, RunOverrides
from goldilocks_core.service._bundle import assemble_bundle_input, request_identity
from goldilocks_core.service._generate import AdviceIncomplete, generate
from goldilocks_core.service._pipeline import advise_steps, check
from goldilocks_core.service._step_protocol import DOS_NSCF_PROTOCOL
from goldilocks_core.step_settings import DosSettings
from goldilocks_core.steps import SharedContext, Step, default_shared_context
from goldilocks_core.submission.slurm import render_slurm_script


@dataclass(frozen=True, slots=True)
class DosAdvice:
    """``routing`` is the request's routing notices
    (``RunOverrides.warnings``)."""

    scf: Advice
    nscf: Advice
    dos: FieldState[DosDecision]
    routing: tuple[Warning, ...]

    def field_states(self) -> tuple[FieldState[object], ...]:
        return self.scf.field_states() + self.nscf.field_states() + (self.dos,)

    def tiers(self) -> RecordTiers:
        """``scf``'s records unprefixed (system-level fields --
        ``functional``/``cutoffs``/``pseudopotentials``/``magnetic``/
        etc. -- and the task's one ``job`` are the same objects in
        ``scf`` and ``nscf``, ``advise_steps``), ``nscf``'s own per-step
        fields under an ``nscf_`` prefix (v2 epic 9, #9, #28's
        delivery-layer routing -- the first caller that ever needs to
        tell the two steps' k-sampling/occupations/nbnd/convergence/
        parallelisation apart), plus ``dos`` itself, each step's under its
        purpose."""
        nscf = {
            f"nscf_{name}": state
            for name, state in self.nscf.step.records().items()
            if name != "job"
        }
        return (
            self.scf.tiers("scf")
            .with_records("nscf", nscf)
            .with_records("dos", {"dos": self.dos})
        )

    def records(self) -> dict[str, FieldState[object]]:
        return self.tiers().records()

    def warnings(self) -> list[dict[str, object]]:
        """Every record's warnings, then the routing notices, tagged with
        the record ``overrides``."""
        return self.tiers().warnings() + [
            {**notice.model_dump(), "record": "overrides"} for notice in self.routing
        ]


def advise_dos(
    structure: Structure,
    *,
    code: str = "quantum_espresso",
    hpc: HpcProfile,
    overrides: RunOverrides | None = None,
    store: AssetStore | None = None,
    fetch_missing: bool = False,
) -> DosAdvice:
    """Diagnosis for all three of dos's steps, under the same contract as
    ``advise()``: an undecided field degrades, a fault raises. Each step
    gets its own overrides; the nscf step also gets the dos protocol
    (module docstring)."""
    overrides = overrides or RunOverrides()
    steps = overrides.for_steps(("scf", "nscf", "dos"))
    advice = advise_steps(
        structure,
        code=code,
        hpc=hpc,
        overrides=overrides,
        steps={"scf": steps["scf"], "nscf": steps["nscf"]},
        protocols={"nscf": DOS_NSCF_PROTOCOL},
        store=store,
        fetch_missing=fetch_missing,
    )
    nscf = advice["nscf"]
    dos_overrides = steps["dos"].dos
    dos = dos_settings(
        nscf.step.kpoints.occupations, dos_overrides.dos, dos_overrides.dos_llm
    )
    return DosAdvice(scf=advice["scf"], nscf=nscf, dos=dos, routing=overrides.warnings)


def check_dos(advice: DosAdvice) -> CheckReport:
    """``advise_dos()``/``generate_dos()``'s boundary -- folds all three
    steps' findings into one report, which keeps a root cause the steps
    share once. The nscf pass is checked with ``purpose="nscf"``
    (``checks.py``'s scf-only named rule does not apply to it, per this
    module's own docstring)."""
    scf_report = check(advice.scf, purpose="scf")
    nscf_report = check(advice.nscf, purpose="nscf")
    dos_blocking = collect_blocked(advice.dos)
    blocking = scf_report.blocking + nscf_report.blocking + dos_blocking
    return CheckReport(blocking=blocking)


def generate_dos(
    advice: DosAdvice, report: CheckReport, *, ctx: SharedContext | None = None
) -> tuple[Step, ...]:
    """Delivery: three real ``Step``s (scf, nscf, dos), sharing one
    ``SharedContext`` -- goldilocks-core-design.md's own "phonon's 4
    steps / bands' 3 steps must share one prefix + outdir" requirement,
    exercised here for the first time. Raises ``AdviceIncomplete`` when
    ``report`` is not ``ok``, same contract as the single-step
    ``generate()`` -- checked once, directly, rather than re-derived per
    step: ``report.blocking`` holds every step's findings (``check_dos``),
    so if the whole is empty every part is too, and each inner
    ``generate()`` call below is passed a trivially-``ok`` report rather
    than recomputing one."""
    if not report.ok:
        raise AdviceIncomplete(report)
    shared_ctx = ctx or default_shared_context()
    ok_report = CheckReport()
    scf_steps = generate(advice.scf, ok_report, ctx=shared_ctx)
    nscf_steps = generate(advice.nscf, ok_report, ctx=shared_ctx, purpose="nscf")
    dos_settings_value = DosSettings(
        emin=advice.dos.value.emin,
        emax=advice.dos.value.emax,
        delta_e=advice.dos.value.delta_e,
        broadening=advice.dos.value.broadening,
        ngauss=advice.dos.value.ngauss,
    )
    dos_steps = write_qe_dos(dos_settings_value, shared_ctx)
    return scf_steps + nscf_steps + tuple(dos_steps)


def render_submission_dos(
    advice: DosAdvice,
    hpc: HpcProfile,
    code: str,
    steps: tuple[Step, ...],
) -> str:
    """One shared script for a ``dos`` task's three steps (v2 epic 9,
    #9, #28's delivery-layer routing), from the task's one job: ``scf``
    and ``nscf`` hold the same ``JobDecision``, sized over both ``pw.x``
    steps (#169)."""
    return render_slurm_script(
        hpc, advice.scf.step.resources.job.value, code, list(steps)
    )


def to_bundle_input_dos(
    advice: DosAdvice,
    steps: tuple[Step, ...],
    submission_script: str,
    ctx: SharedContext,
    *,
    code: str,
    hpc: HpcProfile,
    assignments: Mapping[str, object],
    source: StructureIdentity,
) -> BundleInput:
    """``service/_bundle.py``'s ``to_bundle_input``, for a ``dos``
    task. The pseudopotential files and their licence come from
    ``advice.scf`` -- the same system advice ``advice.nscf`` holds
    (``advise_steps``)."""
    return assemble_bundle_input(
        advice.scf.system.pseudo,
        steps,
        submission_script,
        ctx,
        advice.records(),
        advice.warnings(),
        request_identity(
            "dos", code=code, hpc=hpc, assignments=assignments, source=source
        ),
        hpc=hpc,
        job=advice.scf.step.resources.job.value,
    )
