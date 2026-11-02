"""SLURM submission-script layout. This file makes no decisions.

New in v2 (v2 epic 7, #7); no v1 precedent (v1 never generated a
submission script at all). Where every number in the generated script
comes from -- goldilocks-core-design.md:1297-1310's own signpost,
translated:

    nodes / ntasks / walltime / partition  <- advisors/job_resources.py
    and the job timer                          (the task's one allocation)
    npool / ndiag / nimage                 <- advisors/parallelisation.py
                                               (already baked into Step.args)
    which programs run, in what order,     <- generation/<code>/<task>.py's
    on how many tasks, how each step's         produced Step sequence
    completion is checked, which file          (Step.ntasks, Step.completion,
    stops it, what it resumes from             Step.stop_file,
                                               Step.restart_data)
    module load / launcher / partition
    defaults                               <- inputs/profiles/<machine>.toml

This file only lays out SBATCH and launch-line syntax.

**The job sets the allocation; each step sets its own launch shape.**
A step with ``Step.ntasks=None`` runs on the whole allocation through
the bare profile launcher -- the task count ``pw.x``'s ``-npool``/
``-ndiag`` are computed for. A step that declares ``ntasks=N`` runs as
``srun --nodes=ceil(N / ntasks_per_node) --ntasks=N``, so no step
inherits an allocation its program cannot use (``dos.x`` and ``bands.x``
run on one task; see ``generation/quantum_espresso/dos.py`` and
``bands.py``). Those flags are
srun's: such a step on a profile whose launcher is not ``srun`` raises
``SubmissionError`` rather than guessing another launcher's syntax.

**Scheduler-only, not code-aware, except for one lookup and the
completion checks below.** goldilocks-core-design.md:1249-1259:
code-specific parallel flags (QE's ``-npool``/``-ndiag`` on the command
line; VASP's ``NPAR``/``KPAR``/``NCORE`` written into ``INCAR`` instead)
are already packed into ``Step.args``/``Step.files`` by the
``generation/<code>/`` writer that produced them -- this module never
inspects or interprets either, so the same ``render_slurm_script``
schedules QE and VASP steps identically. The one lookup is ``code``,
taken as an explicit parameter purely to select ``hpc.modules[code]`` --
which software module to load is a deployment fact about the HPC
profile, not a property of how a ``Step`` is invoked, so it does not
belong on ``Step`` itself.

**Every step is followed by the completion check its writer declared**
(``Step.completion``); a failed check stops the script with a
``goldilocks:`` line on stderr. ``set -e`` alone cannot see a QE program
fail: built without ``__RETURN_EXIT_STATUS``, ``do_stop`` is a bare
``STOP`` (QE 7.3 ``PW/src/stop_run.f90:65``), and ``stop_run`` prints
``JOB DONE.`` through ``environment_end`` whatever the outcome
(``stop_run.f90:48``, ``Modules/environment.f90:165``). ``pw.x``'s real
status is the ``<exit_status>`` it writes into
``<outdir>/<prefix>.save/data-file-schema.xml`` on every ``punch``
(``PW/src/punch.f90:77``): 0 finished, 1 ``errore``, 2 SCF not
converged, 3 ionic relaxation not converged, 255 stopped by
``max_seconds`` or a stop file (``PW/src/run_pwscf.f90:17-28``). Only
``punch('all')`` copies it to ``<outdir>/<prefix>.xml``
(``punch.f90:110-120``), and a non-converged or stopped run calls
``punch('config')`` (``run_pwscf.f90:197-212``), so that copy is
missing, or an earlier step's, exactly when the step failed.

- ``ExitStatusCheck`` (``pw.x``): ``goldilocks_fingerprint`` takes the
  status file's ``cksum`` before the launch line, and
  ``goldilocks_check_exit_status`` passes the step only if the file
  exists, has changed, and records exit_status 0. An unchanged file is
  an earlier step's; deleting it first is not an option, because the
  nscf and bands steps read the scf's ``.save``. ``JOB DONE`` never passes
  a ``pw.x`` step. An exit_status 3 is reported as a BFGS failure when
  the stdout says 'bfgs failed' (its history was reset at two consecutive
  steps, ``Modules/bfgs_module.f90:366-372``, ``:1084``), which more steps
  do not fix; otherwise as nstep running out, which also covers a
  vc-relax that converged on its last allowed step and had none left for
  its final scf, so its save holds the atomic starting density
  (``run_pwscf.f90:177``, ``:372-413``).
- ``StdoutMarkerCheck`` (``dos.x``, ``bands.x``, ``d3hess.x``, ``q2r.x``
  and ``matdyn.x``, which write no status file):
  ``goldilocks_check_stdout_marker`` passes the step only if its stdout
  contains the marker.
- ``DynamicalMatricesCheck`` (``ph.x``): the launch line keeps ph.x's
  exit code (``|| goldilocks_status=$?``), since ph.x stopped in its
  linear response or on a linear system that did not converge exits
  with 1 after ``JOB DONE``, and ``set -e`` would end the script without
  a reason. ``goldilocks_check_ph`` passes the step only if the code is
  0, line 2 of ``<fildyn>0`` gives the number N of q-points, and each of
  ``<fildyn>1`` to ``<fildyn>N`` ends with dyndia's line of a space and
  74 '*' (``steps.DynamicalMatricesCheck``): ph.x stopped in a q-point's
  non-scf step exits with 0 before that q-point's file exists.
  Otherwise it names the stop ph.x printed ('Program stopped by user
  request', which the job timer causes, or 'No convergence has been
  achieved', ``PHonon/PH/phqscf.f90:135``) or its exit code, and the
  q-points without a matrix, and prints the ``sbatch`` line that resumes
  the job at the step.

Only the functions the steps use are emitted. A QE build with
``__RETURN_EXIT_STATUS`` exits non-zero on 2, 3 and 255, so ``set -e``
stops the script before the check runs; the job still fails.

**One job for all steps; ``job_resources`` splits its walltime or sets
a timer.** ``JobDecision`` is the task's one job, sized over every
step's estimate, and ``max_seconds_by_step`` gives each ``pw.x`` step a
share of 95% of the walltime in proportion to its estimated workload
(goldilocks-core-design.md:1226-1237's size-weighted split; see
``advisors/job_resources.py``). Each share is written into that step's
input by ``generation/quantum_espresso/scf.py``, not here: baking it in
at generation time keeps the published manifest's sha256 describing the
bytes actually run. ``dos.x`` and ``bands.x`` have no ``max_seconds`` and
run in the remaining 5% or more.

A job with ``JobDecision.timer_seconds`` gives no step a share. Its
script deletes the one ``Step.stop_file`` the steps declare, since
pw.x dry-runs on a stale one with exit_status 255
(``run_pwscf.f90:149-158``), and starts a timer that creates it in the
working directory ``timer_seconds`` after the start; pw.x and ph.x look
for it there first, delete it and stop cleanly
(``Modules/check_stop.f90:124-133``), so each step can use the time the
steps before it left. The timer is a subshell waiting on a background
``sleep``: the script's EXIT trap sends it TERM, which interrupts the
wait at once, and its own trap kills the sleep with SIGKILL, since a TERM
reaching a ``sleep`` that is still starting is lost; a job that ends
before its timer fires so leaves no stop file and no process behind.
d3hess.x, q2r.x and matdyn.x never look for the file: one created while
they run is left to the next pw.x or ph.x step, or to the next job's
deletion. In a timer job exit_status 255 names the stop file and
walltime_h: a pw.x step stopped there cannot resume.

**The resume switch.** When a step declares ``Step.restart_data``,
``GOLDILOCKS_FROM_STEP`` names the step the job starts at, the first when
it is unset. A set value must equal a step name, or the script exits 1
listing them before it deletes anything; an empty value is refused too,
not read as a fresh run. Every step before the named one is skipped. A
run that starts at the first step deletes every declared ``restart_data``
first: that data belongs to the save the first step rewrites, and ph.x's
``recover`` checks only its flags and q-mesh against it
(``PHonon/PH/ph_restart.f90:645-653``, ``:701-705``). A ``*`` in an entry
is a shell glob; the rest is quoted.
"""

