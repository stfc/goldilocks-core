"""``advise_relax()``/``check_relax()``/``generate_relax()``: the
``relax``/``vc-relax`` tasks' path (v2 epic 10, #10).

**Single-step, unlike ``dos``.** ``relax``/``vc-relax`` are one ``pw.x``
run each (``calculation='relax'``/``'vc-relax'`` does the electronic
scf loop *and* the ionic/cell optimization together) -- not a second
pw.x step like ``service/_dos.py``'s nscf. This module asks
``advise_steps`` for that one step, keyed by its ``calculation`` (so
the job's ``max_seconds_by_step`` names it), calls ``generate()`` once,
and adds exactly one more resolved decision (``relax``) on top --
mirroring how ``service/_dos.py``'s own ``DosAdvice`` adds ``dos`` on
top of two ``Advice``s, just with one ``Advice`` instead of two.

**``RelaxOverrides`` is real request-validation plumbing, not a
task-specific side channel.** ``relax``/``relax_llm`` are read off the
step's own overrides (``capabilities.py``'s ``relax`` branch, v2 epic 10,
#10), which ``set_overrides.build_overrides`` routes to the step named by
``calculation``: ``--set nstep=100`` (etc.) reaches here, and a vc-relax
key on a relax (``press``) is refused before it (#154).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from pymatgen.core import Structure

from goldilocks_core.advisors.relax import (
    RelaxOptions,
    VcRelaxOptions,
    relax_settings,
)
from goldilocks_core.assets.store import AssetStore
from goldilocks_core.bundle import BundleInput, StructureIdentity
from goldilocks_core.checks import CheckReport
from goldilocks_core.inputs.hpc import HpcProfile
from goldilocks_core.resolution import FieldState
from goldilocks_core.service._advice import Advice, RecordTiers, RunOverrides
from goldilocks_core.service._bundle import (
    assemble_bundle_input,
    render_submission,
    request_identity,
)
from goldilocks_core.service._generate import AdviceIncomplete, generate
from goldilocks_core.service._pipeline import advise_steps, check
from goldilocks_core.steps import SharedContext, Step, default_shared_context


@dataclass(frozen=True, slots=True)
class RelaxAdvice:
    calculation: Literal["relax", "vc-relax"]
    advice: Advice
    relax: FieldState[RelaxOptions | VcRelaxOptions]

    def field_states(self) -> tuple[FieldState[object], ...]:
        return (*self.advice.field_states(), self.relax)

    def tiers(self) -> RecordTiers:
        """``advice``'s records by tier, its one step named by
        ``calculation`` and holding ``relax`` too."""
        return self.advice.tiers(self.calculation).with_records(
            self.calculation, {"relax": self.relax}
        )

    def records(self) -> dict[str, FieldState[object]]:
        return self.tiers().records()

    def warnings(self) -> list[dict[str, object]]:
        return self.tiers().warnings()


def advise_relax(
    structure: Structure,
    *,
    calculation: Literal["relax", "vc-relax"],
    code: str = "quantum_espresso",
    hpc: HpcProfile,
    overrides: RunOverrides | None = None,
    store: AssetStore | None = None,
    fetch_missing: bool = False,
) -> RelaxAdvice:
    """Diagnosis, under the same contract as ``advise()``: an undecided
    field degrades, a fault raises. ``relax_settings`` reads
    ``advice.step.kpoints.convergence`` (for ``etot_conv_thr``) and
    ``advice.system.geometry_eff``, the uploaded structure's geometry with
    the vacuum and frame of the cell to be written, the record the advice
    publishes (#210), which decides vc-relax's ``cell_dofree``, off the very
    same ``Advice`` this function
    just built -- no second structure-analysis pass. The written cell puts
    every slab with its vacuum along c in the xy frame, so such a slab
    gets '2Dxy' however it was uploaded (#140)."""
    overrides = overrides or RunOverrides()
    steps = overrides.for_steps((calculation,))
    advice = advise_steps(
        structure,
        code=code,
        hpc=hpc,
        overrides=overrides,
        steps=steps,
        store=store,
        fetch_missing=fetch_missing,
    )[calculation]
    relax_overrides = steps[calculation].relax
    relax = relax_settings(
        calculation,
        advice.step.kpoints.convergence,
        advice.system.geometry_eff,
        relax_overrides.relax,
        relax_overrides.relax_llm,
    )
    return RelaxAdvice(calculation=calculation, advice=advice, relax=relax)


def check_relax(advice: RelaxAdvice) -> CheckReport:
    """``advise_relax()``/``generate_relax()``'s boundary. ``relax`` is
    passed straight through to ``check()``/``checks.check_all`` -- which
    folds its own ``Blocked``-ness into ``collect_blocked`` and runs the
    vc-relax ``ion_dynamics`` rule (``checks.py``'s own
    ``_vc_relax_requires_bfgs_ion_dynamics``) -- so there is no separate
    ``collect_blocked(advice.relax)`` call here to double-count it."""
    return check(advice.advice, purpose=advice.calculation, relax=advice.relax)


def generate_relax(
    advice: RelaxAdvice, report: CheckReport, *, ctx: SharedContext | None = None
) -> tuple[Step, ...]:
    """Delivery: one real ``Step``. Raises ``AdviceIncomplete`` when
    ``report`` is not ``ok``, same contract as the single-step
    ``generate()`` -- checked once, directly, rather than re-derived:
    the inner ``generate()`` call below is passed a trivially-``ok``
    report, matching ``service/_dos.py``'s own ``generate_dos``."""
    if not report.ok:
        raise AdviceIncomplete(report)
    return generate(
        advice.advice,
        CheckReport(),
        ctx=ctx or default_shared_context(),
        purpose=advice.calculation,
        relax=advice.relax.value,
    )


def render_submission_relax(
    advice: RelaxAdvice,
    hpc: HpcProfile,
    code: str,
    steps: tuple[Step, ...],
) -> str:
    return render_submission(advice.advice, hpc, code, steps)


def to_bundle_input_relax(
    advice: RelaxAdvice,
    steps: tuple[Step, ...],
    submission_script: str,
    ctx: SharedContext,
    *,
    code: str,
    hpc: HpcProfile,
    assignments: Mapping[str, object],
    source: StructureIdentity,
) -> BundleInput:
    """``service/_bundle.py``'s ``to_bundle_input``, for a ``relax`` or
    ``vc-relax`` task: the request names ``advice.calculation``."""
    return assemble_bundle_input(
        advice.advice.system.pseudo,
        steps,
        submission_script,
        ctx,
        advice.records(),
        advice.warnings(),
        request_identity(
            advice.calculation,
            code=code,
            hpc=hpc,
            assignments=assignments,
            source=source,
        ),
    )
