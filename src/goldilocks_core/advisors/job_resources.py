"""job_resources: one job per task -- partition, nodes, ntasks, walltime,
and each ``pw.x`` step's ``max_seconds`` or the job's timer -- from the
task's per-step resource estimates and an HPC profile.

New in v2 (v2 epic 7, #7); no v1 precedent. Part of the false
-circularity fix goldilocks-core-design.md:3176-3195 describes:
``resource_estimate`` (``advisors/size.py``) carries zero parallel
information, and ``advisors/parallelisation.py``'s ``parallelisation``
is a pure function of a job's ``ntasks`` and a step's k-point/spin
pairs. This module therefore evaluates the layout ``parallelisation``
will choose for each candidate ``ntasks`` -- a bounded search, not
feedback: ``parallelisation`` never reads this module's output, only
the ``ntasks`` it settles on.

**`nodes` are sized on pw.x's memory per process for the layout that
will run (#148).** For each candidate node count (``ntasks = nodes x
cores_per_node``) every step gets the npool/ndiag ``parallelisation``
gives it, from the user's overrides or its default, and
``size.memory_estimate`` gives pw.x's "max dynamical RAM per process"
for that layout. The heuristic takes the smallest node count on which
the largest step's figure x the tasks on one node x
``_NODE_SAFETY_FACTOR`` fits the node's memory; the factor covers what
pw.x's own estimate leaves out (the static footprint of the binary and
libraries: SCARF MaxRSS ran above pw.x's figure). Memory is never an
aggregate over the job: every process holds its own share, and every
pool its own copy of the wavefunctions and density. A user's ``nodes``
or ``ntasks`` is kept and only warned about
(``job.memory_exceeds_node``) when it does not fit; the estimate is
+-20% at best. ``JobDecision`` publishes the sizing step's two figures.

**`partition` is resolved with the machine, upstream of nodes/ntasks,
not a peer of them** (goldilocks-core-design.md:1561-1581): choosing an
HPC profile fixes the default partition; the heuristic only moves off
it when no node count up to the partition's ceiling fits, at which
point it takes the largest-memory partition in the same profile (and
only warns, does not silently guess, if none exists -- SCARF's own
profile today has no such "bigmem"-style escape hatch to fall back
to). Where nothing fits, the job asks for the partition's node ceiling
and warns.

**One job for all of a task's steps.** The steps run one after another
in one allocation, so partition and nodes are sized for the step that
needs the most memory per process, and the steps share one walltime.

**`walltime` is anchored at the partition's own ceiling, not a
middling guess** (goldilocks-core-design.md:1337-1394): `size` gives
*relative* workload, not absolute time, and no machine-specific
throughput constant has ever been calibrated -- guessing short kills
the job (the whole run is wasted); guessing long only costs queue time.
So the heuristic default is `max_walltime_h` itself, with a warning,
never a "conservative-looking" smaller number.

**`max_seconds_by_step` splits 95% of the walltime across the steps**
(the 95% matches aiida-quantumespresso's own `max_seconds` convention).
pw.x counts `max_seconds` from its own start (QE 7.3
`Modules/check_stop.f90:69`, `:147-148`), so steps that each got 95% of
the walltime would overrun it together, and SLURM would kill the later
one without restart data. Each step's share is proportional to its
estimated `workload` and floored to whole seconds, so the shares never
sum past the 95%; a single step gets all of it. A step that reaches its
share stops cleanly with exit_status 255, which the submission script
reports (`submission/slurm.py`). The shares are static because they are
written into each step's input (`generation/quantum_espresso/scf.py`).
Programs other than pw.x (`dos.x`, `bands.x`) get no share and run in the
rest.

**A task's protocol can run a job timer instead** (`JobTimerProtocol`,
#215). No step then gets a share: `max_seconds_by_step` is empty, so no
input carries `max_seconds`, and `timer_seconds` is the same 95% of the
walltime, counted from the job's start. At that time the job's timer
(`submission/slurm.py`) creates `<prefix>.EXIT`, which pw.x and ph.x look
for in the working directory, delete, and stop cleanly at (QE 7.3
`Modules/check_stop.f90:59-63`, `:124-133`), so each step can use the time
the steps before it left. The job record's `source_note` is the
protocol's note.

`npool`/`ndiag`/`nimage` are not decided here -- that is
`advisors/parallelisation.py`'s job, reading this module's `ntasks` as
an input. `account` has no ml/heuristic tier at all: it is personal to
whoever is submitting, not a property of the machine or the
calculation, so it is human-only, and left `None` (not guessed) if
never supplied.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import Field

from goldilocks_core.advisors.parallelisation import (
    ParallelisationHumanInput,
    diag_grid_side,
    parallelisation,
)
from goldilocks_core.advisors.size import (
    MemoryEstimate,
    ResourceEstimate,
    memory_estimate,
)
from goldilocks_core.inputs.hpc import HpcProfile, Partition
from goldilocks_core.inputs.overrides import HumanInput, LlmInput
from goldilocks_core.resolution import (
    FieldState,
    Provenance,
    Resolved,
    Unavailable,
    Warning,
)

_NODE_SAFETY_FACTOR = 1.2
_MAX_SECONDS_FRACTION = 0.95
_MB_PER_GB = 1024

WARNING_CATALOGUE = (
    Warning(
        code="job.partition_upgraded_for_memory",
        level="info",
        category="job",
        message=(
            "pw.x's estimated memory does not fit the default partition at "
            "any node count up to its ceiling; a larger-memory partition on "
            "the same profile was used instead."
        ),
    ),
    Warning(
        code="job.no_larger_partition_available",
        level="warning",
        category="job",
        message=(
            "pw.x's estimated memory does not fit the default partition at "
            "any node count up to its ceiling, and the HPC profile has no "
            "larger-memory partition to fall back to."
        ),
    ),
    Warning(
        code="job.memory_exceeds_node",
        level="warning",
        category="job",
        message=(
            "pw.x's estimated memory per process, times the tasks on one "
            "node and a 1.2 safety factor, exceeds a node's memory; the job "
            "is likely to run out of memory."
        ),
    ),
    Warning(
        code="job.walltime_defaulted",
        level="warning",
        category="job",
        message=(
            "walltime not specified; requesting the chosen partition's own "
            "ceiling instead of a guessed value."
        ),
    ),
    Warning(
        code="job.nodes_exceeds_partition_ceiling",
        level="warning",
        category="job",
        message=(
            "nodes exceeds the chosen partition's own ceiling; the scheduler "
            "will likely refuse this request."
        ),
    ),
    Warning(
        code="job.walltime_exceeds_partition_ceiling",
        level="warning",
        category="job",
        message=(
            "walltime_h exceeds the chosen partition's own ceiling; the "
            "scheduler will likely refuse this request."
        ),
    ),
)
"""Every warning code this module can emit -- ``capabilities.py``'s
``warnings[]`` catalogue aggregates one of these tuples per advisor. The
real, per-occurrence messages (naming the actual partition/GB figures)
are built at their call sites below; these are the generic descriptions
of each code, for a caller that has not seen it fire."""


@dataclass(frozen=True, slots=True)
class JobStep:
    """One pw.x step the job must hold: its estimate and the user's
    npool/ndiag for it, which fix its layout for a given ``ntasks``."""

    estimate: ResourceEstimate
    parallelisation: ParallelisationHumanInput | None = None


@dataclass(frozen=True, slots=True)
class JobDecision:
    """The task's one job. ``max_seconds_by_step`` maps each pw.x step's
    purpose to its share of the walltime, in seconds; under a job timer it
    is empty and ``timer_seconds`` is when the timer fires, in seconds from
    the job's start, otherwise ``None`` (module docstring).
    ``memory_per_process_mb``/``memory_total_mb`` are pw.x's estimated
    memory per process and in total, in MB, for the step that needs the
    most per process, at this job's layout."""

    partition: str
    nodes: int
    ntasks: int
    ntasks_per_node: int
    walltime_h: float
    max_seconds_by_step: dict[str, int]
    memory_per_process_mb: float
    memory_total_mb: float
    account: str | None
    warnings: tuple[Warning, ...] = ()
    timer_seconds: int | None = None