from __future__ import annotations

import math
import shlex

from goldilocks_core.advisors.job_resources import JobDecision
from goldilocks_core.inputs.hpc import HpcProfile
from goldilocks_core.steps import (
    DynamicalMatricesCheck,
    ExitStatusCheck,
    StdoutMarkerCheck,
    Step,
)
from goldilocks_core.submission.errors import SubmissionError
from goldilocks_core.types import CodeName

_EXIT_STATUS_HEAD = """\
goldilocks_fingerprint() {
  if [ -f "$1" ]; then cksum < "$1"; fi
  return 0
}

goldilocks_check_exit_status() {
  step_name="$1"; stdout_file="$2"; status_file="$3"; before="$4"
  after=$(goldilocks_fingerprint "$status_file")
  if [ -z "$after" ] || [ "$after" = "$before" ]; then
    reason="pw.x wrote no status for this step (${status_file} missing or unchanged)"
  else
    status=$(grep -o '<exit_status>[0-9]*</exit_status>' "$status_file" \\
      | grep -o '[0-9][0-9]*' || true)
    case "$status" in
      0) return 0 ;;
      "") reason="no <exit_status> in ${status_file}" ;;
      1) reason="exit_status 1 (errore)" ;;
      2) reason="exit_status 2 (SCF not converged)" ;;
      3) if grep -qF 'bfgs failed' "$stdout_file"; then
           reason="exit_status 3 (BFGS stopped without converging: its trust radius"
           reason="$reason fell below its minimum at two consecutive steps; raising"
           reason="$reason nstep does not help, tighten conv_thr)"
         else
           reason="exit_status 3 (ionic relaxation not converged in nstep steps, or"
           reason="$reason a vc-relax that converged on its last allowed step had none"
           reason="$reason left for its final scf, so its save holds the atomic"
           reason="$reason starting density; raise nstep)"
         fi ;;
"""

