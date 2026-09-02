from __future__ import annotations

from goldilocks_core.calculation import CalculationHints
from goldilocks_core.provenance import Provenance
from goldilocks_core.types import JsonDict

DEFAULT_CONV_THR = 1e-6
DEFAULT_MIXING_BETA = 0.4
DEFAULT_ELECTRON_MAXSTEP = 80


def advise_convergence(hints: CalculationHints) -> JsonDict:
    if (
        hints.conv_thr is not None
        or hints.mixing_beta is not None
        or hints.electron_maxstep is not None
    ):
        return {
            "conv_thr": hints.conv_thr
            if hints.conv_thr is not None
            else DEFAULT_CONV_THR,
            "provenance": Provenance(
                source="user_hint",
                reason="Use operator-provided convergence settings where supplied.",
            ),
            "mixing_beta": hints.mixing_beta
            if hints.mixing_beta is not None
            else DEFAULT_MIXING_BETA,
            "electron_maxstep": hints.electron_maxstep
            if hints.electron_maxstep is not None
            else DEFAULT_ELECTRON_MAXSTEP,
        }

    return {
        "conv_thr": DEFAULT_CONV_THR,
        "provenance": Provenance(
            source="default",
            reason="Use package default SCF convergence settings.",
        ),
        "mixing_beta": DEFAULT_MIXING_BETA,
        "electron_maxstep": DEFAULT_ELECTRON_MAXSTEP,
    }
