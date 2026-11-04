"""StepSettings: the typed middle layer between a planned step and a
rendered one.

New in v2 (v2 epic 6, #6); no v1 precedent. Per
goldilocks-core-design.md:1054-1253 ("generation: task decides the step
sequence"), a fully rendered ``Step`` is not enough by itself: a DOS
task's ``scf`` and ``nscf`` steps differ in grid, ``nbnd``, occupations,
and convergence threshold, and leaving that up to the writer to
improvise is exactly what "generation only translates" is supposed to
forbid. ``StepSettings`` is the resolved, ready-to-render answer for one
step -- by the time one of these is constructed, ``checks.py`` (this
epic's other deliverable) has already confirmed nothing it depends on
is ``Blocked``, so these dataclasses hold concrete values, not
``FieldState``-wrapped ones.

**Typed per program, not one class with unused fields.** An earlier
shape considered giving every step every field, leaving whatever a
given program does not use as ``None`` -- rejected
(goldilocks-core-design.md:1133-1150) because it both force-feeds
``dos.x`` fields it cannot use (``k_sampling``/``n_irr_k``/``nbnd``/
``convergence``) and has nowhere to put what ``dos.x`` actually needs
(``emin``/``delta_e``/``ngauss``). ``StepSettings`` is instead a tagged
union (``PwSettings | DosSettings | PhSettings | Q2rSettings |
MatdynSettings | DispersionSettings``), dispatched by ordinary
``isinstance``/pattern matching -- there is no shared base data class for
the union members. Resource estimates are not settings: no writer reads
one, and the job record carries pw.x's estimated memory instead
(``advisors/job_resources.py``, #148).

**Only the fields this codebase currently has a producer for are
required; every other field defaults to `None` rather than forcing a
fabricated value.** ``PwSettings``'s ``occupations``/``k_sampling``/
``n_irr_k``/``nbnd``/``convergence`` (v2 epic 6) and ``parallel``
(v2 epic 7's ``advisors/parallelisation.py``) are real types with real
producers, just still optional here because nothing has wired a full
per-step orchestration loop that constructs one of these yet (v2 epic
8). ``relax`` (v2 epic 7's ``advisors/relax.py``) has a real *type*
(``RelaxOptions | VcRelaxOptions``) with a real producer too, since v2
epic 10: ``advisors/relax.py``'s ``relax_settings()`` is called by
``service/_relax.py`` and threaded into ``generate(relax=...)``, so a
``relax``/``vc-relax`` task genuinely constructs a non-``None`` value
here today. ``DosSettings``'s fields are numbers ``service/_dos.py``
copies from the dos record. ``PhSettings``, ``Q2rSettings``,
``MatdynSettings`` and ``DispersionSettings`` (#215) came after their
producers, the q-mesh and phonon advisors (``advisors/q_sampling.py``,
``advisors/phonon.py``), so every one of their fields is required;
``service/_phonon_steps.py`` builds them from those advisors' records
(``phonon_step_settings``). Every optional field here is expected to become
required once its real producer exists -- a natural, signature-breaking
change at that point, not scope creep now.

``DosSettings`` existing as its own type with its own ``broadening``
field (QE calls this ``degauss`` too, in ``dos.x``/``projwfc.x`` --
occupation broadening in ``pw.x`` and DOS-histogram broadening in
``dos.x`` are physically unrelated numbers that happen to share a QE
keyword) is exactly what stops one value from silently doing double
duty across two different programs -- the deferred test from v2 epic 2
this epic's issue names as its item 6.
"""

from __future__ import annotations

from dataclasses import dataclass

from goldilocks_core.advisors.convergence import ConvergenceDecision
from goldilocks_core.advisors.k_path import KPathDecision
from goldilocks_core.advisors.k_sampling import KSamplingDecision
from goldilocks_core.advisors.nbnd import NbndDecision
from goldilocks_core.advisors.occupations import OccupationsDecision
from goldilocks_core.advisors.parallelisation import ParallelisationDecision
from goldilocks_core.advisors.phonon import (
    PhononDecision,
    PhononDosDecision,
    Q2rDecision,
)
from goldilocks_core.advisors.q_sampling import QSamplingDecision
from goldilocks_core.advisors.relax import RelaxOptions, VcRelaxOptions