class JobHumanInput(HumanInput):
    """``nodes``/``ntasks``/``walltime_h`` must be positive at
    construction (#35, v2 epic 9, #9) -- before this, e.g. ``nodes=0``
    or a negative ``walltime_h`` was accepted and reached ``#SBATCH``
    verbatim, or crashed downstream with an unrelated traceback rather
    than a clean ``InvalidSetting`` error. Upper bounds against the
    chosen partition's own ceilings (``max_nodes``/``max_walltime_h``)
    can't be pydantic field constraints -- they need the partition,
    which isn't known yet at this class's construction time -- so those
    stay advisory warnings inside ``job_resources()`` below, same
    warn-don't-block pattern as ``advisors/parallelisation.py``'s own
    QE-will-refuse-this cases."""

    partition: str | None = None
    nodes: int | None = Field(default=None, gt=0)
    ntasks: int | None = Field(default=None, gt=0)
    walltime_h: float | None = Field(default=None, gt=0)
    account: str | None = None


class JobLlmInput(LlmInput):
    partition: str | None = None
    walltime_h: float | None = Field(default=None, gt=0)


@dataclass(frozen=True, slots=True)
class JobTimerProtocol:
    """A task protocol's job timer in place of the steps' ``max_seconds``
    shares (#215, module docstring). Not a request value, so it leaves the
    job record's source as the job settings give it; ``note`` becomes the
    record's ``source_note``."""

    note: str


