"""Phase 3b of the v2 orchestrator (v2 epic 8, #8): resource sizing for
a task, the resources half of each ``StepAdvice`` ``_step.py`` composes
-- see that module's own docstring on why the per-step advisor set is
split across files.

**One job per task, parallelisation per step.** A task's pw.x steps run
one after another in one allocation, so ``task_resources`` makes one
``job_resources`` call over every step (#169): it sizes the allocation
on pw.x's memory per process for the layout each step will run (#148)
and gives each step its own ``max_seconds`` share of the walltime, which
the step's ``ResourceStepAdvice`` carries for ``generate()`` -- unless a
step's protocol runs a job timer for the task instead, when no step gets
one (#215). Each step's ``parallelisation`` then reads that job's
``ntasks`` and the step's own k-point/spin pairs (``n_irr_k`` -- a bands
step's is every point of its band path, #118 -- and the magnetic
decision's spin layout) -- ``job_resources`` evaluates that same function
for each candidate ``ntasks`` rather than reading its output (see
``advisors/job_resources.py``'s own module note on false circularity).
``JobOverrides`` (partition, nodes, ntasks, walltime, account) are
task-level, one per request; ``ResourceOverrides`` (``npool``/``ndiag``)
are per step (#154).

**The estimate reads the cell the writer renders**: the simulated cell,
``MagneticConfigFacts.cell`` (an AFM candidate can be a different cell
from the input, #128), one species per site label -- the species the
magnetic step split the cell into and the writer renders (#170) -- each
species' projector counts from its pseudopotential's PP_HEADER
(``_pseudo.upf_projectors``), the +U manifolds the writer renders, and
each step's mixing mode. A step without an SCF loop of its own (an nscf
or bands step, ``plan.SCF_LIKE_PURPOSES``) is estimated as one pass over
its k-points.

The estimate needs ``cutoffs``, the pseudopotentials, ``magnetic`` and
``hubbard``, and each step's ``nbnd``/``n_irr_k``/``convergence``
resolved, so the job is ``Blocked`` by the first of those that is not;
a pseudopotential header without projector counts (naming the file) makes
it ``Unavailable``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

from goldilocks_core.advisors.job_resources import (
    JobDecision,
    JobHumanInput,
    JobLlmInput,
    JobStep,
    JobTimerProtocol,
    job_resources,
)
from goldilocks_core.advisors.parallelisation import (
    ParallelisationDecision,
    ParallelisationHumanInput,
    kpoint_spin_pairs,
    parallelisation,
    qe_spin_layout,
)
from goldilocks_core.advisors.size import Species, resource_estimate
from goldilocks_core.inputs.hpc import HpcProfile
from goldilocks_core.plan import SCF_LIKE_PURPOSES
from goldilocks_core.resolution import Blocked, FieldState, Unavailable, blocked_by
from goldilocks_core.service._pseudo import upf_projectors
from goldilocks_core.service._step_kpath import PathStepAdvice
from goldilocks_core.service._step_kpoints import ElectronicStepAdvice
from goldilocks_core.service._system import SystemAdvice

_ANGULAR_MOMENTA = "spdf"


@dataclass(frozen=True, slots=True)
class JobOverrides:
    """The task's one allocation: a request sets it once, never per step,
    since ``render_submission*`` writes one ``#SBATCH`` header per task."""

    job: JobHumanInput | None = None
    job_llm: JobLlmInput | None = None


@dataclass(frozen=True, slots=True)
class ResourceOverrides:
    """One pw.x step's own layout inside the task's allocation."""

    parallelisation: ParallelisationHumanInput | None = None


@dataclass(frozen=True, slots=True)
class ResourceStepAdvice:
    """One step's resources: the task's one ``job`` (the same state in
    every step of the task), the step's own ``parallelisation``, and its
    ``max_seconds`` share of the job's walltime
    (``JobDecision.max_seconds_by_step``), ``None`` while the job is not
    resolved or when it runs a timer instead (``JobDecision.timer_seconds``)."""

    job: FieldState[JobDecision]
    parallelisation: FieldState[ParallelisationDecision]
    max_seconds: int | None

    def field_states(self) -> tuple[FieldState[object], ...]:
        return (self.job, self.parallelisation)

    def records(self) -> dict[str, FieldState[object]]:
        return {"job": self.job, "parallelisation": self.parallelisation}