@dataclass(frozen=True, slots=True)
class PwSettings:
    """pw.x: scf / nscf / bands / relax. ``k_sampling`` is the k-point mesh
    of an scf, nscf or relaxation step, ``k_path`` the band path of a bands
    step, which ``write_qe_bands`` writes as ``K_POINTS crystal_b`` (#118).
    ``max_seconds`` is this step's share of the task's walltime
    (``JobDecision.max_seconds_by_step``, ``advisors/job_resources.py``),
    or ``None`` when the task runs a job timer instead
    (``JobDecision.timer_seconds``, #215): ``write_qe_scf`` and
    ``write_qe_relax`` then write none, while ``write_qe_bands``, whose
    task always splits the walltime, still requires one.
    ``fft_grid`` and ``dftd3_threebody`` are the phonon tasks' first-step
    keywords (#215): ``fft_grid`` the dense FFT grid written as nr1-nr3 where
    ph.x would refuse pw.x's own (``FftGridDecision.written``,
    ``advisors/fft_grid.py``), and ``dftd3_threebody`` ``False`` for DFT-D3
    from two-body terms only, the D3 of d3hess.x's Hessian; ``None`` writes
    neither (``dfpt_system_keywords``).
    There is no ``disk_io``: QE's default always writes the status file the
    submission script checks (``steps.ExitStatusCheck``), and
    ``disk_io='none'`` would write none (``PW/src/punch.f90:60-63``)."""

    occupations: OccupationsDecision | None = None
    k_sampling: KSamplingDecision | None = None
    k_path: KPathDecision | None = None
    n_irr_k: int | None = None
    nbnd: NbndDecision | None = None
    convergence: ConvergenceDecision | None = None
    parallel: ParallelisationDecision | None = None
    max_seconds: int | None = None
    relax: RelaxOptions | VcRelaxOptions | None = None
    fft_grid: tuple[int, int, int] | None = None
    dftd3_threebody: bool | None = None

    @property
    def dfpt_system_keywords(self) -> dict[str, object]:
        """The ``&SYSTEM`` keywords of ``fft_grid`` and ``dftd3_threebody``,
        which ``scf.system_keywords`` adds to the step's pw.x input: nr1, nr2
        and nr3 together, since pw.x computes all three itself when any is 0
        (QE 7.3 ``FFTXlib/src/fft_types.f90:1078``) and otherwise uses them as
        given, for the smooth grid too when ecutrho is 4 ecutwfc
        (``PW/src/input.f90:1785-1797``); dftd3_threebody as set. ``{}`` when
        neither is set: pw.x's own grid and QE's three-body D3 terms."""
        keywords: dict[str, object] = {}
        if self.fft_grid is not None:
            keywords.update(zip(("nr1", "nr2", "nr3"), self.fft_grid, strict=True))
        if self.dftd3_threebody is not None:
            keywords["dftd3_threebody"] = self.dftd3_threebody
        return keywords


@dataclass(frozen=True, slots=True)
class DosSettings:
    """dos.x / projwfc.x: reads a previous step's wavefunctions --
    no k_sampling/n_irr_k/nbnd/convergence of its own."""

    emin: float | None = None
    emax: float | None = None
    delta_e: float | None = None
    broadening: float | None = None
    ngauss: int | None = None


@dataclass(frozen=True, slots=True)
class PhSettings:
    """ph.x: the q-point mesh it runs on (``advisors/q_sampling.py``), its
    linear-response settings (``advisors/phonon.py``) and the pools and
    diagonalization group of the first pw.x step, which it runs with. No
    ``epsil``: on a q-mesh ph.x decides it at Gamma itself (QE 7.3
    ``PHonon/PH/prepare_q.f90:137-180``)."""

    q_sampling: QSamplingDecision
    phonon: PhononDecision
    parallel: ParallelisationDecision


@dataclass(frozen=True, slots=True)
class Q2rSettings:
    """q2r.x: the acoustic sum rule it applies to the effective charges and
    the 2D non-analytic term (``advisors/phonon.py``)."""

    q2r: Q2rDecision


@dataclass(frozen=True, slots=True)
class MatdynSettings:
    """matdyn.x's phonon DOS: q2r.x's acoustic sum rule and 2D non-analytic
    term, which matdyn.x applies to the force constants, and the DOS mesh and
    energy step (``advisors/phonon.py``)."""

    q2r: Q2rDecision
    phonon_dos: PhononDosDecision


@dataclass(frozen=True, slots=True)
class DispersionSettings:
    """matdyn.x's dispersion: q2r.x's acoustic sum rule and 2D non-analytic
    term, which matdyn.x applies to the force constants, and the path it
    follows, the band path as matdyn.x reads it (``advisors/phonon.py``'s
    ``dispersion_path``)."""

    q2r: Q2rDecision
    path: KPathDecision


type StepSettings = (
    PwSettings
    | DosSettings
    | PhSettings
    | Q2rSettings
    | MatdynSettings
    | DispersionSettings
)
