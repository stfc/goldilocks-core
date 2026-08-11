"""Convergence advice policy for the Advise stage."""

from __future__ import annotations

from goldilocks_core.contracts import (
    CalculationHints,
    ConvergenceAdvice,
    Provenance,
)

DEFAULT_CONV_THR = 1e-6
DEFAULT_MIXING_BETA = 0.4
DEFAULT_ELECTRON_MAXSTEP = 80


def advise_convergence(hints: CalculationHints) -> ConvergenceAdvice:
    """Return SCF convergence advice with user hints applied."""
    if _has_convergence_hint(hints):
        return ConvergenceAdvice(
            conv_thr=hints.conv_thr or DEFAULT_CONV_THR,
            mixing_beta=hints.mixing_beta or DEFAULT_MIXING_BETA,
            electron_maxstep=hints.electron_maxstep or DEFAULT_ELECTRON_MAXSTEP,
            provenance=Provenance(
                source="user_hint",
                reason="Use operator-provided convergence settings where supplied.",
            ),
        )

    return ConvergenceAdvice(
        conv_thr=DEFAULT_CONV_THR,
        mixing_beta=DEFAULT_MIXING_BETA,
        electron_maxstep=DEFAULT_ELECTRON_MAXSTEP,
        provenance=Provenance(
            source="default",
            reason="Use package default SCF convergence settings.",
        ),
    )


def _has_convergence_hint(hints: CalculationHints) -> bool:
    """Return whether any convergence-specific hint was provided."""
    return any(
        hint is not None
        for hint in (hints.conv_thr, hints.mixing_beta, hints.electron_maxstep)
    )