_EXIT_255_MAX_SECONDS = """\
      255) reason="exit_status 255 (stopped at max_seconds before finishing;"
           reason="$reason raise walltime_h or restart from the saved data)" ;;
"""

_EXIT_255_TIMER = """\
      255) reason="exit_status 255 (stopped through {stop_file}, which the job timer"
           reason="$reason creates at 95% of the walltime, before finishing; this"
           reason="$reason step cannot resume, raise walltime_h)" ;;
"""

_EXIT_STATUS_TAIL = """\
      *) reason="exit_status ${status}" ;;
    esac
  fi
  echo "goldilocks: ${step_name}: ${reason}, see ${stdout_file}" >&2
  exit 1
}
"""

_STDOUT_MARKER_FUNCTION = """\
goldilocks_check_stdout_marker() {
  step_name="$1"; stdout_file="$2"; marker="$3"
  if ! grep -qF -- "$marker" "$stdout_file"; then
    echo "goldilocks: ${step_name}: no '${marker}' in ${stdout_file}" >&2
    exit 1
  fi
}
"""

_DYNAMICAL_MATRICES_FUNCTION = """\
goldilocks_check_ph() {
  step_name="$1"; stdout_file="$2"; fildyn="$3"; exit_code="$4"
  end_line="@DYNDIA_END@"
  count=$(sed -n 2p "${fildyn}0" 2>/dev/null | tr -d ' ')
  case "$count" in
    ""|*[!0-9]*) missing="no q-point count on line 2 of ${fildyn}0" ;;
    *)
      missing=""
      iq=1
      while [ "$iq" -le "$count" ]; do
        if [ "$(tail -n 1 "${fildyn}${iq}" 2>/dev/null)" != "$end_line" ]; then
          missing="${missing} ${iq}"
        fi
        iq=$((iq + 1))
      done
      if [ -n "$missing" ]; then
        missing="q-points without a complete dynamical matrix:${missing} (of ${count})"
      fi ;;
  esac
  if [ "$exit_code" = 0 ] && [ -z "$missing" ]; then
    return 0
  fi
  if grep -qF 'Program stopped by user request' "$stdout_file"; then
    reason="stopped by the job timer at 95% of the walltime"
  elif grep -qF 'No convergence has been achieved' "$stdout_file"; then
    reason="a linear system did not converge"
  else
    reason="ph.x exited with status ${exit_code}"
  fi
  if [ -n "$missing" ]; then reason="${reason}; ${missing}"; fi
  echo "goldilocks: ${step_name}: ${reason}, see ${stdout_file}" >&2
  echo "goldilocks: ${step_name}: resume with" \\
    "sbatch --export=ALL,GOLDILOCKS_FROM_STEP=${step_name} submit.sh" >&2
  exit 1
}
""".replace("@DYNDIA_END@", " " + "*" * 74)
"""``goldilocks_check_ph``; ``@DYNDIA_END@`` becomes the line dyndia writes
last into a q-point's file, a space and 74 '*' (QE 7.3
``PHonon/PH/dyndia.f90:113-114``)."""


