"""write_qe_phonon: the phonon tasks' ``d3hess.x``, ``ph.x``, ``q2r.x`` and
two ``matdyn.x`` inputs, the phonon DOS and the dispersion (#215).

They follow the first pw.x step (scf, relax or vc-relax) on its
``SharedContext``: d3hess.x and ph.x read its save under ``outdir`` with its
``prefix``, and every file the inputs name is the prefix's.

**ph.in** is a title line, then ``&INPUTPH``. ph.x reads the first line as
the title, into 75 characters, and takes a line containing '&inputph' for a
missing one (QE 7.3 ``PHonon/PH/phq_readin.f90:229-246``,
``Modules/run_info.f90:15``); the title names the q-mesh, in 47 characters
at most within q2r.x's 1024 divisions per axis. ``ldisp`` runs the phonons
on the Gamma-centred nq1 x nq2 x nq3 mesh of ``QSamplingDecision.mesh``,
with ``PhononDecision``'s tr2_ph, alpha_mix(1), which ph.x copies to every
iteration (``phq_setup.f90:303-305``), and nmix_ph. ``fildyn`` is
``<prefix>.dyn``, not ending in .xml, so the dynamical matrices are text
(``phq_readin.f90:870``): ``<prefix>.dyn0`` lists the q-points and
``<prefix>.dyn<n>`` holds the n-th one's matrices (``q_points.f90:112-124``,
``prepare_q.f90:124``).
``recover`` is always on: a stopped run rerun with the same input resumes
from ph.x's data under ``<outdir>/_ph0`` (``phq_readin.f90:648``,
``check_initial_status.f90:112``), and a fresh one prints 'Run is not
recoverable starting from scratch' and starts (``phq_readin.f90:655-668``).
Not written:

- ``max_seconds``: the job timer stops ph.x through ``<prefix>.EXIT``
  (``Step.stop_file``);
- ``epsil`` and ``zeu``: on a q-mesh ph.x sets them at Gamma for fixed
  occupations and clears them otherwise (``prepare_q.f90:137-180``), and
  epsil on a smeared run stops it (``phq_readin.f90:944-945``);
- ``asr``, which acts only with Gamma-Gamma tricks (``phq_readin.f90:962``),
  ``amass``, read from the save, and the k-mesh, the scf's;
- ``dftd3_hess``: its default, ``<outdir>/<prefix>.hess``
  (``phq_readin.f90:971-972``), is the file d3hess.x writes.

ph.x runs on the whole allocation with the first step's pools and
diagonalization group, without images. Its step is checked by
``steps.DynamicalMatricesCheck``, declares the job timer's stop file and
names the data a rerun resumes from (``Step.restart_data``).

**d3hess.in**, only for DFT-D3, sets the prefix and outdir alone. Its
defaults (``PP/src/d3hess.f90:49-62``) write the Hessian ph.x reads, with
q_gamma off: a Gamma-only Hessian is refused at q /= 0
(``PHonon/PH/d2ionq_disp.f90:87-88``). The Hessian has two-body terms only
(``dft-d3/dftd3_qe.f90:217``), which is why the first step then writes
``dftd3_threebody = .false.``.

**q2r.in** reads ``<prefix>.dyn0`` and the files it lists
(``PHonon/PH/do_q2r.f90:92-139``) into the force constants ``<prefix>.fc``,
with ``Q2rDecision``'s acoustic sum rule for the effective charges and, for a
slab under 2D truncation, ``loto_2d``.

**phonon_dos.in** (matdyn.x) applies the same sum rule and ``loto_2d`` to the
force constants and writes the phonon DOS on ``PhononDosDecision``'s mesh,
every ``delta_e`` cm^-1, into ``<prefix>.phdos``; degauss 0, the default,
means tetrahedra. Blank ``flfrq`` and ``flvec`` stop it writing the
frequencies and modes of every mesh point (``PHonon/PH/matdyn.f90:564-583``,
``:760-778``).

**dispersion.in** (matdyn.x) applies the same sum rule and ``loto_2d`` to the
same force constants along the path of ``DispersionSettings``, the rows of
``bands.path_rows`` after the namelist. With ``q_in_band_form`` and
``q_in_cryst_coord`` matdyn.x reads the number of rows, then each row that
starts with a digit, a sign or a dot as x y z n, ignoring the rest of the
line (``matdyn.f90:485-501``). A row starting with a letter is read as a
symbolic point, which needs an ``ibrav`` other than 0 in the force-constant
file (``:529-531``), and every cell written here has 0, so the labels stay
comments. The coordinates are taken in the reciprocal vectors of the cell
the force-constant file holds (``:538``), and the rows are expanded as pw.x
expands a K_POINTS crystal_b card, a count of 0 going straight to the next
row (``:546``, ``Modules/generate_k_along_lines.f90``). ``flfrq`` writes the
frequencies in cm^-1, negative where imaginary, to ``<prefix>.freq``, with
each point's Cartesian coordinates in 2 pi / alat, and to
``<prefix>.freq.gp`` against the length along the path, jumps included
(``:760-776``); a blank ``flvec`` leaves out the modes of every point,
5 + 3 nat (nat + 1) lines each (``:564-569``, ``:739``,
``write_eigenvectors.f90:90-108``). ``fleig`` and ``fldyn``, which write the
modes too, are left unset, and so is ``dos``, false by default. The
``.freq`` header writes the number of points with format i4 (``:762``), so
plotband.x cannot read a path of 10000 points or more; the ``.gp`` file has
no such limit.

d3hess.x, q2r.x and matdyn.x run on one MPI task. q2r.x works on its I/O rank
alone and matdyn.x repeats its whole calculation on every rank; d3hess.x
reads the save as dos.x does (``dos.py``), where a rank that owns no FFT
plane aborts. None writes a status file, so ``JOB DONE`` in its stdout
passes it. Their errors exit non-zero, so the submission script's ``set -e``
ends the job at the launch, before that check: ``errore`` writes CRASH and
stops with code 1 (``UtilXlib/error_handler.f90:90-94``), and matdyn.x opens
the force-constant file and reads each row without IOSTAT
(``matdyn.f90:917``, ``:499-500``), so a missing file or a malformed row
ends in a Fortran runtime error.
"""