def job_resources(
    steps: Mapping[str, JobStep],
    hpc: HpcProfile,
    human: JobHumanInput | None = None,
    llm: JobLlmInput | None = None,
    timer: JobTimerProtocol | None = None,
) -> FieldState[JobDecision]:
    """The job for a task whose pw.x steps run one after another in one
    allocation; ``steps`` maps each step's purpose to its estimate and
    npool/ndiag overrides. The step that needs the most memory per
    process sizes partition and nodes, and every step gets a
    ``max_seconds`` share, unless the task's protocol runs a ``timer``
    instead (module docstring)."""
    human = human or JobHumanInput()
    llm = llm or JobLlmInput()

    requested_partition = human.partition or llm.partition
    if requested_partition is not None and requested_partition not in hpc.partitions:
        available = ", ".join(sorted(hpc.partitions))
        return Unavailable(
            reason=f"HPC profile {hpc.name} has no partition "
            f"{requested_partition}; available: {available}"
        )

    partition, fitting_nodes, warnings = _pick_partition(steps, hpc, human, llm)
    hardware = partition.hardware
    ntasks_per_node = hardware.cores_per_node

    if human.nodes is not None:
        nodes = human.nodes
    elif human.ntasks is not None:
        # #35 (v2 epic 9, #9): ntasks given alone (no nodes) used to
        # leave nodes at the memory-estimate-derived heuristic value,
        # independent of the requested ntasks -- ntasks-per-node stays
        # fixed to the partition's cores_per_node regardless, so the two
        # could disagree (ntasks > nodes * ntasks_per_node), rendering a
        # submit.sh SLURM would reject as internally inconsistent.
        # Deriving nodes from ntasks here keeps the two self-consistent.
        nodes = math.ceil(human.ntasks / ntasks_per_node)
    else:
        nodes = fitting_nodes or hardware.max_nodes
    ntasks = human.ntasks if human.ntasks is not None else nodes * ntasks_per_node

    if nodes > hardware.max_nodes:
        warnings.append(
            Warning(
                code="job.nodes_exceeds_partition_ceiling",
                level="warning",
                category="job",
                message=(
                    f"nodes={nodes} exceeds the ceiling of partition "
                    f"{partition.name} ({hardware.max_nodes} nodes); the scheduler "
                    "will likely refuse this request."
                ),
            )
        )

    purpose, memory = _largest_step_memory(steps, ntasks)
    warnings.extend(_memory_warnings(purpose, memory, ntasks, partition))

    walltime_h = _pick_walltime(partition, human, llm, warnings)
    if walltime_h > hardware.max_walltime_h:
        warnings.append(
            Warning(
                code="job.walltime_exceeds_partition_ceiling",
                level="warning",
                category="job",
                message=(
                    f"walltime_h={walltime_h:g} exceeds the ceiling of partition "
                    f"{partition.name} ({hardware.max_walltime_h:g}h); the "
                    "scheduler will likely refuse this request."
                ),
            )
        )

    max_seconds_by_step, timer_seconds = _time_limits(walltime_h, steps, timer)
    decision = JobDecision(
        partition=partition.name,
        nodes=nodes,
        ntasks=ntasks,
        ntasks_per_node=ntasks_per_node,
        walltime_h=walltime_h,
        max_seconds_by_step=max_seconds_by_step,
        memory_per_process_mb=round(memory.per_process_mb, 2),
        memory_total_mb=round(memory.total_mb, 2),
        account=human.account,
        warnings=tuple(warnings),
        timer_seconds=timer_seconds,
    )
    source = "human" if _any_set(human) else "llm" if _any_set(llm) else "heuristic"
    note = None if timer is None else timer.note
    return Resolved(decision, Provenance(source=source, source_note=note))


