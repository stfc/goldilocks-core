from __future__ import annotations

from dataclasses import fields

from goldilocks_core.contracts import (
    ConvergenceHints,
    KmeshHints,
    PseudoHints,
    SmearingHints,
    SpinHints,
    VdwHints,
)

type HintView = (
    KmeshHints | SmearingHints | SpinHints | PseudoHints | ConvergenceHints | VdwHints
)


def has_hint(hints: HintView) -> bool:
    return any(getattr(hints, field.name) is not None for field in fields(hints))
