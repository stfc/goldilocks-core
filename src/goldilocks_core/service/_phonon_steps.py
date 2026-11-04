"""``PhononStepsAdvice``: what a phonon task decides after its first pw.x
step's advice (#215).

A phonon task runs its first pw.x step, an scf, a fixed-cell relax or a
vc-relax, then ``d3hess.x`` for DFT-D3, ``ph.x`` on a q-point mesh,
``q2r.x``, and ``matdyn.x`` for the phonon DOS and for the dispersion, in one
job on one ``SharedContext``. The first step is advised as any pw.x step, by
``advise_steps`` under ``phonon_step_protocol`` (``_step_protocol.py``): its
k-mesh is constrained by the ph step's q-mesh, and the job runs the phonon
tasks' timer. ``phonon_steps_advice`` decides the rest on that step's
``Advice``:

- the relax record of a relax or vc-relax first step (``relax_settings``),
  with the phonon tasks' force threshold (``StepProtocol.relax``, which
  ``advise_steps`` does not read); an scf first step has none;
- the first step's dense FFT grid for ph.x (``advisors/fft_grid.py``);
- the ph step's q-point mesh (``advisors/q_sampling.py``) and its
  linear-response settings, which carry the run's notices, the q2r step's
  acoustic sum rule and the phonon_dos step's mesh (``advisors/phonon.py``);
- the dispersion step's path, the band path as matdyn.x reads it, which
  depends on the first step's occupations and the q2r record
  (``advisors/phonon.py``'s ``dispersion_path``).

Every structural input is the written cell (``system.cell``), the cell the
first step's k-mesh is constrained on, so the q-mesh decided here is the one
that k-mesh meets, and the path is the band task's on the same cell. d3hess.x
has no settings and no record: it runs exactly when the first step writes
DFT-D3, the fact the two-body notice reads.

``phonon_step_settings`` turns the resolved records into the ph.x, q2r.x and
both matdyn.x settings ``write_qe_phonon`` renders, ph.x with the first
step's pools and diagonalization group.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from goldilocks_core.advisors.fft_grid import FftGridDecision, fft_grid
from goldilocks_core.advisors.k_path import KPathDecision
from goldilocks_core.advisors.phonon import (
    PhononDecision,
    PhononDosDecision,
    Q2rDecision,
    dispersion_path,
    phonon_dos_settings,
    phonon_notices,
    phonon_settings,
    q2r_settings,
)
from goldilocks_core.advisors.q_sampling import QSamplingDecision, q_sampling
from goldilocks_core.advisors.relax import (
    RelaxOptions,
    RelaxProtocol,
    VcRelaxOptions,
    relax_settings,
)
from goldilocks_core.resolution import FieldState
from goldilocks_core.service._advice import Advice
from goldilocks_core.service._step import StepOverrides
from goldilocks_core.step_settings import (
    DispersionSettings,
    MatdynSettings,
    PhSettings,
    Q2rSettings,
)


@dataclass(frozen=True, slots=True)
class PhononStepsAdvice:
    """A phonon task's records beside its first step's advice (module
    docstring). The first step holds ``relax``, its relaxation (``None`` for
    an scf first step), and ``fft_grid``; the ph step ``q_sampling`` and
    ``phonon``, the q2r step ``q2r``, the phonon_dos step ``phonon_dos`` and
    the dispersion step ``dispersion``, its path."""

    relax: FieldState[RelaxOptions | VcRelaxOptions] | None
    fft_grid: FieldState[FftGridDecision]
    q_sampling: FieldState[QSamplingDecision]
    phonon: FieldState[PhononDecision]
    q2r: FieldState[Q2rDecision]
    phonon_dos: FieldState[PhononDosDecision]
    dispersion: FieldState[KPathDecision]

    def field_states(self) -> tuple[FieldState[object], ...]:
        """Everything except ``relax``, which ``check()`` folds in with the
        first step's advice (``_pipeline.py``)."""
        return (
            self.fft_grid,
            self.q_sampling,
            self.phonon,
            self.q2r,
            self.phonon_dos,
            self.dispersion,
        )

    def first_step_records(self) -> dict[str, FieldState[object]]:
        """The first step's records beside its own advice: ``relax``, when
        the first step relaxes, and ``fft_grid``."""
        relax = {} if self.relax is None else {"relax": self.relax}
        return {**relax, "fft_grid": self.fft_grid}

    def step_records(self) -> dict[str, dict[str, FieldState[object]]]:
        """The ph, q2r, phonon_dos and dispersion steps' records, by step, in
        run order; the dispersion's path is ``k_path``, as the band task's
        bands step publishes its own."""
        return {
            "ph": {"q_sampling": self.q_sampling, "phonon": self.phonon},
            "q2r": {"q2r": self.q2r},
            "phonon_dos": {"phonon_dos": self.phonon_dos},
            "dispersion": {"k_path": self.dispersion},
        }


