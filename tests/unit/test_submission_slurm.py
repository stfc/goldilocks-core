from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import replace
from pathlib import Path

import pytest

from goldilocks_core.advisors.job_resources import JobDecision
from goldilocks_core.inputs.hpc import Hardware, HpcProfile, Partition
from goldilocks_core.steps import (
    DynamicalMatricesCheck,
    ExitStatusCheck,
    StdoutMarkerCheck,
    Step,
)
from goldilocks_core.submission.errors import SubmissionError
from goldilocks_core.submission.slurm import render_slurm_script, run_instructions

_HARDWARE = Hardware(
    cores_per_node=64, mem_per_node_gb=250.0, max_nodes=454, max_walltime_h=168.0
)
_HPC = HpcProfile(
    name="scarf",
    scheduler="slurm",
    launcher="srun",
    modules={"quantum_espresso": ("QuantumESPRESSO/7.5-foss-2025a",)},
    partitions={"scarf": Partition(name="scarf", hardware=_HARDWARE, default=True)},
)
_JOB = JobDecision(
    partition="scarf",
    nodes=1,
    ntasks=64,
    ntasks_per_node=64,
    walltime_h=168.0,
    max_seconds_by_step={"scf": 574560},
    memory_per_process_mb=12.5,
    memory_total_mb=900.0,
    account=None,
)
_SCHEMA = "./out/pwscf.save/data-file-schema.xml"
_SCF_STEP = Step(
    name="scf",
    executable="pw.x",
    args=("-npool", "4", "-in", "scf.in"),
    files={"scf.in": "&CONTROL\n/\n"},
    stdout="scf.out",
    completion=ExitStatusCheck(_SCHEMA),
)
_NSCF_STEP = Step(
    name="nscf",
    executable="pw.x",
    args=("-npool", "4", "-in", "nscf.in"),
    files={"nscf.in": "&CONTROL\n/\n"},
    stdout="nscf.out",
    completion=ExitStatusCheck(_SCHEMA),
)
_DOS_STEP = Step(
    name="dos",
    executable="dos.x",
    args=("-in", "dos.in"),
    files={"dos.in": "&DOS\n/\n"},
    stdout="dos.out",
    completion=StdoutMarkerCheck(),
    ntasks=1,
)


def _one_task_step(name: str, executable: str) -> Step:
    """A program on one task, passed by JOB DONE, as dos.x and bands.x are."""
    return replace(
        _DOS_STEP,
        name=name,
        executable=executable,
        args=("-in", f"{name}.in"),
        files={f"{name}.in": "&INPUT\n/\n"},
        stdout=f"{name}.out",
    )


_BANDS_STEP = replace(
    _NSCF_STEP,
    name="bands",
    args=("-npool", "4", "-in", "bands.in"),
    files={"bands.in": "&CONTROL\n/\n"},
    stdout="bands.out",
)
_RELAX_STEP = replace(
    _SCF_STEP,
    name="relax",
    args=("-npool", "4", "-in", "relax.in"),
    files={"relax.in": "&CONTROL\n/\n"},
    stdout="relax.out",
)
_PH_STEP = Step(
    name="ph",
    executable="ph.x",
    args=("-npool", "4", "-in", "ph.in"),
    files={"ph.in": "phonons on a 2x2x2 q-mesh (goldilocks)\n&INPUTPH\n/\n"},
    stdout="ph.out",
    completion=DynamicalMatricesCheck("pwscf.dyn"),
    stop_file="pwscf.EXIT",
    restart_data=("./out/_ph0", "pwscf.dyn*"),
)
_RELAX_PHONON = [
    _RELAX_STEP,
    _one_task_step("d3hess", "d3hess.x"),
    _PH_STEP,
    _one_task_step("q2r", "q2r.x"),
    _one_task_step("phonon_dos", "matdyn.x"),
    _one_task_step("dispersion", "matdyn.x"),
]
"""A relax-phonon task's steps with DFT-D3, as its writers declare them."""

_TIMER_JOB = replace(_JOB, max_seconds_by_step={}, timer_seconds=574560)
"""A job that runs a timer instead of giving its steps max_seconds shares."""


def test_renders_sbatch_directives_from_job_decision() -> None:
    script = render_slurm_script(_HPC, _JOB, "quantum_espresso", [_SCF_STEP])

    assert script.startswith("#!/bin/bash\n")
    assert "#SBATCH --partition=scarf" in script
    assert "#SBATCH --nodes=1" in script
    assert "#SBATCH --ntasks=64" in script
    assert "#SBATCH --ntasks-per-node=64" in script
    assert "#SBATCH --time=168:00:00" in script


