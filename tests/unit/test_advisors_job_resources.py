from __future__ import annotations

from dataclasses import replace

import pytest
from pymatgen.core import Lattice

from goldilocks_core.advisors.job_resources import (
    JobHumanInput,
    JobLlmInput,
    JobStep,
    JobTimerProtocol,
    job_resources,
)
from goldilocks_core.advisors.parallelisation import (
    ParallelisationHumanInput,
    diag_grid_side,
)
from goldilocks_core.advisors.size import (
    ResourceEstimate,
    Species,
    memory_estimate,
    resource_estimate,
)
from goldilocks_core.inputs.hpc import Hardware, HpcProfile, Partition

_SPECIES = (Species(atoms=2, projectors=4, l_max=1, ultrasoft=False),)
_SILICON = Lattice.cubic(5.43)


def _estimate(
    lattice: Lattice = _SILICON,
    *,
    pairs: int = 4,
    ecutrho_ry: float = 160.0,
    nbnd: int = 8,
) -> ResourceEstimate:
    return resource_estimate(
        lattice,
        _SPECIES,
        ecutwfc_ry=ecutrho_ry / 4,
        ecutrho_ry=ecutrho_ry,
        nbnd=nbnd,
        n_kpoint_spin=pairs,
        nspin=1,
        npol=1,
        nspin_mag=1,
        scf_loop=True,
        variable_cell=False,
        local_tf_mixing=False,
    )


_SMALL = _estimate()
_BOX = _estimate(Lattice.cubic(20.0), pairs=1, nbnd=400)
"""Gamma-only, so every layout keeps one pool, and with 400 bands the
distributed arrays outweigh ggen's per-process floor, so memory per
process falls as tasks are added."""
_HUGE = _estimate(Lattice.cubic(100.0), pairs=1, ecutrho_ry=400.0)
"""ggen's 16 x ngm bytes on every process alone exceed what a 64-task
node can give each task, so no node count fits (memory_report.f90:464)."""
_SMALL_JOB = {"scf": JobStep(_SMALL)}
_HUGE_JOB = {"scf": JobStep(_HUGE)}


def _profile(
    *, with_bigmem: bool = False, mem_per_node_gb: float = 250, max_nodes: int = 100
) -> HpcProfile:
    default_hw = Hardware(
        cores_per_node=64,
        mem_per_node_gb=mem_per_node_gb,
        max_nodes=max_nodes,
        max_walltime_h=168,
    )
    partitions = {
        "scarf": Partition(name="scarf", hardware=default_hw, default=True),
    }
    if with_bigmem:
        partitions["bigmem"] = Partition(
            name="bigmem",
            hardware=Hardware(
                cores_per_node=64,
                mem_per_node_gb=1024,
                max_nodes=10,
                max_walltime_h=24,
            ),
        )
    return HpcProfile(
        name="test-cluster",
        scheduler="slurm",
        launcher="srun",
        modules={},
        partitions=partitions,
    )