def task_resources(
    system: SystemAdvice,
    electronic: Mapping[str, ElectronicStepAdvice | PathStepAdvice],
    hpc: HpcProfile,
    job_human: JobHumanInput | None,
    job_llm: JobLlmInput | None,
    parallelisation_human: Mapping[str, ParallelisationHumanInput | None],
    timer: JobTimerProtocol | None = None,
) -> dict[str, ResourceStepAdvice]:
    """Each step's resources, keyed like ``electronic`` (purpose -> the
    step's electronic advice, a mesh step's or a bands step's): one job
    from ``job_human``/``job_llm``, running the task protocol's ``timer``
    in place of the steps' ``max_seconds`` shares when one is given, and
    each step's npool/ndiag from ``parallelisation_human[purpose]``."""
    unresolved = next(
        (
            state
            for step in electronic.values()
            for state in (
                system.cutoffs,
                system.pseudo.metadata,
                system.magnetic,
                system.hubbard,
                step.nbnd,
                step.n_irr_k,
                step.convergence,
            )
            if not state.ok
        ),
        None,
    )
    if unresolved is not None:
        return _without_job(electronic, Blocked(by=blocked_by(unresolved)))
    species = _written_species(system)
    if isinstance(species, Unavailable):
        return _without_job(electronic, species)

    pairs = {
        purpose: kpoint_spin_pairs(step.n_irr_k.value, system.magnetic.value)
        for purpose, step in electronic.items()
    }
    steps = {
        purpose: _job_step(
            system, species, step, pairs[purpose], purpose, parallelisation_human
        )
        for purpose, step in electronic.items()
    }
    job = job_resources(steps, hpc, job_human, job_llm, timer)
    return {
        purpose: _step_resources(
            job, purpose, pairs[purpose], parallelisation_human[purpose]
        )
        for purpose in electronic
    }


def _without_job(
    electronic: Mapping[str, ElectronicStepAdvice | PathStepAdvice],
    job: Blocked | Unavailable,
) -> dict[str, ResourceStepAdvice]:
    return {
        purpose: ResourceStepAdvice(
            job=job, parallelisation=Blocked(by=blocked_by(job)), max_seconds=None
        )
        for purpose in electronic
    }


def _written_species(system: SystemAdvice) -> tuple[Species, ...] | Unavailable:
    """The species of the cell the writer renders (module docstring);
    ``Unavailable`` for a pseudopotential header without projector counts."""
    magnetic = system.magnetic.value
    metadata = system.pseudo.metadata.value
    projectors = upf_projectors(metadata)
    if isinstance(projectors, Unavailable):
        return projectors
    ultrasoft = {item.element: item.pseudo_type in ("USPP", "PAW") for item in metadata}
    hubbard_l = _hubbard_angular_momenta(system)
    atoms = Counter((site.label, site.specie.symbol) for site in magnetic.cell)
    return tuple(
        Species(
            atoms=count,
            projectors=projectors[element][0],
            l_max=projectors[element][1],
            ultrasoft=ultrasoft[element],
            hubbard_l=hubbard_l.get(element),
        )
        for (_label, element), count in atoms.items()
    )


def _hubbard_angular_momenta(system: SystemAdvice) -> dict[str, int]:
    """element -> the angular momentum of its +U manifold, for every
    element the writer renders a U line for (one per
    ``HubbardUDecision.u_values`` entry; each species of a split element
    takes its element's line)."""
    return {
        entry.element: _ANGULAR_MOMENTA.index(entry.manifold[-1])
        for entry in system.hubbard.value.u_values
    }


def _job_step(
    system: SystemAdvice,
    species: tuple[Species, ...],
    step: ElectronicStepAdvice | PathStepAdvice,
    n_kpoint_spin: int,
    purpose: str,
    parallelisation_human: Mapping[str, ParallelisationHumanInput | None],
) -> JobStep:
    """The step's estimate on the written cell, with its npool/ndiag."""
    magnetic = system.magnetic.value
    layout = qe_spin_layout(magnetic)
    estimate = resource_estimate(
        magnetic.cell.lattice,
        species,
        ecutwfc_ry=system.cutoffs.value.ecutwfc_ry,
        ecutrho_ry=system.cutoffs.value.ecutrho_ry,
        nbnd=step.nbnd.value.nbnd,
        n_kpoint_spin=n_kpoint_spin,
        nspin=layout.nspin,
        npol=layout.npol,
        nspin_mag=layout.nspin_mag,
        scf_loop=purpose in SCF_LIKE_PURPOSES,
        variable_cell=purpose == "vc-relax",
        local_tf_mixing=step.convergence.value.mixing_mode == "local-TF",
    )
    return JobStep(estimate, parallelisation_human[purpose])


def _step_resources(
    job: FieldState[JobDecision],
    purpose: str,
    n_kpoint_spin: int,
    human: ParallelisationHumanInput | None,
) -> ResourceStepAdvice:
    """The step's layout and its share, none under a job timer; a job that
    splits the walltime holds a share for every step it was sized over."""
    if not job.ok:
        return ResourceStepAdvice(
            job=job, parallelisation=Blocked(by=blocked_by(job)), max_seconds=None
        )
    return ResourceStepAdvice(
        job=job,
        parallelisation=parallelisation(job.value.ntasks, n_kpoint_spin, human),
        max_seconds=(
            None
            if job.value.timer_seconds is not None
            else job.value.max_seconds_by_step[purpose]
        ),
    )
