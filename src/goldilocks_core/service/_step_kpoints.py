"""Phase 3a of the v2 orchestrator (v2 epic 8, #8): the per-step
electronic-structure advisors (occupations/k-mesh/bands/convergence) of a
step on a k-mesh, one of the ``_step*`` files ``_step.py`` composes into
``StepAdvice`` (a bands step's are ``_step_kpath.py``'s, #118) -- see
that module's own docstring on why the per-step advisor set is split
across files (the same import-surface ceiling reason ``_pseudo.py`` was
split out of ``_system.py`` for).

Ordering follows the real dependency chain (each function's own
signature, not a convention invented here): ``occupations`` before
``k_sampling`` before ``n_irr_k``; ``occupations`` reads
``system.electron_count`` for fixed occupations' parity (#138) and
resolves without it; ``nbnd`` needs its *plain* ``nelec`` (already
resolved by phase 2) so it is ``Blocked`` outright if that failed.

A step's ``KpointsOverrides`` hold request values only; its task's
protocol for it (``StepProtocol``, ``_step_protocol.py``: the dos task's
nscf mesh and occupations) reaches ``occupations``, ``k_sampling`` and
``nbnd`` as a tier of its own, below the request (#174), and can withhold
a compensated ordering's moment from ``occupations`` (the band task's scf,
#118). A phonon task's first step also has ``k_sampling`` raise its mesh
against the ph step's q-mesh, as the step's occupations require (#215).
``nbnd`` also reads the step's purpose, which words its moment warning.

**Every structural input is the simulated cell** (``system.cell``, #128):
``k_sampling`` and ``n_irr_k`` mesh its reciprocal lattice -- ``n_irr_k``
with its moments, for a spin-orbit run (#172) -- and ``convergence``
scales with its atom count, the same cell ``system.electron_count``
counted and the writer renders. A blocked cell blocks all three; there is
no fallback to the input structure.
"""

from __future__ import annotations

from dataclasses import dataclass

from goldilocks_core.advisors.convergence import (
    ConvergenceDecision,
    ConvergenceHumanInput,
    ConvergenceLlmInput,
    convergence,
)
from goldilocks_core.advisors.k_sampling import (
    KSamplingDecision,
    KSamplingHumanInput,
    KSamplingLlmInput,
    k_sampling,
)
from goldilocks_core.advisors.n_irr_k import n_irr_k
from goldilocks_core.advisors.nbnd import (
    NbndDecision,
    NbndHumanInput,
    NbndLlmInput,
    nbnd,
)
from goldilocks_core.advisors.occupations import (
    OccupationsDecision,
    OccupationsHumanInput,
    OccupationsLlmInput,
    occupations,
)
from goldilocks_core.resolution import Blocked, FieldState, blocked_by
from goldilocks_core.service._analysis import AnalysisFacts
from goldilocks_core.service._step_protocol import StepProtocol
from goldilocks_core.service._system import SystemAdvice


@dataclass(frozen=True, slots=True)
class KpointsOverrides:
    """One pw.x step's occupations, k-point, band and convergence settings;
    a bands step reads only its band and convergence settings
    (``_step_kpath.py``)."""

    occupations: OccupationsHumanInput | None = None
    occupations_llm: OccupationsLlmInput | None = None
    k_sampling: KSamplingHumanInput | None = None
    k_sampling_llm: KSamplingLlmInput | None = None
    nbnd: NbndHumanInput | None = None
    nbnd_llm: NbndLlmInput | None = None
    convergence: ConvergenceHumanInput | None = None
    convergence_llm: ConvergenceLlmInput | None = None


@dataclass(frozen=True, slots=True)
class ElectronicStepAdvice:
    occupations: FieldState[OccupationsDecision]
    k_sampling: FieldState[KSamplingDecision]
    n_irr_k: FieldState[int]
    nbnd: FieldState[NbndDecision]
    convergence: FieldState[ConvergenceDecision]

    def field_states(self) -> tuple[FieldState[object], ...]:
        """Everything except ``occupations``/``nbnd`` --
        ``checks.check_all`` folds those in itself; see its own docstring
        on why a caller must not repeat them here."""
        return (self.k_sampling, self.n_irr_k, self.convergence)

    def records(self) -> dict[str, FieldState[object]]:
        return {
            "occupations": self.occupations,
            "k_sampling": self.k_sampling,
            "n_irr_k": self.n_irr_k,
            "nbnd": self.nbnd,
            "convergence": self.convergence,
        }


def electronic_step_advice(
    analysis: AnalysisFacts,
    system: SystemAdvice,
    overrides: KpointsOverrides,
    protocol: StepProtocol,
    purpose: str,
) -> ElectronicStepAdvice:
    """One step's electronic advice from its request ``overrides`` and its
    task's ``protocol`` for it, a tier below the overrides (#174), for a
    step of ``purpose`` (``plan.PlannedStep.purpose``)."""
    occupations_state = occupations(
        analysis.is_metal,
        system.magnetic,
        system.electron_count,
        human=overrides.occupations,
        llm=overrides.occupations_llm,
        protocol=protocol.occupations,
        unpinned=protocol.unpinned_moment,
    )
    k_sampling_state, n_irr_k_state, convergence_state = _cell_sampling(
        analysis, system, occupations_state, overrides, protocol
    )

    if system.electron_count.ok:
        nbnd_state = nbnd(
            system.electron_count.value.nelec,
            occupations_state,
            purpose,
            system.magnetic,
            overrides.nbnd,
            overrides.nbnd_llm,
            protocol=protocol.nbnd,
        )
    else:
        nbnd_state = Blocked(by=blocked_by(system.electron_count))

    return ElectronicStepAdvice(
        occupations=occupations_state,
        k_sampling=k_sampling_state,
        n_irr_k=n_irr_k_state,
        nbnd=nbnd_state,
        convergence=convergence_state,
    )


def _cell_sampling(
    analysis: AnalysisFacts,
    system: SystemAdvice,
    occupations_state: FieldState[OccupationsDecision],
    overrides: KpointsOverrides,
    protocol: StepProtocol,
) -> tuple[
    FieldState[KSamplingDecision], FieldState[int], FieldState[ConvergenceDecision]
]:
    """``k_sampling``, ``n_irr_k`` and ``convergence`` on the simulated
    cell (module docstring)."""
    if not system.cell.ok:
        cause = Blocked(by=blocked_by(system.cell))
        return cause, cause, cause
    cell = system.cell.value
    k_sampling_state = k_sampling(
        analysis.is_metal,
        cell.structure,
        occupations_state,
        overrides.k_sampling,
        overrides.k_sampling_llm,
        protocol=protocol.k_sampling,
        phonon=protocol.phonon_k,
    )
    return (
        k_sampling_state,
        n_irr_k(cell, k_sampling_state),
        convergence(
            len(cell.structure),
            hubbard=system.hubbard,
            geometry=analysis.geometry,
            human=overrides.convergence,
            llm=overrides.convergence_llm,
        ),
    )
