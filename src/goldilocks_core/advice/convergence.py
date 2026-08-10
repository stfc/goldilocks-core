"""Convergence advice policy for the Advise stage."""

from __future__ import annotations

from goldilocks_core.advice._hints import has_hint
from goldilocks_core.contracts import (
    ConvergenceAdvice,
    ConvergenceHints,
    Provenance,
)

DEFAULT_CONV_THR = 1e-6
DEFAULT_MIXING_BETA = 0.4
DEFAULT_ELECTRON_MAXSTEP = 80


def advise_convergence(hints: ConvergenceHints) -> ConvergenceAdvice:
    """Return SCF convergence advice with user hints applied.

    ``None`` means "let Core decide"; a non-None value overrides. The
    ``is not None`` check (not ``or``) honours that contract and stays correct
    if the boundary validation ever loosens to admit falsy non-None values.
    """
    if has_hint(hints):
        return ConvergenceAdvice(
            conv_thr=hints.conv_thr if hints.conv_thr is not None else DEFAULT_CONV_THR,
            mixing_beta=hints.mixing_beta
            if hints.mixing_beta is not None
            else DEFAULT_MIXING_BETA,
            electron_maxstep=hints.electron_maxstep
            if hints.electron_maxstep is not None
            else DEFAULT_ELECTRON_MAXSTEP,
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