def test_account_directive_only_emitted_when_set() -> None:
    without_account = render_slurm_script(_HPC, _JOB, "quantum_espresso", [_SCF_STEP])
    assert "--account" not in without_account

    with_account = render_slurm_script(
        _HPC, replace(_JOB, account="myproject"), "quantum_espresso", [_SCF_STEP]
    )
    assert "#SBATCH --account=myproject" in with_account


def test_loads_the_module_for_the_given_code_only() -> None:
    script = render_slurm_script(_HPC, _JOB, "quantum_espresso", [_SCF_STEP])

    assert "module load QuantumESPRESSO/7.5-foss-2025a" in script


def test_no_modules_declared_for_a_code_emits_no_module_load_line() -> None:
    script = render_slurm_script(_HPC, _JOB, "vasp", [_SCF_STEP])

    assert "module load" not in script


def test_step_launch_line_never_interprets_code_specific_args() -> None:
    script = render_slurm_script(_HPC, _JOB, "quantum_espresso", [_SCF_STEP])

    assert "srun pw.x -npool 4 -in scf.in > scf.out" in script


def test_a_step_that_declares_ntasks_runs_on_that_many_tasks() -> None:
    """#134: dos.x on all 64 tasks aborts wherever a rank owns no FFT
    plane; the pw.x step keeps the whole allocation."""
    script = render_slurm_script(_HPC, _JOB, "quantum_espresso", [_SCF_STEP, _DOS_STEP])

    lines = script.splitlines()
    assert "#SBATCH --ntasks=64" in lines
    assert "srun pw.x -npool 4 -in scf.in > scf.out" in lines
    assert "srun --nodes=1 --ntasks=1 dos.x -in dos.in > dos.out" in lines


@pytest.mark.parametrize("ntasks, nodes", [(1, 1), (64, 1), (65, 2)])
def test_a_reduced_step_spans_only_the_nodes_its_tasks_fill(
    ntasks: int, nodes: int
) -> None:
    job = replace(_JOB, nodes=2, ntasks=128)
    step = replace(_DOS_STEP, ntasks=ntasks)

    script = render_slurm_script(_HPC, job, "quantum_espresso", [step])

    expected = f"srun --nodes={nodes} --ntasks={ntasks} dos.x -in dos.in > dos.out"
    assert expected in script.splitlines()


def test_a_reduced_step_keeps_the_launchers_own_srun_options() -> None:
    hpc = replace(_HPC, launcher="srun --mpi=pmix")

    script = render_slurm_script(hpc, _JOB, "quantum_espresso", [_DOS_STEP])

    expected = "srun --mpi=pmix --nodes=1 --ntasks=1 dos.x -in dos.in > dos.out"
    assert expected in script.splitlines()


def test_a_reduced_step_on_a_non_srun_launcher_is_refused() -> None:
    """The per-step flags are srun's; other launchers still run
    whole-allocation steps."""
    hpc = replace(_HPC, name="other", launcher="mpirun")

    whole = render_slurm_script(hpc, _JOB, "quantum_espresso", [_SCF_STEP])
    assert "mpirun pw.x -npool 4 -in scf.in > scf.out" in whole.splitlines()

    with pytest.raises(SubmissionError, match=r"dos sets ntasks=1.*other.*mpirun"):
        render_slurm_script(hpc, _JOB, "quantum_espresso", [_SCF_STEP, _DOS_STEP])


def test_every_step_is_wrapped_in_the_check_its_writer_declared() -> None:
    """#129: a pw.x step fingerprints its status file before the launch
    and checks it after; dos.x is checked by its stdout marker."""
    script = render_slurm_script(
        _HPC, _JOB, "quantum_espresso", [_SCF_STEP, _NSCF_STEP, _DOS_STEP]
    )

    lines = script.splitlines()
    fingerprint = f'goldilocks_before=$(goldilocks_fingerprint "{_SCHEMA}")'
    nscf = lines.index("srun pw.x -npool 4 -in nscf.in > nscf.out")
    assert lines[nscf - 1] == fingerprint
    assert lines[nscf + 1] == (
        f'goldilocks_check_exit_status "nscf" "nscf.out" "{_SCHEMA}"'
        ' "$goldilocks_before"'
    )
    dos = lines.index("srun --nodes=1 --ntasks=1 dos.x -in dos.in > dos.out")
    assert lines[dos - 1] == "# dos"
    assert lines[dos + 1] == 'goldilocks_check_stdout_marker "dos" "dos.out" "JOB DONE"'
    assert lines.count(fingerprint) == 2
    assert script.count("goldilocks_check_exit_status() {") == 1
    assert script.count("goldilocks_check_stdout_marker() {") == 1
    assert "pwscf.xml" not in script


