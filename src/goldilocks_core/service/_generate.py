"""``generate()``: the "delivery" half of the v2 orchestrator, unwrapping
one ``Advice`` into rendered ``Step``s (v2 epic 8, #8). See
``_pipeline.py`` for the ``advise()``/``generate()`` promise this splits.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from goldilocks_core.advisors.relax import RelaxOptions, VcRelaxOptions
from goldilocks_core.checks import CheckReport, Finding
from goldilocks_core.failures import ExpectedFailure
from goldilocks_core.generation.quantum_espresso.bands import write_qe_bands
from goldilocks_core.generation.quantum_espresso.relax import write_qe_relax
from goldilocks_core.generation.quantum_espresso.scf import write_qe_scf
from goldilocks_core.service._advice import Advice
from goldilocks_core.service._step_kpath import PathStepAdvice
from goldilocks_core.step_settings import PwSettings
from goldilocks_core.steps import SharedContext, Step, default_shared_context
from goldilocks_core.system_settings import SystemSettings


class AdviceIncomplete(ExpectedFailure, ValueError):
    """``generate()`` was asked to render a runnable input, but
    ``checks.check_all`` refused it. Carries the ``CheckReport``; the
    message lists each finding with its remedies as JSON override patches
    (what the MCP tools relay), and ``public_error()`` adds the findings
    themselves under ``details.findings`` (#151)."""

    kind = "advice_incomplete"

    def __init__(self, report: CheckReport) -> None:
        self.report = report
        super().__init__(
            "cannot generate a runnable input: "
            + "; ".join(_described(finding) for finding in report.blocking)
        )

    def public_error(self) -> dict[str, Any]:
        return {
            **super().public_error(),
            "details": {
                "findings": [finding.to_document() for finding in self.report.blocking]
            },
        }


def _described(finding: Finding) -> str:
    """``finding``'s message, then its remedies as override patches, null
    clearing a key."""
    if not finding.remedies:
        return finding.message
    patches = " or ".join(json.dumps(remedy) for remedy in finding.remedies)
    return f"{finding.message} Remedy overrides: {patches}."


def generate(
    advice: Advice,
    report: CheckReport,
    *,
    ctx: SharedContext | None = None,
    purpose: Literal["scf", "nscf", "bands", "relax", "vc-relax"] = "scf",
    relax: RelaxOptions | VcRelaxOptions | None = None,
    fft_grid: tuple[int, int, int] | None = None,
    dftd3_threebody: bool | None = None,
) -> tuple[Step, ...]:
    """Delivery: raises ``AdviceIncomplete`` if ``report`` is not ``ok``,
    per the "generate() refuses iff a needed field is unavailable/blocked"
    promise -- callers must call ``check(advice)`` first and are expected
    to inspect ``report.blocking`` themselves before ever reaching here
    in normal operation; this raise is the hard boundary, not the
    primary way a caller learns what is missing.

    ``purpose`` (v2 epic 9, #9): selects the writer and QE's own
    ``calculation`` value -- see ``write_qe_scf``/``write_qe_relax``/
    ``write_qe_bands``' own docstrings. ``service/_dos.py``'s nscf pass is
    the first to pass ``purpose="nscf"``. A ``"bands"`` step (#118) is
    written along its band path (``PathStepAdvice``), every other step on
    its k-mesh; each writer refuses settings without the k-points it
    renders. ``max_seconds`` is the advised step's own share of the task's
    walltime (``ResourceStepAdvice.max_seconds``, #169), ``None`` when the
    task runs a job timer instead (#215), and the scf and relaxation
    writers then write none.

    ``relax`` (v2 epic 10, #10): only ``service/_relax.py`` and
    ``service/_phonon.py`` (#215) ever pass this -- it is threaded onto
    ``PwSettings.relax`` and dispatches to ``write_qe_relax`` instead of
    ``write_qe_scf`` whenever ``purpose`` is ``"relax"``/``"vc-relax"``.
    Reusing this function rather than a parallel ``generate_relax``
    duplicating the ``SystemSettings``/``PwSettings`` construction above:
    nothing about assembling those two differs between an scf step and a
    relax step, only which writer gets called and what ``PwSettings.relax``
    holds.

    ``fft_grid`` and ``dftd3_threebody`` (#215): the phonon tasks' first
    step writes the dense FFT grid ph.x accepts as nr1-nr3 where it would
    refuse pw.x's own (``FftGridDecision.written``), and, with DFT-D3,
    ``dftd3_threebody = .false.``, so that its energy, forces and any
    relaxation use the two-body D3 of d3hess.x's Hessian. Both are stored
    on ``PwSettings``, whose ``dfpt_system_keywords`` the scf and relaxation
    writers add to ``&SYSTEM``; ``None``, every other caller's, writes
    neither.
    """
    if not report.ok:
        raise AdviceIncomplete(report)
    system = SystemSettings(
        functional=advice.system.functional.value,
        cutoffs=advice.system.cutoffs.value,
        electron_count=advice.system.electron_count.value,
        pseudopotentials=advice.system.pseudo.metadata.value,
        magnetic=advice.system.magnetic.value,
        vdw=advice.system.vdw.value,
        hubbard=advice.system.hubbard.value,
        boundary=advice.system.boundary.value,
    )
    kpoints = advice.step.kpoints
    on_path = isinstance(kpoints, PathStepAdvice)
    step_settings = PwSettings(
        occupations=kpoints.occupations.value,
        k_sampling=None if on_path else kpoints.k_sampling.value,
        k_path=kpoints.k_path.value if on_path else None,
        n_irr_k=kpoints.n_irr_k.value if kpoints.n_irr_k.ok else None,
        nbnd=kpoints.nbnd.value,
        convergence=kpoints.convergence.value,
        parallel=advice.step.resources.parallelisation.value,
        max_seconds=advice.step.resources.max_seconds,
        relax=relax,
        fft_grid=fft_grid,
        dftd3_threebody=dftd3_threebody,
    )
    shared_ctx = ctx or default_shared_context()
    if purpose == "bands":
        return tuple(write_qe_bands(system, step_settings, shared_ctx))
    writer = write_qe_relax if purpose in ("relax", "vc-relax") else write_qe_scf
    return tuple(writer(system, step_settings, shared_ctx, purpose))