def _pick_partition(
    steps: Mapping[str, JobStep],
    hpc: HpcProfile,
    human: JobHumanInput,
    llm: JobLlmInput,
) -> tuple[Partition, int | None, list[Warning]]:
    """The partition, the smallest node count on which every step fits
    it (``None`` when none does), and any partition warning."""
    name = human.partition or llm.partition
    if name is not None:
        partition = hpc.partition(name)
        return partition, _fitting_nodes(steps, partition), []

    default = hpc.default_partition()
    nodes = _fitting_nodes(steps, default)
    if nodes is not None:
        return default, nodes, []

    ceiling = default.hardware.max_nodes
    bigger = [
        partition
        for partition in hpc.partitions.values()
        if partition.hardware.mem_per_node_gb > default.hardware.mem_per_node_gb
    ]
    if bigger:
        chosen = max(bigger, key=lambda p: p.hardware.mem_per_node_gb)
        return (
            chosen,
            _fitting_nodes(steps, chosen),
            [
                Warning(
                    code="job.partition_upgraded_for_memory",
                    level="info",
                    category="job",
                    message=(
                        f"pw.x's estimated memory does not fit default "
                        f"partition {default.name} at any node count up to "
                        f"its ceiling of {ceiling}; using {chosen.name} "
                        "instead."
                    ),
                )
            ],
        )
    return (
        default,
        None,
        [
            Warning(
                code="job.no_larger_partition_available",
                level="warning",
                category="job",
                message=(
                    f"pw.x's estimated memory does not fit partition "
                    f"{default.name} at any node count up to its ceiling of "
                    f"{ceiling}, and profile {hpc.name} has no larger-memory "
                    "partition to fall back to."
                ),
            )
        ],
    )


def _fitting_nodes(steps: Mapping[str, JobStep], partition: Partition) -> int | None:
    """The smallest node count up to the partition's ceiling on which
    every step's layout fits a node (module docstring)."""
    hardware = partition.hardware
    for nodes in range(1, hardware.max_nodes + 1):
        ntasks = nodes * hardware.cores_per_node
        _purpose, memory = _largest_step_memory(steps, ntasks)
        if _node_gb(memory, ntasks, partition) <= hardware.mem_per_node_gb:
            return nodes
    return None


