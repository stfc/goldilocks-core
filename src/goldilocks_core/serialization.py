from __future__ import annotations

from dataclasses import fields, is_dataclass
from functools import singledispatch
from pathlib import Path
from typing import Any

import numpy as np
from pymatgen.core import Structure


@singledispatch
def to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {
            field.name: to_jsonable(getattr(value, field.name))
            for field in fields(value)
        }
    return value


@singledispatch
def to_portable(value: Any) -> Any:
    """Machine-independent projection of a record for publication and CLI.

    Matches :func:`to_jsonable` except where a record carries host-local data
    (filesystem paths, licence text); those are dropped or reduced so the
    same computation produces the same bytes on any machine. The archive
    manifest and CLI ``--json`` use this projection; tests and internals use
    the complete :func:`to_jsonable` form.
    """
    return to_jsonable(value)


@to_jsonable.register(tuple)
def _to_jsonable_tuple(value: tuple) -> list:
    return [to_jsonable(item) for item in value]


@to_jsonable.register(list)
def _to_jsonable_list(value: list) -> list:
    return [to_jsonable(item) for item in value]


@to_jsonable.register(dict)
def _to_jsonable_dict(value: dict) -> dict:
    return {str(key): to_jsonable(item) for key, item in value.items()}


@to_jsonable.register(Path)
def _to_jsonable_path(value: Path) -> str:
    return str(value)


@to_jsonable.register(Structure)
def _to_jsonable_structure(value: Structure) -> dict:
    return value.as_dict()


@to_jsonable.register(np.ndarray)
def _to_jsonable_ndarray(value: np.ndarray) -> list:
    return value.tolist()


@to_jsonable.register(np.generic)
def _to_jsonable_generic(value: np.generic) -> Any:
    return value.item()
