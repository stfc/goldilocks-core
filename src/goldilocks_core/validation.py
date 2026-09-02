from __future__ import annotations

import math
from numbers import Integral, Real

from goldilocks_core.types import (
    _VALID_SMEARING_TYPES,
    _VALID_VDW_METHODS,
    KPointGrid,
)


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


def validate_positive_integer(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer; got {value!r}")


def validate_kpoint_grid(grid: object, field_name: str) -> KPointGrid:
    if not isinstance(grid, tuple | list) or len(grid) != 3:
        raise ValueError(
            f"{field_name} must contain exactly three positive integers; got {grid!r}"
        )

    for index, value in enumerate(grid):
        validate_positive_integer(value, f"{field_name}[{index}]")

    return tuple(int(value) for value in grid)


def validate_boolean(value: object, field_name: str) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean; got {value!r}")


def validate_optional_boolean(value: object, field_name: str) -> None:
    if value is not None:
        validate_boolean(value, field_name)


def validate_smearing(
    smearing_type: str | None,
    width: float | None,
    *,
    type_field: str,
    width_field: str,
) -> None:
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
        validate_finite_positive(width, width_field)


def validate_vdw_method(method: object, field_name: str) -> None:
    if not isinstance(method, str) or method not in _VALID_VDW_METHODS:
        valid = ", ".join(sorted(_VALID_VDW_METHODS))
        raise ValueError(f"{field_name} must be one of {valid}; got {method!r}")


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
