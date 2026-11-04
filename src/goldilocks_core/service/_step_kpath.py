"""A bands step's electronic advice (#118): the occupations, band path, band
count and convergence of a ``pw.x`` step with ``calculation='bands'``, which
``_step.py`` composes into ``StepAdvice`` in place of ``_step_kpoints.py``'s
mesh advice. A module of its own because ``_step_kpoints.py`` is at the
import-surface ceiling (``scripts/check_complexity.py``).

A bands run reads the scf step's charge density and Fermi energy and
computes bands at a list of k-points, run as given, unreduced by symmetry
(QE 7.3 ``PW/src/setup.f90:579-585``). So the step has no mesh: its
k-points are the band path of the written cell (``advisors/k_path.py``, on
``system.cell``), every point of which counts as the step's ``n_irr_k`` for
its pools and its share of the job (``_step_resources.py``). Its occupations
follow the scf step's decision (``occupations.bands_occupations``); its band
count reads them and the step's purpose, over its task's protocol for it
(``StepProtocol.nbnd``); its convergence is the scf step's rule on the same
cell, ``conv_thr`` setting the bands run's diagonalization threshold
(``PW/src/setup.f90:374``). As in ``_step_kpoints.py``, a blocked cell
blocks the path and the convergence, and a blocked electron count the band
count.
"""

from __future__ import annotations

from dataclasses import dataclass

from goldilocks_core.advisors.convergence import ConvergenceDecision, convergence
from goldilocks_core.advisors.k_path import KPathDecision, KPathHumanInput, k_path
from goldilocks_core.advisors.nbnd import NbndDecision, nbnd
from goldilocks_core.advisors.occupations import OccupationsDecision, bands_occupations
from goldilocks_core.resolution import Blocked, FieldState, Resolved, blocked_by
from goldilocks_core.service._analysis import AnalysisFacts
from goldilocks_core.service._step_kpoints import KpointsOverrides
from goldilocks_core.service._step_protocol import StepProtocol
from goldilocks_core.service._system import SystemAdvice


@dataclass(frozen=True, slots=True)
class PathStepAdvice:
    """A bands step's advice (module docstring)."""

    occupations: FieldState[OccupationsDecision]
    k_path: FieldState[KPathDecision]
    nbnd: FieldState[NbndDecision]
    convergence: FieldState[ConvergenceDecision]

    @property
    def n_irr_k(self) -> FieldState[int]:
        """The k-points pw.x runs per spin channel: every point of the path,
        under the path's provenance; ``Blocked`` when the path is not
        resolved."""
        if not self.k_path.ok:
            return Blocked(by=blocked_by(self.k_path))
        return Resolved(self.k_path.value.n_kpoints, self.k_path.provenance)

    def field_states(self) -> tuple[FieldState[object], ...]:
        """Everything except ``occupations``/``nbnd``, which
        ``checks.check_all`` folds in itself, as for
        ``ElectronicStepAdvice``."""
        return (self.k_path, self.convergence)

    def records(self) -> dict[str, FieldState[object]]:
        return {
            "occupations": self.occupations,
            "k_path": self.k_path,
            "nbnd": self.nbnd,
            "convergence": self.convergence,
        }


def path_step_advice(
    analysis: AnalysisFacts,
    system: SystemAdvice,
    scf_occupations: FieldState[OccupationsDecision],
    overrides: KpointsOverrides,
    path_human: KPathHumanInput | None,
    protocol: StepProtocol,
) -> PathStepAdvice:
    """A bands step's advice (module docstring), after an scf step whose
    occupations are ``scf_occupations``: its band count and convergence from
    its request ``overrides`` over its task's ``protocol`` for it, its path
    spaced by ``path_human``'s ``k_path_distance``."""
    occupations_state = bands_occupations(scf_occupations)
    if system.electron_count.ok:
        nbnd_state = nbnd(
            system.electron_count.value.nelec,
            occupations_state,
            "bands",
            system.magnetic,
            overrides.nbnd,
            overrides.nbnd_llm,
            protocol=protocol.nbnd,
        )
    else:
        nbnd_state = Blocked(by=blocked_by(system.electron_count))
    if system.cell.ok:
        convergence_state = convergence(
            len(system.cell.value.structure),
            hubbard=system.hubbard,
            geometry=analysis.geometry,
            human=overrides.convergence,
            llm=overrides.convergence_llm,
        )
    else:
        convergence_state = Blocked(by=blocked_by(system.cell))
    return PathStepAdvice(
        occupations=occupations_state,
        k_path=k_path(system.cell, path_human),
        nbnd=nbnd_state,
        convergence=convergence_state,
    )