def test_only_the_check_functions_the_steps_use_are_emitted() -> None:
    pw_only = render_slurm_script(_HPC, _JOB, "quantum_espresso", [_SCF_STEP])
    dos_only = render_slurm_script(_HPC, _JOB, "quantum_espresso", [_DOS_STEP])

    assert "goldilocks_fingerprint() {" in pw_only
    assert "goldilocks_check_stdout_marker" not in pw_only
    assert "goldilocks_check_stdout_marker() {" in dos_only
    assert "goldilocks_fingerprint" not in dos_only
    assert "goldilocks_check_exit_status" not in dos_only


def test_workdir_emits_a_cd_before_the_status_fingerprint() -> None:
    step = replace(_SCF_STEP, args=("-in", "scf.in"), workdir="run/scf")

    script = render_slurm_script(_HPC, _JOB, "quantum_espresso", [step])

    lines = script.splitlines()
    cd_index = lines.index('cd "run/scf"')
    assert lines[cd_index + 1].startswith("goldilocks_before=$(")
    assert lines[cd_index + 2] == "srun pw.x -in scf.in > scf.out"


@pytest.mark.parametrize(
    "hours, expected", [(168.0, "168:00:00"), (1.5, "1:30:00"), (0.25, "0:15:00")]
)
def test_walltime_formatting(hours: float, expected: str) -> None:
    job = replace(_JOB, walltime_h=hours)
    script = render_slurm_script(_HPC, job, "quantum_espresso", [_SCF_STEP])

    assert f"#SBATCH --time={expected}" in script


def test_non_slurm_scheduler_is_rejected() -> None:
    hpc = HpcProfile(
        name="other",
        scheduler="pbs",
        launcher="mpirun",
        modules={},
        partitions={"main": Partition(name="main", hardware=_HARDWARE, default=True)},
    )

    with pytest.raises(SubmissionError, match="slurm"):
        render_slurm_script(hpc, _JOB, "quantum_espresso", [_SCF_STEP])


def test_no_steps_is_rejected() -> None:
    with pytest.raises(SubmissionError, match="no steps"):
        render_slurm_script(_HPC, _JOB, "quantum_espresso", [])


def test_a_phonon_script_starts_a_timer_and_guards_each_checked_step() -> None:
    """#215: the timer comes from the job, the switch from the ph step's
    restart data; ph.x's exit code survives set -e for its check."""
    script = render_slurm_script(_HPC, _TIMER_JOB, "quantum_espresso", _RELAX_PHONON)

    lines = script.splitlines()
    assert 'goldilocks_steps="relax d3hess ph q2r phonon_dos dispersion"' in lines
    assert 'goldilocks_from="${GOLDILOCKS_FROM_STEP-relax}"' in lines
    assert (
        'if [ "$goldilocks_from" = "relax" ]; then rm -rf -- ./out/_ph0 pwscf.dyn*; fi'
        in lines
    )
    assert lines.index("rm -f pwscf.EXIT") < lines.index("  sleep 574560 &")
    ph = lines.index("# ph")
    assert lines[ph : ph + 7] == [
        "# ph",
        'if [ "$goldilocks_from" = "ph" ]; then goldilocks_run=1; fi',
        'if [ "$goldilocks_run" = 1 ]; then',
        "  goldilocks_status=0",
        "  srun ph.x -npool 4 -in ph.in > ph.out || goldilocks_status=$?",
        '  goldilocks_check_ph "ph" "ph.out" "pwscf.dyn" "$goldilocks_status"',
        "fi",
    ]
    relax = lines.index("  srun pw.x -npool 4 -in relax.in > relax.out")
    assert lines[relax + 1].startswith('  goldilocks_check_exit_status "relax"')
    q2r = lines.index("  srun --nodes=1 --ntasks=1 q2r.x -in q2r.in > q2r.out")
    assert (
        lines[q2r + 1] == '  goldilocks_check_stdout_marker "q2r" "q2r.out" "JOB DONE"'
    )
    assert script.count("goldilocks_check_ph() {") == 1
    assert "max_seconds" not in script


@pytest.mark.parametrize(
    "steps",
    [
        [_SCF_STEP],
        [_SCF_STEP, _NSCF_STEP, _DOS_STEP],
        [_SCF_STEP, _BANDS_STEP, _one_task_step("bands_x", "bands.x")],
    ],
    ids=["scf", "dos", "band"],
)
def test_a_script_whose_steps_declare_no_restart_data_has_no_switch_or_timer(
    steps: list[Step],
) -> None:
    script = render_slurm_script(_HPC, _JOB, "quantum_espresso", steps)

    assert "GOLDILOCKS_FROM_STEP" not in script
    assert "goldilocks_run" not in script
    assert "EXIT" not in script
    assert "trap" not in script
    assert "stopped at max_seconds" in script


