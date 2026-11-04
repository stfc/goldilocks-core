"""``StepProtocol``: a task's own defaults for one of its pw.x steps (#174).

A protocol is a tier of its own for the step it is given to: it ranks
below the request's overrides and above the ML tier, for that step only
(``advisors/k_sampling.py``, ``advisors/occupations.py``,
``advisors/nbnd.py``). Its values are not request values, so their records
read ``heuristic`` with the protocol named in ``source_note``; ``human``
only ever comes from the request. A request value replaces the protocol's
field by field: a ``shift`` alone keeps the protocol's k_distance, a
``degauss`` alone its occupations, and an ``extra_bands`` adds to its band
count. ``unpinned_moment`` sets no value: it withholds the moment a
compensated ordering would pin (#118).

``relax`` is the same kind of tier for a relaxation's ``forc_conv_thr``
(#215), which has no ML or llm tier: it ranks above QE's default, and a
request value looser than the protocol's carries the protocol's warning
(``advisors/relax.py``). ``advise_steps`` does not read it: the task
resolves the relax record itself on the step's advice (``relax_settings``,
called by ``_phonon_steps.py``) and passes the protocol there.

``phonon_k`` is not a tier (#215). It carries the q request of a phonon
task's ph step, ``None`` for the default q-mesh, and constrains the first
step's k-mesh after every tier: a mesh the request did not set is raised
against that q-mesh, and one it did set is kept, with a warning where it
falls short (``advisors/k_sampling.py``).

``job_timer`` is task-level (#215): the task's one job runs a timer in
place of every step's ``max_seconds`` share
(``advisors/job_resources.py``), so ``steps_advice`` (``_step.py``) reads
it from whichever step's protocol declares it.

A phonon task gives its first step ``phonon_k``, ``job_timer``
(``PHONON_JOB_TIMER``) and, for a relax or vc-relax, ``relax``
(``RELAX_PHONON_PROTOCOL``). ``phonon_step_protocol`` builds that protocol
per request, since ``phonon_k`` carries the request's q.

Kept apart from ``StepOverrides`` (``_step.py``), which carries request
values only and is walked into ``capabilities``' settings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from goldilocks_core.advisors.job_resources import JobTimerProtocol
from goldilocks_core.advisors.k_sampling import KSamplingProtocol, PhononKProtocol
from goldilocks_core.advisors.nbnd import NbndProtocol
from goldilocks_core.advisors.occupations import (
    OccupationsProtocol,
    UnpinnedMomentProtocol,
)
from goldilocks_core.advisors.phonon import (
    AIIDA_PROTOCOLS_CITATION,
    LOOSE_FORCE_THRESHOLD_WARNING,
)
from goldilocks_core.advisors.q_sampling import QSamplingHumanInput
from goldilocks_core.advisors.relax import RelaxProtocol


@dataclass(frozen=True, slots=True)
class StepProtocol:
    """The protocol fields a step's advisors read; ``None`` leaves that
    advisor to its own tiers, the k-mesh unconstrained for ``phonon_k``,
    and, on every step of a task, the ``max_seconds`` shares for
    ``job_timer``."""

    k_sampling: KSamplingProtocol | None = None
    occupations: OccupationsProtocol | None = None
    nbnd: NbndProtocol | None = None
    unpinned_moment: UnpinnedMomentProtocol | None = None
    phonon_k: PhononKProtocol | None = None
    relax: RelaxProtocol | None = None
    job_timer: JobTimerProtocol | None = None


_DOS_NSCF_NOTE = (
    "Protocol default for the dos task's nscf step: "
    "aiida-quantumespresso's pdos.yaml, balanced."
)

DOS_NSCF_PROTOCOL = StepProtocol(
    k_sampling=KSamplingProtocol(k_distance=0.10, note=_DOS_NSCF_NOTE),
    occupations=OccupationsProtocol(occupations="tetrahedra_opt", note=_DOS_NSCF_NOTE),
)
"""The dos task's nscf step (``service/_dos.py``), from aiida-quantumespresso's
``workflows/protocols/pdos.yaml`` "balanced" protocol (confirmed against its
source 2026-09-14): ``kpoints_distance`` 0.10 1/angstrom, against the scf
heuristic's 0.15/0.30, and ``tetrahedra_opt`` occupations, a DOS-quality
integration grid. That protocol also sets ``nosym`` for the nscf step; this
one does not, because the generated input does not write ``nosym``/``noinv``
(``generation/quantum_espresso/scf.py``), and a protocol value with no effect
on the rendered file would mislead."""

BAND_SCF_PROTOCOL = StepProtocol(
    unpinned_moment=UnpinnedMomentProtocol(
        note=(
            "Protocol default for the band task's scf step: no "
            "tot_magnetization is derived for a magnetic ordering compensated "
            "by symmetry, because bands.x stops on the two Fermi energies any "
            "tot_magnetization writes (QE 7.3 PP/src/bands.f90:114-116), and "
            "fixed occupations on a collinear run need one."
        )
    )
)
"""The band task's scf step (#118): the 0 a compensated ordering would pin
under fixed occupations (#138) is withheld, so a compensated
antiferromagnetic non-metal takes the smearing fallback
(``advisors/occupations.py``). A requested ``tot_magnetization`` is still
carried, and the gate refuses it on a collinear run, since bands.x stops on
it too (``checks.py``, rule 7)."""

_BANDS_NOTE = (
    "Protocol default for the band task's bands step: aiida-quantumespresso's "
    "bands.yaml, three times the occupied bands."
)

BANDS_PROTOCOL = StepProtocol(nbnd=NbndProtocol(factor=3.0, note=_BANDS_NOTE))
"""The band task's bands step (#118), from aiida-quantumespresso's
``workflows/protocols/pw/bands.yaml`` at 322b498e: ``nbands_factor`` 3.0 in
every protocol, which its ``PwBandsWorkChain`` turns into the band count
``advisors/nbnd.py`` computes. Its "balanced" ``bands_kpoints_distance``,
0.025 1/angstrom, is ``advisors/k_path.py``'s default distance. That
protocol also sets ``diagonalization='paro'``, ``diago_full_acc`` and
``startingpot='file'`` for the bands step; this one does not. pw.x forces
``startingpot='file'`` outside an SCF run (QE 7.3
``PW/src/input.f90:860-865``) and converges every band there (only an SCF
run's ``sum_band`` marks bands empty), and the bands step keeps pw.x's
default diagonalization."""

RELAX_PHONON_PROTOCOL = RelaxProtocol(
    forc_conv_thr=1e-4,
    note=(
        "Protocol default for the phonon tasks' relaxation: "
        "aiida-quantumespresso's pw base.yaml, balanced (fast 1e-3, stringent "
        "0.5e-4); Quantum ESPRESSO's own default is 1e-3. The phonons are "
        "computed at the relaxed geometry, and leftover forces shift their "
        "frequencies."
    ),
    citations=(AIIDA_PROTOCOLS_CITATION,),
    loose_warning=LOOSE_FORCE_THRESHOLD_WARNING,
)
"""The relaxation that replaces the phonon scf in the relax-phonon and
vc-relax-phonon tasks (#215): forc_conv_thr 1e-4 Ry/Bohr, the balanced value
of aiida-quantumespresso's ``workflows/protocols/pw/base.yaml``, ten times
tighter than QE's 1e-3, which the relax and vc-relax tasks keep. DFPT takes
second derivatives at the geometry it is given, so leftover forces shift the
frequencies, soft modes most. A request value looser than 1e-4 carries
``phonon.loose_force_threshold`` (``advisors/phonon.py``)."""

PHONON_JOB_TIMER = JobTimerProtocol(
    note=(
        "Protocol default for the phonon tasks: no step writes max_seconds. "
        "The job's timer creates <prefix>.EXIT at timer_seconds, 95% of the "
        "walltime, and pw.x or ph.x, whichever is running, stops there "
        "cleanly. The memory figures are pw.x's for the first step: ph.x's own "
        "memory is not estimated, and it holds arrays that figure leaves out."
    )
)
"""The phonon tasks' job timer (#215): pw.x and ph.x stop cleanly at the
stop file the timer creates (``submission/slurm.py``), so the relaxation
takes the time it needs and ph.x the rest; a ph.x stopped there resumes from
its recover data when the job is resubmitted from its step. The job is sized
on the first step's pw.x estimate, since ph.x's memory has no estimate here;
ph.x also keeps arrays that estimate leaves out, such as the projections of
each of its k-points (QE 7.3 ``PHonon/PH/allocate_phq.f90:143-150``)."""


def phonon_step_protocol(
    first_step: Literal["scf", "relax", "vc-relax"], q: QSamplingHumanInput | None
) -> StepProtocol:
    """A phonon task's protocol for its first step, ``first_step`` (#215,
    module docstring): the k-mesh constrained by the q-mesh of ``q``, the ph
    step's q request (``None`` for the default mesh), the job timer, and,
    for a relax or vc-relax, ``RELAX_PHONON_PROTOCOL``."""
    return StepProtocol(
        phonon_k=PhononKProtocol(q),
        relax=None if first_step == "scf" else RELAX_PHONON_PROTOCOL,
        job_timer=PHONON_JOB_TIMER,
    )