def render_slurm_script(
    hpc: HpcProfile,
    job: JobDecision,
    code: CodeName,
    steps: list[Step],
) -> str:
    """The submit.sh that runs ``steps`` in order in ``job``'s allocation,
    each followed by its completion check, with the resume switch when a
    step declares restart data and the timer when the job sets one
    (module docstring). Raises ``SubmissionError`` for a profile that is
    not SLURM, no steps, or a timer without exactly one declared stop
    file."""
    if hpc.scheduler != "slurm":
        raise SubmissionError(
            f"hpc profile {hpc.name!r} does not use slurm (scheduler={hpc.scheduler!r})"
        )
    if not steps:
        raise SubmissionError("no steps to submit")
    stop_file = None if job.timer_seconds is None else _stop_file(steps)
    resumable = any(step.restart_data for step in steps)

    lines = ["#!/bin/bash", *_sbatch_directives(job)]
    lines += ["", "set -e", ""]
    lines += [f"module load {module}" for module in hpc.modules.get(code, ())]
    for function in _check_functions(steps, stop_file):
        lines += ["", function.rstrip("\n")]
    if resumable:
        lines += ["", *_resume_switch(steps)]
    if stop_file is not None:
        lines += ["", *_timer(job.timer_seconds, stop_file)]
    for step in steps:
        lines += ["", *_step_lines(hpc, job, step, guarded=resumable)]
    return "\n".join(lines) + "\n"


def run_instructions(hpc: HpcProfile, job: JobDecision, steps: list[Step]) -> str:
    """How to run the script ``render_slurm_script`` writes for the same
    ``hpc``, ``job`` and ``steps``, as the bundle's ``README.md`` section
    (#227): copy, unpack, check the request, submit from the bundle's
    directory, follow each step's output, and resume where the script can.
    One text for an archive and a directory bundle, whose bytes match."""
    ceiling = hpc.partition(job.partition).hardware.max_walltime_h
    if job.walltime_h > ceiling:
        walltime = (
            f"It asks for {job.walltime_h:g} h, above the {ceiling:g} h ceiling of "
            f"partition `{job.partition}`, which the scheduler will likely refuse."
        )
    elif job.walltime_h == ceiling:
        walltime = (
            f"It asks for {job.walltime_h:g} h, the ceiling of partition "
            f"`{job.partition}`, which queues slowly: set `walltime_h` to the "
            "time the run needs and generate it again."
        )
    else:
        walltime = f"It asks for {job.walltime_h:g} h on partition `{job.partition}`."
    account = (
        f"It charges account `{job.account}`."
        if job.account is not None
        else "It names no account: if the cluster needs one, set `account` and "
        "generate it again."
    )
    outputs = ", ".join(f"`{step.name}` (`{step.stdout}`)" for step in steps)
    lines = [
        "## Running it",
        "",
        f"`submit.sh` is a SLURM script for the `{hpc.name}` profile.",
        "",
        "1. Copy the bundle to a work directory on the cluster, for example "
        "`scp <bundle>.zip <user>@<login node>:<work directory>/`, or "
        "`rsync -a <bundle>/ <user>@<login node>:<work directory>/<run>/` for "
        "a directory.",
        "2. Unpack a `.zip` bundle into a directory of its own, since its files "
        "sit at the archive's root: `mkdir <run> && unzip <bundle>.zip -d <run>`. "
        "A directory bundle is already unpacked.",
        f"3. Check the request at the top of `submit.sh`. {walltime} {account}",
        "4. Submit it from a login session in that directory, since the inputs "
        "name their files relative to it: `cd <run> && sbatch submit.sh`.",
        "5. Follow it with `squeue -u $USER`. The steps run in this order, each "
        f"writing its output to its own file: {outputs}. A step that fails stops "
        "the job with a `goldilocks: <step>: <reason>` line in "
        "`slurm-<jobid>.out`.",
    ]
    if any(step.restart_data for step in steps):
        later = ", ".join(f"`{step.name}`" for step in steps[1:])
        lines.append(
            "6. To start again at a later step, after one fails or is stopped: "
            "`sbatch --export=ALL,GOLDILOCKS_FROM_STEP=<step> submit.sh`, with "
            f"`<step>` one of {later}. A plain `sbatch submit.sh` starts at "
            f"`{steps[0].name}` and deletes the data the later steps resume from."
        )
    return "\n".join(lines) + "\n"