def _largest_step_memory(
    steps: Mapping[str, JobStep], ntasks: int
) -> tuple[str, MemoryEstimate]:
    """The step that needs the most memory per process on ``ntasks``
    processes, with its estimate."""
    memory = {purpose: _step_memory(step, ntasks) for purpose, step in steps.items()}
    purpose = max(memory, key=lambda name: memory[name].per_process_mb)
    return purpose, memory[purpose]


def _step_memory(step: JobStep, ntasks: int) -> MemoryEstimate:
    """pw.x's memory for ``step`` on ``ntasks`` processes, with the npool
    and ndiag ``parallelisation`` gives that layout."""
    estimate = step.estimate
    layout = parallelisation(
        ntasks, estimate.kpoint_spin_pairs, step.parallelisation
    ).value
    side = diag_grid_side(layout.ndiag, ntasks // layout.npool, estimate.nbnd)
    return memory_estimate(estimate, ntasks=ntasks, npool=layout.npool, diag_side=side)


def _node_gb(memory: MemoryEstimate, ntasks: int, partition: Partition) -> float:
    """What the busiest node needs, in GB, with the safety factor."""
    tasks_on_node = min(ntasks, partition.hardware.cores_per_node)
    return memory.per_process_mb * tasks_on_node * _NODE_SAFETY_FACTOR / _MB_PER_GB


def _memory_warnings(
    purpose: str, memory: MemoryEstimate, ntasks: int, partition: Partition
) -> list[Warning]:
    needed_gb = _node_gb(memory, ntasks, partition)
    available_gb = partition.hardware.mem_per_node_gb
    if needed_gb <= available_gb:
        return []
    tasks_on_node = min(ntasks, partition.hardware.cores_per_node)
    return [
        Warning(
            code="job.memory_exceeds_node",
            level="warning",
            category="job",
            message=(
                f"pw.x needs an estimated {memory.per_process_mb:.1f} MB per "
                f"process for the {purpose} step; {tasks_on_node} tasks per "
                f"node with the {_NODE_SAFETY_FACTOR} safety factor need "
                f"{needed_gb:.1f} GB, more than the {available_gb:g} GB of a "
                f"{partition.name} node. Request more nodes or a "
                "larger-memory partition."
            ),
        )
    ]


def _time_limits(
    walltime_h: float, steps: Mapping[str, JobStep], timer: JobTimerProtocol | None
) -> tuple[dict[str, int], int | None]:
    """``max_seconds_by_step`` and ``timer_seconds`` from 95% of the
    walltime: each step's share, in proportion to its workload and floored
    so the shares never sum past it, and no timer; or, under ``timer``, no
    shares and all of it for the timer."""
    budget = int(walltime_h * 3600 * _MAX_SECONDS_FRACTION)
    if timer is not None:
        return {}, budget
    total = sum(step.estimate.workload for step in steps.values())
    shares = {
        purpose: budget * step.estimate.workload // total
        for purpose, step in steps.items()
    }
    return shares, None


def _pick_walltime(
    partition: Partition,
    human: JobHumanInput,
    llm: JobLlmInput,
    warnings: list[Warning],
) -> float:
    if human.walltime_h is not None:
        return human.walltime_h
    if llm.walltime_h is not None:
        return llm.walltime_h
    warnings.append(
        Warning(
            code="job.walltime_defaulted",
            level="warning",
            category="job",
            message=(
                "walltime not specified; requesting the ceiling of partition "
                f"{partition.name} ({partition.hardware.max_walltime_h:g}h). This "
                "slows queueing -- schedulers favour short jobs -- but guessing short "
                "risks the job being killed before it finishes, wasting the "
                "entire run. If you know roughly how long this will take, set "
                "walltime_h explicitly."
            ),
        )
    )
    return partition.hardware.max_walltime_h


def _any_set(overrides: HumanInput) -> bool:
    return bool(overrides.model_dump(exclude_defaults=True))