from __future__ import annotations

from goldilocks_core.generation.quantum_espresso.bands import path_rows
from goldilocks_core.generation.quantum_espresso.namelists import render_namelist
from goldilocks_core.step_settings import (
    DispersionSettings,
    MatdynSettings,
    PhSettings,
    Q2rSettings,
)
from goldilocks_core.steps import (
    DynamicalMatricesCheck,
    SharedContext,
    StdoutMarkerCheck,
    Step,
)


def write_qe_phonon(
    ph: PhSettings,
    q2r: Q2rSettings,
    matdyn: MatdynSettings,
    dispersion: DispersionSettings,
    ctx: SharedContext,
    *,
    d3hess: bool,
) -> list[Step]:
    """The steps after the first pw.x step, in order: ``d3hess`` when
    ``d3hess`` (the first step writes DFT-D3), then ``ph``, ``q2r``,
    ``phonon_dos`` and ``dispersion`` (module docstring)."""
    steps = [_d3hess_step(ctx)] if d3hess else []
    return [
        *steps,
        _ph_step(ph, ctx),
        _q2r_step(q2r, ctx),
        _dos_step(matdyn, ctx),
        _dispersion_step(dispersion, ctx),
    ]


def _fildyn(ctx: SharedContext) -> str:
    """ph.x's and q2r.x's ``fildyn``."""
    return f"{ctx.prefix}.dyn"


def _flfrc(ctx: SharedContext) -> str:
    """q2r.x's and matdyn.x's force-constant file."""
    return f"{ctx.prefix}.fc"


def _d3hess_step(ctx: SharedContext) -> Step:
    """d3hess.x on the first step's save, with its defaults (module
    docstring)."""
    keywords: dict[str, object] = {"prefix": ctx.prefix, "outdir": ctx.outdir}
    namelist = render_namelist(keywords, binary="d3hess")
    return _one_task_step("d3hess", "d3hess.x", namelist)


