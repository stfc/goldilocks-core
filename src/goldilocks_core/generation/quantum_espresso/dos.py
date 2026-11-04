"""write_qe_dos: render one ``dos.x`` ``Step`` from resolved settings.

New in v2 (v2 epic 9, #9) -- the second Quantum ESPRESSO writer this
codebase has, and the concrete proof that ``StepSettings`` really is a
tagged union with different producers per program, not just a type that
happens to type-check (``step_settings.py``'s own acceptance bar,
goldilocks-implementation-plan.md's five-scenario table, scenario 5).

**No ``SystemSettings`` parameter, unlike ``write_qe_scf``.** ``dos.x``
reads a previous ``pw.x`` step's saved wavefunctions off ``prefix``/
``outdir`` alone -- it has no chemistry, cutoffs, or pseudopotential
awareness of its own (``step_settings.py``'s own ``DosSettings``
docstring: "no k_sampling/n_irr_k/nbnd/convergence of its own"; the same
reasoning extends one level up to the system-level facts ``pw.x``
needs and ``dos.x`` does not).

**One MPI task** (``Step.ntasks=1``) whatever the allocation, and no
``-npool``. ``dos.x`` gains nothing from more tasks and cannot tolerate
many (QE 7.3):

- it refuses pools (``PP/src/dos.f90:108-109``);
- every rank recomputes the whole DOS and only the I/O rank writes it
  (``PP/src/dos.f90:218-230``);
- ``read_file_new`` builds slab FFT descriptors unless ``-pd`` is given
  (``PW/src/data_structure.f90:74-77``), and ``FFTXlib/src/
  fft_types.f90:620-622`` aborts when a rank owns no z-plane. ``pw.x``
  avoids that abort only by switching to pencil decomposition in
  ``PW/src/setup.f90:802``, which ``dos.x`` never runs.

``-pd .true.`` would avoid the abort, but every rank would still repeat
the whole computation.

**Checked by ``JOB DONE`` in its stdout** (``Step.completion``).
``dos.x`` writes no status file. It prints ``JOB DONE`` only when it
reaches ``environment_end`` (``PP/src/dos.f90:248``), and ``errore``
exits non-zero (``UtilXlib/error_handler.f90``), which ``set -e``
catches.
"""

from __future__ import annotations

from goldilocks_core.generation.errors import GenerationError
from goldilocks_core.generation.quantum_espresso.namelists import render_namelist
from goldilocks_core.step_settings import DosSettings
from goldilocks_core.steps import SharedContext, StdoutMarkerCheck, Step


def write_qe_dos(step: DosSettings, ctx: SharedContext) -> list[Step]:
    for name, value in (("delta_e", step.delta_e), ("ngauss", step.ngauss)):
        if value is None:
            raise GenerationError(f"DosSettings.{name} is required to generate dos.in")

    keywords: dict[str, object] = {
        "prefix": ctx.prefix,
        "outdir": ctx.outdir,
        "deltae": step.delta_e,
        "ngauss": step.ngauss,
    }
    if step.emin is not None:
        keywords["emin"] = step.emin
    if step.emax is not None:
        keywords["emax"] = step.emax
    if step.broadening is not None:
        keywords["degauss"] = step.broadening

    content = render_namelist(keywords, binary="dos")

    return [
        Step(
            name="dos",
            executable="dos.x",
            args=("-in", "dos.in"),
            files={"dos.in": content},
            stdout="dos.out",
            completion=StdoutMarkerCheck(),
            ntasks=1,
        )
    ]