@pytest.mark.parametrize("stop_files", [(None,), ("pwscf.EXIT", "si.EXIT")])
def test_a_job_timer_needs_the_steps_to_declare_one_stop_file(
    stop_files: tuple[str | None, ...],
) -> None:
    steps = [
        replace(_PH_STEP, name=f"ph{index}", stop_file=stop_file)
        for index, stop_file in enumerate(stop_files)
    ]

    with pytest.raises(SubmissionError, match="one stop file"):
        render_slurm_script(_HPC, _TIMER_JOB, "quantum_espresso", steps)


# The generated submit.sh, run in bash against stand-in programs.

_FAKE_SRUN = """\
#!/bin/bash
# srun stand-in: drop srun's own --options, run the program on this host.
while [ $# -gt 0 ]; do
  case "$1" in
    --*) shift ;;
    *) break ;;
  esac
done
exec "$@"
"""

_FAKE_PW_X = """\
#!/bin/bash
# pw.x stand-in that ends a run the way QE 7.3 does. <name>.status holds
# the exit_status for -in <name>.in (default 0); "none" writes no status
# file, "missing" writes one without <exit_status>, and "bfgs" prints
# BFGS's failure before exit_status 3 (bfgs_module.f90:1084). A stop file
# found at the start is deleted and makes a dry run with exit_status 255
# (check_stop.f90:126-133, run_pwscf.f90:149-158). Every exit_status
# goes into out/pwscf.save/data-file-schema.xml (punch.f90:77); only
# punch('all'), after exit_status 0 or 3, copies it to out/pwscf.xml
# (punch.f90:110-120, run_pwscf.f90:197-212 and 340-354). pw.x prints
# JOB DONE and exits 0 whatever the status (stop_run.f90:48 and :65).
while [ $# -gt 0 ]; do
  if [ "$1" = "-in" ]; then name="${2%.in}"; fi
  shift
done
echo "pw.x $name" >> fake_steps
status=$(cat "$name.status" 2>/dev/null || echo 0)
if [ -f pwscf.EXIT ]; then
  rm -f pwscf.EXIT
  status=255
fi
if [ "$status" = "bfgs" ]; then
  printf '     bfgs failed after  31 scf cycles and  27 bfgs steps, %s\\n' \\
    "convergence not achieved"
  status=3
fi
runs=$(( $(cat fake_runs 2>/dev/null || echo 0) + 1 ))
echo "$runs" > fake_runs
schema=out/pwscf.save/data-file-schema.xml
mkdir -p out/pwscf.save
case "$status" in
  none) ;;
  missing) printf '<closed DATE="run %s"/>\\n' "$runs" > "$schema" ;;
  *) printf '<exit_status>%s</exit_status>\\n<closed DATE="run %s"/>\\n' \\
       "$status" "$runs" > "$schema" ;;
esac
if [ "$status" = "0" ] || [ "$status" = "3" ]; then
  cp "$schema" out/pwscf.xml
fi
if [ "$status" = "2" ]; then
  echo "     convergence NOT achieved after 80 iterations: stopping"
fi
echo "   JOB DONE."
"""

_FAKE_DOS_X = """\
#!/bin/bash
# dos.x stand-in: writes no XML; prints JOB DONE unless dos.status says
# "silent".
echo "     Program DOS"
if [ "$(cat dos.status 2>/dev/null)" != "silent" ]; then
  echo "   JOB DONE."
fi
"""

_FAKE_PH_X = """\
#!/bin/bash
# ph.x stand-in on a 2x2x2 q-mesh with three irreducible q-points. It
# writes pwscf.dyn0 (3i4 mesh, i4 count, the q-points; q_points.f90:112-124),
# opens pwscf.dyn<iq> empty after q-point iq's non-scf step (do_phonon.f90:84,
# :100; openfilq.f90:205-209) and fills it when the q-point is done, ending
# with dyndia's line of a space and 74 '*' (dyndia.f90:113-114). ph.mode
# says how the run ends:
#   done (default)       every q-point, exit 0;
#   stopped_in_nscf      pwscf.EXIT found in q-point 3's non-scf step, before
#                        pwscf.dyn3 exists, exit 0 (run_nscf.f90:121-128,
#                        stop_run.f90:64-65);
#   no_convergence       a linear system of q-point 2, exit 1 (phqscf.f90:134-136);
#   wait_for_stop_file   waits in q-point 2 until pwscf.EXIT appears, deletes
#                        it and stops, exit 1 (solve_linter.f90:578, stop_ph.f90:31-41);
#   failed_after_last_q  every q-point, then exit 1 without JOB DONE;
#   unreadable_dyn0      a pwscf.dyn0 without a q-point count, exit 0.
echo "ph.x" >> fake_steps
mode=$(cat ph.mode 2>/dev/null || echo done)
end_line=" $(printf '%74s' '' | tr ' ' '*')"
mkdir -p out/_ph0
if [ "$mode" = "unreadable_dyn0" ]; then
  printf '   2   2   2\\n****\\n' > pwscf.dyn0
  echo "   JOB DONE."
  exit 0
fi
printf '   2   2   2\\n   3\\n' > pwscf.dyn0
for iq in 1 2 3; do
  if [ "$mode:$iq" = "stopped_in_nscf:3" ]; then
    echo "     Program stopped by user request"
    echo "   JOB DONE."
    exit 0
  fi
  : > "pwscf.dyn$iq"
  case "$mode:$iq" in
    no_convergence:2)
      echo "     No convergence has been achieved "
      echo "   JOB DONE."
      exit 1 ;;
    wait_for_stop_file:2)
      waited=0
      while [ ! -f pwscf.EXIT ]; do
        if [ "$waited" -ge 300 ]; then echo "no pwscf.EXIT within 30 s"; exit 2; fi
        sleep 0.1
        waited=$((waited + 1))
      done
      rm -f pwscf.EXIT
      echo "     Program stopped by user request"
      echo "   JOB DONE."
      exit 1 ;;
  esac
  printf 'Dynamical matrix file\\n%s\\n' "$end_line" > "pwscf.dyn$iq"
done
if [ "$mode" = "failed_after_last_q" ]; then exit 1; fi
echo "   JOB DONE."
"""

