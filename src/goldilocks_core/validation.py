from __future__ import annotations

import math
from numbers import Real


def validate_finite_positive(value: Real, field_name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, Real)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(
            f"{field_name} must be a finite positive number; got {value!r}"
        )


_VALID_RELATIVISTIC_MODES: frozenset[str] = frozenset(
    {"scalar", "full", "non-relativistic"}
)


def validate_optional_nonempty_str(value: object, field_name: str) -> None:
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise ValueError(
            f"{field_name} must be a non-empty string, or None; got {value!r}"
        )


def validate_relativistic_mode(value: object, field_name: str) -> None:
    if value is not None and (
        not isinstance(value, str) or value not in _VALID_RELATIVISTIC_MODES
    ):
        valid = ", ".join(sorted(_VALID_RELATIVISTIC_MODES))
        raise ValueError(f"{field_name} must be one of {valid}, or None; got {value!r}")