def _sbatch_directives(job: JobDecision) -> list[str]:
    directives = [
        f"#SBATCH --partition={job.partition}",
        f"#SBATCH --nodes={job.nodes}",
        f"#SBATCH --ntasks={job.ntasks}",
        f"#SBATCH --ntasks-per-node={job.ntasks_per_node}",
        f"#SBATCH --time={_format_walltime(job.walltime_h)}",
    ]
    if job.account is not None:
        directives.append(f"#SBATCH --account={job.account}")
    return directives


def _format_walltime(hours: float) -> str:
    total_seconds = round(hours * 3600)
    whole_hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{whole_hours}:{minutes:02d}:{seconds:02d}"


def _stop_file(steps: list[Step]) -> str:
    """The stop file a job timer creates: the one ``Step.stop_file`` the
    steps declare. Raises ``SubmissionError`` for none or several."""
    declared = sorted({step.stop_file for step in steps} - {None})
    if len(declared) != 1:
        raise SubmissionError(
            "a job timer needs the steps to declare one stop file, not "
            f"{len(declared)} ({', '.join(declared) or 'none'})"
        )
    return declared[0]


def _check_functions(steps: list[Step], stop_file: str | None) -> list[str]:
    """The shell functions the steps' ``CompletionCheck`` kinds call, each
    once; exit_status 255 names ``stop_file`` in a timer job and
    ``max_seconds`` otherwise."""
    exit_255 = (
        _EXIT_255_MAX_SECONDS
        if stop_file is None
        else _EXIT_255_TIMER.format(stop_file=stop_file)
    )
    functions = {
        ExitStatusCheck: _EXIT_STATUS_HEAD + exit_255 + _EXIT_STATUS_TAIL,
        StdoutMarkerCheck: _STDOUT_MARKER_FUNCTION,
        DynamicalMatricesCheck: _DYNAMICAL_MATRICES_FUNCTION,
    }
    used = {type(step.completion) for step in steps}
    return [function for kind, function in functions.items() if kind in used]


def _resume_switch(steps: list[Step]) -> list[str]:
    """``GOLDILOCKS_FROM_STEP``, checked against the step names, and the
    first step's deletion of every step's ``restart_data``; the steps then
    run from ``goldilocks_run`` on (module docstring)."""
    first = steps[0].name
    names = " ".join(step.name for step in steps)
    restart_data = " ".join(
        _shell_word(entry) for step in steps for entry in step.restart_data
    )
    return [
        f'goldilocks_steps="{names}"',
        f'goldilocks_from="${{GOLDILOCKS_FROM_STEP-{first}}}"',
        "goldilocks_known=0",
        "for goldilocks_step in $goldilocks_steps; do",
        '  if [ "$goldilocks_step" = "$goldilocks_from" ]; then goldilocks_known=1; fi',
        "done",
        'if [ "$goldilocks_known" != 1 ]; then',
        "  echo \"goldilocks: GOLDILOCKS_FROM_STEP='$goldilocks_from' is not one of"
        " this job's steps: $goldilocks_steps\" >&2",
        "  exit 1",
        "fi",
        f'if [ "$goldilocks_from" = "{first}" ]; then rm -rf -- {restart_data}; fi',
        "goldilocks_run=0",
    ]