_FAKE_ONE_TASK_X = """\
#!/bin/bash
# d3hess.x, q2r.x and matdyn.x stand-in: writes no XML, prints JOB DONE.
echo "$(basename "$0")" >> fake_steps
echo "   JOB DONE."
"""

_BARE_HPC = replace(_HPC, name="bare", modules={})
"""srun with no module lines, so the script runs on this host."""


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    """An empty run directory, with fake srun, pw.x, dos.x, ph.x, d3hess.x,
    q2r.x and matdyn.x first on PATH."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (
        ("srun", _FAKE_SRUN),
        ("pw.x", _FAKE_PW_X),
        ("dos.x", _FAKE_DOS_X),
        ("ph.x", _FAKE_PH_X),
        ("d3hess.x", _FAKE_ONE_TASK_X),
        ("q2r.x", _FAKE_ONE_TASK_X),
        ("matdyn.x", _FAKE_ONE_TASK_X),
    ):
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    directory = tmp_path / "run"
    directory.mkdir()
    return directory


def _submit(
    run_dir: Path,
    steps: list[Step],
    *,
    job: JobDecision = _JOB,
    from_step: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the rendered submit.sh with bash in ``run_dir``, with
    ``GOLDILOCKS_FROM_STEP`` set to ``from_step`` when given. Its output goes
    through files, so a background process it leaves cannot hold the run
    open."""
    script = render_slurm_script(_BARE_HPC, job, "quantum_espresso", steps)
    (run_dir / "submit.sh").write_text(script)
    env = {k: v for k, v in os.environ.items() if k != "GOLDILOCKS_FROM_STEP"}
    env["PATH"] = f"{run_dir.parent / 'bin'}{os.pathsep}{os.environ['PATH']}"
    if from_step is not None:
        env["GOLDILOCKS_FROM_STEP"] = from_step
    stdout, stderr = run_dir.parent / "submit.stdout", run_dir.parent / "submit.stderr"
    with stdout.open("w") as out, stderr.open("w") as err:
        result = subprocess.run(
            ["bash", "submit.sh"],
            cwd=run_dir,
            env=env,
            stdout=out,
            stderr=err,
            check=False,
            timeout=120,
        )
    return subprocess.CompletedProcess(
        result.args, result.returncode, stdout.read_text(), stderr.read_text()
    )


def _programs_run(run_dir: Path) -> list[str]:
    """The stand-ins that ran, in order."""
    log = run_dir / "fake_steps"
    return log.read_text().splitlines() if log.exists() else []


def test_an_unconverged_scf_fails_although_pw_x_printed_job_done(
    run_dir: Path,
) -> None:
    """#129: after 'convergence NOT achieved' pw.x leaves no out/pwscf.xml,
    prints JOB DONE and exits 0; only the .save schema holds exit_status 2."""
    (run_dir / "scf.status").write_text("2")

    result = _submit(run_dir, [_SCF_STEP])

    assert "JOB DONE" in (run_dir / "scf.out").read_text()
    assert not (run_dir / "out" / "pwscf.xml").exists()
    assert result.returncode == 1
    assert result.stderr == (
        "goldilocks: scf: exit_status 2 (SCF not converged), see scf.out\n"
    )


_NSTEP_REASON = (
    "exit_status 3 (ionic relaxation not converged in nstep steps, or a vc-relax"
    " that converged on its last allowed step had none left for its final scf,"
    " so its save holds the atomic starting density; raise nstep)"
)
_BFGS_REASON = (
    "exit_status 3 (BFGS stopped without converging: its trust radius fell below"
    " its minimum at two consecutive steps; raising nstep does not help, tighten"
    " conv_thr)"
)