def phonon_steps_advice(
    first_step: Literal["scf", "relax", "vc-relax"],
    first: Advice,
    steps: Mapping[str, StepOverrides],
    relax_protocol: RelaxProtocol | None,
) -> PhononStepsAdvice:
    """The phonon steps on ``first``, the advice of the task's first step,
    ``first_step`` (module docstring). ``steps`` holds the request's
    overrides by purpose, for ``first_step`` and the ``ph``, ``q2r``,
    ``phonon_dos`` and ``dispersion`` steps; ``relax_protocol`` is the first
    step's ``StepProtocol.relax``. ``first``
    is advised under ``phonon_step_protocol`` with the q request of
    ``steps["ph"]``, so its k-mesh meets the q-mesh decided here."""
    system = first.system
    kpoints = first.step.kpoints
    geometry = system.geometry_eff
    relax = None
    if first_step != "scf":
        relax_overrides = steps[first_step].relax
        relax = relax_settings(
            first_step,
            kpoints.convergence,
            geometry,
            relax_overrides.relax,
            relax_overrides.relax_llm,
            protocol=relax_protocol,
        )
    ph = steps["ph"].ph
    q = q_sampling(system.cell, ph.q_sampling)
    notices = phonon_notices(
        first_step,
        kpoints.occupations,
        geometry,
        system.boundary,
        system.magnetic,
        system.hubbard,
        d3=system.vdw.ok and system.vdw.value.use_vdw,
    )
    q2r = q2r_settings(system.boundary, steps["q2r"].q2r.q2r)
    return PhononStepsAdvice(
        relax=relax,
        fft_grid=fft_grid(system.cell, system.cutoffs, first_step),
        q_sampling=q,
        phonon=phonon_settings(ph.phonon, notices),
        q2r=q2r,
        phonon_dos=phonon_dos_settings(
            system.cell, steps["phonon_dos"].phonon_dos.phonon_dos
        ),
        dispersion=dispersion_path(
            system.cell,
            geometry,
            kpoints.occupations,
            q2r,
            steps["dispersion"].k_path.k_path,
        ),
    )


def phonon_step_settings(
    steps: PhononStepsAdvice, first: Advice
) -> tuple[PhSettings, Q2rSettings, MatdynSettings, DispersionSettings]:
    """The ph.x, q2r.x and both matdyn.x settings of ``steps``, ph.x with the
    pools and diagonalization group of ``first``, the first step's advice:
    what ``write_qe_phonon`` renders. Every record must be resolved, as the
    gate checks before any input is written."""
    q2r = steps.q2r.value
    return (
        PhSettings(
            q_sampling=steps.q_sampling.value,
            phonon=steps.phonon.value,
            parallel=first.step.resources.parallelisation.value,
        ),
        Q2rSettings(q2r=q2r),
        MatdynSettings(q2r=q2r, phonon_dos=steps.phonon_dos.value),
        DispersionSettings(q2r=q2r, path=steps.dispersion.value),
    )
