"""Scientific validation shared by pseudopotential metadata producers."""

from __future__ import annotations

import math
from numbers import Real

from goldilocks_core.functionals import normalize_functional_label


class PseudoImportError(ValueError):
    """Source files cannot form trustworthy pseudopotential metadata."""

    pass


class AmbiguousCutoffMetadata(PseudoImportError):
    """More than one recognized cutoff record describes a local UPF."""

    pass


def finite_positive_cutoff(value: object, label: str) -> float:
    """Return one finite positive cutoff without accepting booleans."""
    if (
        isinstance(value, bool)
        or not isinstance(value, Real)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise PseudoImportError(f"{label} must be finite and positive; got {value!r}")
    return float(value)


def required_functional(value: object, label: str) -> str:
    """Return one normalized functional or reject absent/unknown metadata."""
    if not isinstance(value, str):
        raise PseudoImportError(f"{label} must name a functional; got {value!r}")
    functional = normalize_functional_label(value)
    if functional is None:
        raise PseudoImportError(f"{label} must name a functional; got {value!r}")
    return functional
