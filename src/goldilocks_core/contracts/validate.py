"""Boundary-validation helpers for contract records."""

from __future__ import annotations

import math
from numbers import Integral, Real

from goldilocks_core.contracts.types import (
    _VALID_SMEARING_TYPES,
    _VALID_VDW_METHODS,
    KPointGrid,
)


def _validate_finite_positive(value: Real, field_name: str) -> None:
    """Require a finite number greater than zero."""
    if (
        isinstance(value, bool)
        or not isinstance(value, Real)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(
            f"{field_name} must be a finite positive number; got {value!r}"
        )


def _validate_positive_integer(value: int, field_name: str) -> None:
    """Require a positive integer without accepting booleans."""
    if isinstance(value, bool) or not isinstance(value, Integral) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer; got {value!r}")


def _validate_kpoint_grid(grid: object, field_name: str) -> KPointGrid:
    """Return an immutable grid of exactly three positive integer dimensions."""
    if not isinstance(grid, tuple | list) or len(grid) != 3:
        raise ValueError(
            f"{field_name} must contain exactly three positive integers; got {grid!r}"
        )

    for index, value in enumerate(grid):
        _validate_positive_integer(value, f"{field_name}[{index}]")

    return tuple(int(value) for value in grid)


def _validate_boolean(value: object, field_name: str) -> None:
    """Require a built-in boolean rather than a truthy value."""
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean; got {value!r}")


def _validate_optional_boolean(value: object, field_name: str) -> None:
    """Require None or a built-in boolean."""
    if value is not None:
        _validate_boolean(value, field_name)


def _validate_smearing(
    smearing_type: str | None,
    width: float | None,
    *,
    type_field: str,
    width_field: str,
) -> None:
    """Require fixed occupations without width or smearing with positive width."""
    if smearing_type is not None and (
        not isinstance(smearing_type, str) or smearing_type not in _VALID_SMEARING_TYPES
    ):
        valid = ", ".join(sorted(_VALID_SMEARING_TYPES))
        raise ValueError(
            f"{type_field} must be one of {valid}, or None; got {smearing_type!r}"
        )

    fixed_occupations = smearing_type in {None, "fixed"}
    if fixed_occupations and width is not None:
        raise ValueError(
            f"{width_field} must be None when {type_field} is {smearing_type!r}"
        )
    if not fixed_occupations and width is None:
        raise ValueError(
            f"{width_field} is required when {type_field} is {smearing_type!r}"
        )
    if width is not None:
        _validate_finite_positive(width, width_field)


def _validate_vdw_method(method: object, field_name: str) -> None:
    """Require a supported code-agnostic vdW method label."""
    if not isinstance(method, str) or method not in _VALID_VDW_METHODS:
        valid = ", ".join(sorted(_VALID_VDW_METHODS))
        raise ValueError(f"{field_name} must be one of {valid}; got {method!r}")