def _ph_step(ph: PhSettings, ctx: SharedContext) -> Step:
    """ph.x on the q-mesh of ``ph``, with its stop file and the data a rerun
    resumes from (module docstring)."""
    mesh = ph.q_sampling.mesh
    keywords: dict[str, object] = {
        "outdir": ctx.outdir,
        "prefix": ctx.prefix,
        "tr2_ph": ph.phonon.tr2_ph,
        "alpha_mix(1)": ph.phonon.alpha_mix,
        "nmix_ph": ph.phonon.nmix_ph,
        "fildyn": _fildyn(ctx),
        "recover": True,
        "ldisp": True,
        "nq1": mesh[0],
        "nq2": mesh[1],
        "nq3": mesh[2],
    }
    title = f"phonons on a {'x'.join(str(n) for n in mesh)} q-mesh (goldilocks)"
    args = ["-npool", str(ph.parallel.npool)]
    if ph.parallel.ndiag is not None:
        args += ["-ndiag", str(ph.parallel.ndiag)]
    return Step(
        name="ph",
        executable="ph.x",
        args=(*args, "-in", "ph.in"),
        files={"ph.in": f"{title}\n{render_namelist(keywords, binary='ph')}"},
        stdout="ph.out",
        completion=DynamicalMatricesCheck(_fildyn(ctx)),
        stop_file=f"{ctx.prefix}.EXIT",
        restart_data=(f"{ctx.outdir}/_ph0", f"{_fildyn(ctx)}*"),
    )


def _q2r_step(q2r: Q2rSettings, ctx: SharedContext) -> Step:
    """q2r.x from ph.x's dynamical matrices to the force constants (module
    docstring)."""
    keywords: dict[str, object] = {
        "fildyn": _fildyn(ctx),
        "flfrc": _flfrc(ctx),
        "zasr": q2r.q2r.asr,
    }
    if q2r.q2r.loto_2d:
        keywords["loto_2d"] = True
    return _one_task_step("q2r", "q2r.x", render_namelist(keywords, binary="q2r"))


def _dos_step(matdyn: MatdynSettings, ctx: SharedContext) -> Step:
    """matdyn.x's phonon DOS from the force constants (module docstring)."""
    mesh = matdyn.phonon_dos.mesh
    keywords: dict[str, object] = {
        "flfrc": _flfrc(ctx),
        "asr": matdyn.q2r.asr,
        "dos": True,
        "nk1": mesh[0],
        "nk2": mesh[1],
        "nk3": mesh[2],
        "deltae": matdyn.phonon_dos.delta_e,
        "fldos": f"{ctx.prefix}.phdos",
        "flfrq": " ",
        "flvec": " ",
    }
    if matdyn.q2r.loto_2d:
        keywords["loto_2d"] = True
    namelist = render_namelist(keywords, binary="matdyn")
    return _one_task_step("phonon_dos", "matdyn.x", namelist)


def _dispersion_step(dispersion: DispersionSettings, ctx: SharedContext) -> Step:
    """matdyn.x's dispersion from the force constants, along the path's rows
    (module docstring)."""
    keywords: dict[str, object] = {
        "flfrc": _flfrc(ctx),
        "asr": dispersion.q2r.asr,
        "flfrq": f"{ctx.prefix}.freq",
        "flvec": " ",
        "q_in_band_form": True,
        "q_in_cryst_coord": True,
    }
    if dispersion.q2r.loto_2d:
        keywords["loto_2d"] = True
    rows = "\n".join(path_rows(dispersion.path))
    contents = f"{render_namelist(keywords, binary='matdyn')}{rows}\n"
    return _one_task_step("dispersion", "matdyn.x", contents)


def _one_task_step(name: str, executable: str, contents: str) -> Step:
    """The step ``name``: ``executable`` on one MPI task, reading ``<name>.in``,
    which holds ``contents``, passed by ``JOB DONE`` in ``<name>.out`` (module
    docstring)."""
    return Step(
        name=name,
        executable=executable,
        args=("-in", f"{name}.in"),
        files={f"{name}.in": contents},
        stdout=f"{name}.out",
        completion=StdoutMarkerCheck(),
        ntasks=1,
    )