@pytest.mark.parametrize(
    "status, reason",
    [
        ("1", "exit_status 1 (errore)"),
        ("3", _NSTEP_REASON),
        ("bfgs", _BFGS_REASON),
        ("131", "exit_status 131"),
    ],
    ids=["errore", "nstep", "bfgs", "other"],
)
def test_a_pw_x_step_that_records_a_failure_status_fails_the_job(
    run_dir: Path, status: str, reason: str
) -> None:
    (run_dir / "scf.status").write_text(status)

    result = _submit(run_dir, [_SCF_STEP])

    assert result.returncode == 1
    assert result.stderr == f"goldilocks: scf: {reason}, see scf.out\n"


def test_a_max_seconds_stop_fails_and_names_walltime_h(run_dir: Path) -> None:
    """goldilocks never renders restart_mode, so 255 names the fix rather
    than calling the step resumable."""
    (run_dir / "scf.status").write_text("255")

    result = _submit(run_dir, [_SCF_STEP])

    assert result.returncode == 1
    assert result.stderr == (
        "goldilocks: scf: exit_status 255 (stopped at max_seconds before "
        "finishing; raise walltime_h or restart from the saved data), "
        "see scf.out\n"
    )


@pytest.mark.parametrize("stale", [None, "0"])
def test_a_pw_x_step_that_writes_no_status_fails(
    run_dir: Path, stale: str | None
) -> None:
    """A status file this step did not write -- absent, or left at 0 by
    an earlier run -- is not this step's status, whatever its stdout."""
    if stale is not None:
        (run_dir / "out" / "pwscf.save").mkdir(parents=True)
        schema = f"<exit_status>{stale}</exit_status>\n"
        (run_dir / "out" / "pwscf.save" / "data-file-schema.xml").write_text(schema)
        (run_dir / "out" / "pwscf.xml").write_text(schema)
    (run_dir / "scf.status").write_text("none")

    result = _submit(run_dir, [_SCF_STEP])

    assert "JOB DONE" in (run_dir / "scf.out").read_text()
    assert result.returncode == 1
    assert result.stderr == (
        f"goldilocks: scf: pw.x wrote no status for this step ({_SCHEMA} "
        "missing or unchanged), see scf.out\n"
    )


def test_a_status_file_without_exit_status_fails(run_dir: Path) -> None:
    (run_dir / "scf.status").write_text("missing")

    result = _submit(run_dir, [_SCF_STEP])

    assert result.returncode == 1
    assert result.stderr == (
        f"goldilocks: scf: no <exit_status> in {_SCHEMA}, see scf.out\n"
    )


def test_the_second_pw_x_step_is_checked_against_its_own_status(
    run_dir: Path,
) -> None:
    """The scf's status file must not pass the nscf that follows it."""
    (run_dir / "nscf.status").write_text("none")

    result = _submit(run_dir, [_SCF_STEP, _NSCF_STEP, _DOS_STEP])

    assert result.returncode == 1
    assert result.stderr.startswith(
        "goldilocks: nscf: pw.x wrote no status for this step"
    )
    assert (run_dir / "fake_runs").read_text().strip() == "2"
    assert not (run_dir / "dos.out").exists()


def test_a_dos_x_step_without_job_done_fails(run_dir: Path) -> None:
    """dos.x writes no XML; the pw.x steps' status file must not pass it."""
    (run_dir / "dos.status").write_text("silent")

    result = _submit(run_dir, [_SCF_STEP, _NSCF_STEP, _DOS_STEP])

    assert result.returncode == 1
    assert result.stderr == "goldilocks: dos: no 'JOB DONE' in dos.out\n"


def test_a_dos_task_whose_steps_all_finish_passes(run_dir: Path) -> None:
    """Each pw.x step rewrites the status file with exit_status 0."""
    result = _submit(run_dir, [_SCF_STEP, _NSCF_STEP, _DOS_STEP])

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert (run_dir / "fake_runs").read_text().strip() == "2"
    assert "JOB DONE" in (run_dir / "dos.out").read_text()


def test_a_phonon_job_runs_its_steps_in_order(run_dir: Path) -> None:
    result = _submit(run_dir, _RELAX_PHONON, job=_TIMER_JOB)

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert _programs_run(run_dir) == [
        "pw.x relax",
        "d3hess.x",
        "ph.x",
        "q2r.x",
        "matdyn.x",
        "matdyn.x",
    ]


def test_an_unconverged_relaxation_stops_a_phonon_job_before_ph(run_dir: Path) -> None:
    """ph.x would accept the trial geometry an exit_status 3 leaves."""
    (run_dir / "relax.status").write_text("3")

    result = _submit(run_dir, _RELAX_PHONON, job=_TIMER_JOB)

    assert result.returncode == 1
    assert result.stderr == f"goldilocks: relax: {_NSTEP_REASON}, see relax.out\n"
    assert _programs_run(run_dir) == ["pw.x relax"]


