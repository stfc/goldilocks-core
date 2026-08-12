"""Shared helpers for the per-stage hint views.

The narrow hint types (KmeshHints, SmearingHints, SpinHints, PseudoHints,
ConvergenceHints, VdwHints) each mirror the disjoint slice of
``CalculationHints`` one stage consumes. "Does this stage carry an operator
override?" is therefore a generic question over a hint view -- "is any field
non-None?" -- not stage-specific knowledge. The stage-specific knowledge (which
fields belong to the stage) lives in the view type itself.
"""

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
"""Any per-stage hint view a stage consumes."""


def has_hint(hints: HintView) -> bool:
    """Return whether any field of a per-stage hint view is set (non-None)."""
    return any(getattr(hints, field.name) is not None for field in fields(hints))