def _shell_word(entry: str) -> str:
    """``entry`` as one shell word: each ``*`` a glob, the rest quoted."""
    return "*".join(shlex.quote(part) if part else "" for part in entry.split("*"))


def _timer(seconds: int, stop_file: str) -> list[str]:
    """The job timer (module docstring): ``stop_file`` deleted, then created
    ``seconds`` later unless the script has ended."""
    path = shlex.quote(stop_file)
    return [
        f"rm -f {path}",
        "( trap 'kill -KILL %1 2>/dev/null; exit' TERM",
        f"  sleep {seconds} &",
        f"  wait %1 && touch {path} ) &",
        "goldilocks_timer=$!",
        "trap 'kill \"$goldilocks_timer\" 2>/dev/null || true' EXIT",
    ]


def _step_lines(
    hpc: HpcProfile, job: JobDecision, step: Step, *, guarded: bool
) -> list[str]:
    """``step``'s block: its launch line inside its completion check, run
    only from ``GOLDILOCKS_FROM_STEP``'s step on when ``guarded``."""
    body = [] if step.workdir is None else [f'cd "{step.workdir}"']
    command = " ".join([*_launcher(hpc, job, step), step.executable, *step.args])
    body += _checked_launch(step, f"{command} > {step.stdout}")
    if not guarded:
        return [f"# {step.name}", *body]
    return [
        f"# {step.name}",
        f'if [ "$goldilocks_from" = "{step.name}" ]; then goldilocks_run=1; fi',
        'if [ "$goldilocks_run" = 1 ]; then',
        *(f"  {line}" for line in body),
        "fi",
    ]


def _checked_launch(step: Step, launch: str) -> list[str]:
    """``launch`` with the lines that check ``step`` finished: an
    ``ExitStatusCheck`` fingerprints the status file before the launch and
    reads it after; a ``StdoutMarkerCheck`` greps the stdout after; a
    ``DynamicalMatricesCheck`` keeps the exit code past ``set -e`` and
    checks it and the dynamical matrices after."""
    name, stdout, completion = step.name, step.stdout, step.completion
    if isinstance(completion, StdoutMarkerCheck):
        marker = completion.marker
        return [
            launch,
            f'goldilocks_check_stdout_marker "{name}" "{stdout}" "{marker}"',
        ]
    if isinstance(completion, DynamicalMatricesCheck):
        return [
            "goldilocks_status=0",
            f"{launch} || goldilocks_status=$?",
            f'goldilocks_check_ph "{name}" "{stdout}" "{completion.fildyn}"'
            ' "$goldilocks_status"',
        ]
    status_file = completion.status_file
    return [
        f'goldilocks_before=$(goldilocks_fingerprint "{status_file}")',
        launch,
        f'goldilocks_check_exit_status "{name}" "{stdout}" "{status_file}"'
        ' "$goldilocks_before"',
    ]


def _launcher(hpc: HpcProfile, job: JobDecision, step: Step) -> list[str]:
    """The launch words before ``step``'s executable: the profile launcher
    alone for a whole-allocation step, plus srun's ``--nodes``/``--ntasks``
    for a step that declares its own ``ntasks``. Raises ``SubmissionError``
    when such a step meets a launcher that is not srun."""
    if step.ntasks is None:
        return [hpc.launcher]
    if hpc.launcher.split()[:1] != ["srun"]:
        raise SubmissionError(
            f"step {step.name} sets ntasks={step.ntasks}, but hpc profile "
            f"{hpc.name} launches with {hpc.launcher}; a per-step task count "
            "is rendered only for srun"
        )
    nodes = math.ceil(step.ntasks / job.ntasks_per_node)
    return [hpc.launcher, f"--nodes={nodes}", f"--ntasks={step.ntasks}"]