def test_a_pw_x_step_stopped_in_a_timer_job_names_the_stop_file(run_dir: Path) -> None:
    (run_dir / "relax.status").write_text("255")

    result = _submit(run_dir, _RELAX_PHONON, job=_TIMER_JOB)

    assert result.returncode == 1
    assert result.stderr == (
        "goldilocks: relax: exit_status 255 (stopped through pwscf.EXIT, which the"
        " job timer creates at 95% of the walltime, before finishing; this step"
        " cannot resume, raise walltime_h), see relax.out\n"
    )


_RESUME = (
    "goldilocks: ph: resume with sbatch --export=ALL,GOLDILOCKS_FROM_STEP=ph"
    " submit.sh\n"
)


@pytest.mark.parametrize(
    "mode, reason",
    [
        (
            "stopped_in_nscf",
            "stopped by the job timer at 95% of the walltime; q-points without a"
            " complete dynamical matrix: 3 (of 3)",
        ),
        (
            "no_convergence",
            "a linear system did not converge; q-points without a complete"
            " dynamical matrix: 2 3 (of 3)",
        ),
        ("failed_after_last_q", "ph.x exited with status 1"),
        (
            "unreadable_dyn0",
            "ph.x exited with status 0; no q-point count on line 2 of pwscf.dyn0",
        ),
    ],
    ids=["stopped_in_nscf", "no_convergence", "failed_after_last_q", "unreadable_dyn0"],
)
def test_a_ph_x_step_passes_only_with_every_dynamical_matrix(
    run_dir: Path, mode: str, reason: str
) -> None:
    """ph.x stopped in a q-point's non-scf step exits with 0 before that
    q-point's file exists; q2r.x would stop on the missing file."""
    (run_dir / "ph.mode").write_text(mode)

    result = _submit(run_dir, _RELAX_PHONON, job=_TIMER_JOB)

    assert result.returncode == 1
    assert result.stderr == f"goldilocks: ph: {reason}, see ph.out\n{_RESUME}"
    assert _programs_run(run_dir)[-1] == "ph.x"


def _leave_restart_data(run_dir: Path) -> tuple[Path, Path]:
    """ph.x's recover data and a dynamical matrix from an earlier run."""
    recover = run_dir / "out" / "_ph0" / "pwscf.phsave" / "status_run.xml"
    recover.parent.mkdir(parents=True)
    recover.write_text("<status/>")
    matrix = run_dir / "pwscf.dyn5"
    matrix.write_text("Dynamical matrix file\n")
    return recover, matrix


@pytest.mark.parametrize(
    ("from_step", "programs"),
    [
        ("ph", ["ph.x", "q2r.x", "matdyn.x", "matdyn.x"]),
        ("dispersion", ["matdyn.x"]),
    ],
)
def test_goldilocks_from_step_resumes_at_a_later_step_with_its_restart_data(
    run_dir: Path, from_step: str, programs: list[str]
) -> None:
    """At ph, ph.x resumes from its recover data; at the dispersion, matdyn.x
    alone reruns on q2r.x's force constants."""
    recover, matrix = _leave_restart_data(run_dir)

    result = _submit(run_dir, _RELAX_PHONON, job=_TIMER_JOB, from_step=from_step)

    assert result.returncode == 0, result.stderr
    assert _programs_run(run_dir) == programs
    assert recover.exists()
    assert matrix.exists()


@pytest.mark.parametrize("from_step", [None, "relax"])
def test_a_run_from_the_first_step_deletes_the_restart_data(
    run_dir: Path, from_step: str | None
) -> None:
    """With recover on, ph.x would resume from another save's data: it
    compares only its flags and q-mesh (ph_restart.f90:645-653, 701-705)."""
    recover, matrix = _leave_restart_data(run_dir)

    result = _submit(run_dir, _RELAX_PHONON, job=_TIMER_JOB, from_step=from_step)

    assert result.returncode == 0, result.stderr
    assert _programs_run(run_dir)[0] == "pw.x relax"
    assert not recover.exists()
    assert not matrix.exists()


@pytest.mark.parametrize(
    "from_step", ["phonon", "ph q2r", ""], ids=["unknown", "two_steps", "empty"]
)
def test_goldilocks_from_step_must_name_one_step(run_dir: Path, from_step: str) -> None:
    """An empty value too: read as unset, it would start a fresh run that
    deletes ph.x's restart data."""
    recover, matrix = _leave_restart_data(run_dir)

    result = _submit(run_dir, _RELAX_PHONON, job=_TIMER_JOB, from_step=from_step)

    assert result.returncode == 1
    assert result.stderr == (
        f"goldilocks: GOLDILOCKS_FROM_STEP='{from_step}' is not one of this job's"
        " steps: relax d3hess ph q2r phonon_dos dispersion\n"
    )
    assert _programs_run(run_dir) == []
    assert recover.exists()
    assert matrix.exists()