def _per_process_mb(estimate: ResourceEstimate, ntasks: int, npool: int = 1) -> float:
    """pw.x's figure with the grid pw.x picks itself when ndiag is unset."""
    side = diag_grid_side(None, ntasks // npool, estimate.nbnd)
    return memory_estimate(
        estimate, ntasks=ntasks, npool=npool, diag_side=side
    ).per_process_mb


def _node_gb(per_process_mb: float) -> float:
    """What 64 tasks of that size need with the 1.2 safety factor."""
    return per_process_mb * 64 * 1.2 / 1024


def test_small_job_stays_on_the_default_partition() -> None:
    state = job_resources(_SMALL_JOB, _profile())

    assert state.ok
    assert state.value.partition == "scarf"
    assert state.value.nodes == 1
    assert state.value.ntasks == 64


def test_the_job_publishes_pw_x_s_memory_for_the_layout_that_runs() -> None:
    """#148: 4 k-point/spin pairs on 64 tasks run 4 pools of 16 tasks."""
    state = job_resources(_SMALL_JOB, _profile())

    memory = memory_estimate(_SMALL, ntasks=64, npool=4, diag_side=1)
    assert state.value.memory_per_process_mb == round(memory.per_process_mb, 2)
    assert state.value.memory_total_mb == round(memory.total_mb, 2)


@pytest.mark.parametrize("nodes", [2, 3])
def test_nodes_rise_until_64_tasks_of_pw_x_fit_a_node(nodes: int) -> None:
    """#148: the node count is the smallest whose per-process memory x
    tasks per node x 1.2 fits the node, not an aggregate over the job."""
    fits = _node_gb(_per_process_mb(_BOX, 64 * nodes))
    too_big = _node_gb(_per_process_mb(_BOX, 64 * (nodes - 1)))
    profile = _profile(mem_per_node_gb=(fits + too_big) / 2)

    state = job_resources({"scf": JobStep(_BOX)}, profile)

    assert state.value.nodes == nodes
    assert state.value.ntasks == 64 * nodes
    assert state.value.warnings == (_walltime_warning(state),)


def _walltime_warning(state):
    (warning,) = (w for w in state.value.warnings if w.code == "job.walltime_defaulted")
    return warning


@pytest.mark.parametrize("larger", ["scf", "nscf"])
def test_nodes_are_sized_for_the_step_that_needs_the_most(larger) -> None:
    smaller = "nscf" if larger == "scf" else "scf"
    fits = _node_gb(_per_process_mb(_BOX, 128))
    too_big = _node_gb(_per_process_mb(_BOX, 64))
    profile = _profile(mem_per_node_gb=(fits + too_big) / 2)
    steps = {larger: JobStep(_BOX), smaller: JobStep(_SMALL)}

    state = job_resources(steps, profile)

    assert state.value.nodes == 2
    assert state.value.memory_per_process_mb == round(_per_process_mb(_BOX, 128), 2)


def test_a_human_npool_is_the_layout_that_is_sized() -> None:
    """64 pairs would get 64 pools of one task each; npool=1 spreads every
    array over all 64 tasks instead."""
    estimate = _estimate(pairs=64)
    pooled = job_resources({"scf": JobStep(estimate)}, _profile())
    single = job_resources(
        {"scf": JobStep(estimate, ParallelisationHumanInput(npool=1))}, _profile()
    )

    assert pooled.value.memory_per_process_mb == round(
        _per_process_mb(estimate, 64, npool=64), 2
    )
    assert single.value.memory_per_process_mb == round(
        _per_process_mb(estimate, 64, npool=1), 2
    )
    assert single.value.memory_per_process_mb < pooled.value.memory_per_process_mb


def test_a_human_ndiag_is_the_grid_that_is_sized() -> None:
    estimate = replace(_estimate(pairs=1), nbnd=400)
    state = job_resources(
        {"scf": JobStep(estimate, ParallelisationHumanInput(ndiag=16))}, _profile()
    )

    memory = memory_estimate(estimate, ntasks=64, npool=1, diag_side=4)
    assert state.value.memory_per_process_mb == round(memory.per_process_mb, 2)


def test_human_nodes_that_cannot_hold_pw_x_warn() -> None:
    too_big = _node_gb(_per_process_mb(_BOX, 64))
    profile = _profile(mem_per_node_gb=too_big / 2)

    state = job_resources({"scf": JobStep(_BOX)}, profile, human=JobHumanInput(nodes=1))

    assert state.value.nodes == 1
    (warning,) = (
        w for w in state.value.warnings if w.code == "job.memory_exceeds_node"
    )
    assert warning.level == "warning"
    assert "scf" in warning.message


def test_human_ntasks_below_a_node_are_sized_on_the_tasks_that_run() -> None:
    """16 tasks put 16 processes on their one node, not the node's 64
    cores: memory for 32 of them is enough."""
    profile = _profile(mem_per_node_gb=_node_gb(_per_process_mb(_BOX, 16)) / 2)

    state = job_resources(
        {"scf": JobStep(_BOX)}, profile, human=JobHumanInput(ntasks=16)
    )

    assert (state.value.nodes, state.value.ntasks) == (1, 16)
    assert "job.memory_exceeds_node" not in [w.code for w in state.value.warnings]


def test_human_nodes_that_hold_pw_x_do_not_warn_about_memory() -> None:
    state = job_resources(_SMALL_JOB, _profile(), human=JobHumanInput(nodes=2))

    assert "job.memory_exceeds_node" not in [w.code for w in state.value.warnings]


def test_walltime_defaults_to_the_partitions_ceiling_with_a_warning() -> None:
    state = job_resources(_SMALL_JOB, _profile())

    assert state.value.walltime_h == 168
    (warning,) = (
        warning
        for warning in state.value.warnings
        if warning.code == "job.walltime_defaulted"
    )
    assert warning.message.startswith(
        "walltime not specified; requesting the ceiling of partition scarf (168h)."
    )


def test_a_single_step_keeps_the_whole_max_seconds_budget() -> None:
    state = job_resources(_SMALL_JOB, _profile())

    assert state.value.max_seconds_by_step == {"scf": 574560}  # 0.95 x 168 h


def test_steps_split_the_max_seconds_budget_by_workload() -> None:
    """#169: pw.x counts max_seconds from its own start, so steps that run
    one after another in one allocation each get a share of 95% of the
    walltime (13680 s of 4 h), floored so the shares never sum past it."""
    steps = {
        "scf": JobStep(replace(_SMALL, workload=1560)),
        "nscf": JobStep(replace(_SMALL, workload=1512)),
    }

    state = job_resources(steps, _profile(), human=JobHumanInput(walltime_h=4.0))

    assert state.value.max_seconds_by_step == {"scf": 6946, "nscf": 6733}
    assert state.value.timer_seconds is None
    assert state.provenance.source_note is None


@pytest.mark.parametrize("walltime_h, seconds", [(None, 574560), (4.0, 13680)])
def test_a_job_timer_replaces_every_steps_max_seconds_share(
    walltime_h: float | None, seconds: int
) -> None:
    """#215: under a task protocol's job timer no step gets a share; the
    timer fires at the same 95% of the walltime (of 168 h, the partition's
    ceiling, or of a requested 4 h), the job record carries the protocol's
    note, and the job is otherwise the one the shares would have run in."""
    steps = {
        "scf": JobStep(replace(_SMALL, workload=1560)),
        "nscf": JobStep(replace(_SMALL, workload=1512)),
    }
    human = JobHumanInput(walltime_h=walltime_h)
    timer = JobTimerProtocol(note="Test protocol: one timer for the whole job.")

    split = job_resources(steps, _profile(), human=human)
    timed = job_resources(steps, _profile(), human=human, timer=timer)

    assert timed.value.max_seconds_by_step == {}
    assert timed.value.timer_seconds == seconds
    assert timed.provenance.source_note == "Test protocol: one timer for the whole job."
    assert timed.source == split.source
    assert split.value.timer_seconds is None
    assert (
        replace(
            timed.value,
            max_seconds_by_step=split.value.max_seconds_by_step,
            timer_seconds=None,
        )
        == split.value
    )


def test_max_seconds_shares_are_proportional_to_workload() -> None:
    steps = {
        "scf": JobStep(replace(_SMALL, workload=1)),
        "nscf": JobStep(replace(_SMALL, workload=3)),
    }

    state = job_resources(steps, _profile(), human=JobHumanInput(walltime_h=1.0))

    shares = state.value.max_seconds_by_step
    assert shares == {"scf": 855, "nscf": 2565}
    assert sum(shares.values()) <= int(0.95 * 1.0 * 3600)


def test_the_step_that_fits_nowhere_picks_the_larger_partition() -> None:
    steps = {"scf": JobStep(_SMALL), "nscf": JobStep(_HUGE)}

    state = job_resources(steps, _profile(with_bigmem=True))

    assert state.value.partition == "bigmem"


def test_human_walltime_is_used_without_a_warning() -> None:
    state = job_resources(_SMALL_JOB, _profile(), human=JobHumanInput(walltime_h=2.0))

    assert state.value.walltime_h == 2.0
    assert state.value.warnings == ()
    assert state.source == "human"


def test_a_job_no_node_count_fits_moves_to_a_larger_memory_partition() -> None:
    state = job_resources(_HUGE_JOB, _profile(with_bigmem=True))

    assert state.value.partition == "bigmem"
    codes = [warning.code for warning in state.value.warnings]
    assert "job.partition_upgraded_for_memory" in codes
    # Not even bigmem's 10 nodes hold it: the largest request, and a warning.
    assert state.value.nodes == 10
    assert "job.memory_exceeds_node" in codes


def test_a_job_no_node_count_fits_warns_when_no_larger_partition_exists() -> None:
    state = job_resources(_HUGE_JOB, _profile(with_bigmem=False))

    assert state.ok
    assert state.value.partition == "scarf"
    assert state.value.nodes == 100
    codes = [warning.code for warning in state.value.warnings]
    assert "job.no_larger_partition_available" in codes
    assert "job.memory_exceeds_node" in codes


def test_a_partition_that_fits_is_kept_although_a_larger_one_exists() -> None:
    state = job_resources(_SMALL_JOB, _profile(with_bigmem=True))

    assert state.value.partition == "scarf"
    assert "job.partition_upgraded_for_memory" not in [
        w.code for w in state.value.warnings
    ]


def test_human_can_force_a_specific_partition() -> None:
    state = job_resources(
        _SMALL_JOB,
        _profile(with_bigmem=True),
        human=JobHumanInput(partition="bigmem"),
    )

    assert state.value.partition == "bigmem"
    assert state.value.ntasks_per_node == 64


def test_unknown_partition_name_is_unavailable_not_a_crash() -> None:
    state = job_resources(
        _SMALL_JOB, _profile(), human=JobHumanInput(partition="does-not-exist")
    )

    assert not state.ok
    assert state.status == "unavailable"
    assert state.reason == (
        "HPC profile test-cluster has no partition does-not-exist; available: scarf"
    )


def test_human_nodes_and_ntasks_override_the_heuristic() -> None:
    state = job_resources(
        _SMALL_JOB, _profile(), human=JobHumanInput(nodes=4, ntasks=200)
    )

    assert state.value.nodes == 4
    assert state.value.ntasks == 200


def test_account_is_never_guessed() -> None:
    state = job_resources(_SMALL_JOB, _profile())

    assert state.value.account is None


def test_ntasks_alone_derives_a_self_consistent_nodes_count() -> None:
    """Regression for #35 (v2 epic 9, #9): ntasks given with no nodes
    override used to leave nodes at the memory-estimate heuristic value
    regardless, so ntasks-per-node (fixed to the partition's
    cores_per_node) times nodes could be smaller than the requested
    ntasks -- an internally self-contradictory submit.sh."""
    state = job_resources(_SMALL_JOB, _profile(), human=JobHumanInput(ntasks=200))

    assert state.value.ntasks == 200
    assert state.value.ntasks <= state.value.nodes * state.value.ntasks_per_node


def test_nodes_exceeding_the_partition_ceiling_warns() -> None:
    """Regression for #35 (v2 epic 9, #9): nodes had no upper-bound
    check against the chosen partition's own max_nodes at all."""
    state = job_resources(
        _SMALL_JOB,
        _profile(with_bigmem=True),
        human=JobHumanInput(partition="bigmem", nodes=50),
    )

    assert state.value.nodes == 50
    assert [
        warning.message
        for warning in state.value.warnings
        if warning.code == "job.nodes_exceeds_partition_ceiling"
    ] == [
        "nodes=50 exceeds the ceiling of partition bigmem (10 nodes); the "
        "scheduler will likely refuse this request."
    ]


def test_walltime_exceeding_the_partition_ceiling_warns() -> None:
    """Regression for #35 (v2 epic 9, #9): walltime_h had no upper
    -bound check against the chosen partition's own max_walltime_h."""
    state = job_resources(_SMALL_JOB, _profile(), human=JobHumanInput(walltime_h=999.0))

    assert state.value.walltime_h == 999.0
    assert [
        warning.message
        for warning in state.value.warnings
        if warning.code == "job.walltime_exceeds_partition_ceiling"
    ] == [
        "walltime_h=999 exceeds the ceiling of partition scarf (168h); the "
        "scheduler will likely refuse this request."
    ]


def test_human_account_passes_through() -> None:
    state = job_resources(_SMALL_JOB, _profile(), human=JobHumanInput(account="scd"))

    assert state.value.account == "scd"


def test_llm_walltime_used_when_no_human_override() -> None:
    state = job_resources(_SMALL_JOB, _profile(), llm=JobLlmInput(walltime_h=4.0))

    assert state.value.walltime_h == 4.0
    assert state.source == "llm"