def test_the_job_timer_stops_ph_x_through_the_stop_file(run_dir: Path) -> None:
    (run_dir / "ph.mode").write_text("wait_for_stop_file")

    result = _submit(run_dir, _RELAX_PHONON, job=replace(_TIMER_JOB, timer_seconds=1))

    assert result.returncode == 1
    assert result.stderr == (
        "goldilocks: ph: stopped by the job timer at 95% of the walltime; q-points"
        f" without a complete dynamical matrix: 2 3 (of 3), see ph.out\n{_RESUME}"
    )
    assert not (run_dir / "pwscf.EXIT").exists()


def test_a_stale_stop_file_is_removed_before_the_first_step(run_dir: Path) -> None:
    """pw.x would dry-run on it with exit_status 255."""
    (run_dir / "pwscf.EXIT").touch()

    result = _submit(run_dir, _RELAX_PHONON, job=_TIMER_JOB)

    assert result.returncode == 0, result.stderr
    assert not (run_dir / "pwscf.EXIT").exists()


def test_the_job_timer_is_stopped_when_the_script_ends(run_dir: Path) -> None:
    result = _submit(run_dir, [_PH_STEP], job=replace(_TIMER_JOB, timer_seconds=2))

    assert result.returncode == 0, result.stderr
    time.sleep(3)
    assert not (run_dir / "pwscf.EXIT").exists()


@pytest.mark.skipif(shutil.which("pgrep") is None, reason="needs pgrep")
def test_the_job_timer_leaves_no_process_behind(run_dir: Path) -> None:
    """The timer's sleep ends with the script, not a week later."""
    job = replace(_TIMER_JOB, timer_seconds=471053)

    assert _submit(run_dir, [_PH_STEP], job=job).returncode == 0

    for _ in range(20):
        found = subprocess.run(
            ["pgrep", "-f", "sleep 471053"], capture_output=True, check=False
        )
        if found.returncode == 1:
            break
        time.sleep(0.1)
    assert found.returncode == 1


def test_run_instructions_copy_unpack_submit_and_follow_the_steps() -> None:
    """#227: README.md said nothing on how to run a bundle. Its archive keeps
    the files at its root, the inputs name files relative to the bundle's
    directory, and a failed step leaves a goldilocks: line in SLURM's output;
    a script without restart data has no resume step."""
    text = run_instructions(_HPC, _JOB, [_SCF_STEP, _NSCF_STEP, _DOS_STEP])

    assert text.startswith("## Running it\n\n`submit.sh` is a SLURM script for")
    assert "unzip <bundle>.zip -d <run>" in text
    assert "`cd <run> && sbatch submit.sh`" in text
    assert "`scf` (`scf.out`), `nscf` (`nscf.out`), `dos` (`dos.out`)" in text
    assert "`slurm-<jobid>.out`" in text
    assert "GOLDILOCKS_FROM_STEP" not in text


@pytest.mark.parametrize(
    ("walltime_h", "said"),
    [
        (12.0, "It asks for 12 h on partition `scarf`."),
        (168.0, "the ceiling of partition `scarf`, which queues slowly"),
        (200.0, "above the 168 h ceiling of partition `scarf`"),
    ],
    ids=["below", "at", "above"],
)
def test_run_instructions_weigh_the_walltime_against_the_ceiling(
    walltime_h: float, said: str
) -> None:
    job = replace(_JOB, walltime_h=walltime_h)

    assert said in run_instructions(_HPC, job, [_SCF_STEP])


def test_run_instructions_name_the_account_or_ask_for_one() -> None:
    named = run_instructions(_HPC, replace(_JOB, account="abc123"), [_SCF_STEP])
    unnamed = run_instructions(_HPC, _JOB, [_SCF_STEP])

    assert "It charges account `abc123`." in named
    assert "if the cluster needs one, set `account`" in unnamed


def test_run_instructions_resume_at_the_later_steps_the_script_takes() -> None:
    """The resume command and step names are the script's own."""
    script = render_slurm_script(_HPC, _TIMER_JOB, "quantum_espresso", _RELAX_PHONON)
    text = run_instructions(_HPC, _TIMER_JOB, _RELAX_PHONON)

    command = "sbatch --export=ALL,GOLDILOCKS_FROM_STEP=<step> submit.sh"
    assert f"`{command}`" in text
    assert command.replace("<step>", "${step_name}") in script
    assert (
        "with `<step>` one of `d3hess`, `ph`, `q2r`, `phonon_dos`, `dispersion`" in text
    )
    assert "A plain `sbatch submit.sh` starts at `relax`" in text
