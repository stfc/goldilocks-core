from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from functools import cache, singledispatch
from pathlib import Path
from typing import Annotated, Any, get_args, get_origin, get_type_hints

import numpy as np
from pydantic import BaseModel
from pymatgen.core import Structure


@dataclass(frozen=True)
class Portable:
    """Annotated field projection used by portable document consumers.

    ``None`` omits a field; another annotation describes its serialized shape.
    The domain serializer remains responsible for producing that projection.
    """

    annotation: Any = None


@cache
def _portable_exclusions(contract: type) -> frozenset[str]:
    return frozenset(
        name
        for name, annotation in get_type_hints(contract, include_extras=True).items()
        if get_origin(annotation) is Annotated
        and any(
            isinstance(item, Portable) and item.annotation is None
            for item in get_args(annotation)[1:]
        )
    )


@singledispatch
def to_portable(value: Any) -> Any:
    """Machine-independent JSON projection of a record value, the one used
    for publication: the records of every response, CLI ``--json`` and
    ``goldilocks.json`` (#152).

    Recurses through dataclasses, pydantic models, dicts, tuples and lists.
    A dataclass drops every field its type annotates ``Portable()``
    (host-local data: filesystem paths, licence text), so the same
    computation produces the same bytes on any machine. A pymatgen
    ``Structure`` becomes its formula and atom count, a path its string, a
    numpy value a list or number. A type with a shape of its own registers
    an implementation (``inputs.structure``'s sources).
    """
    if is_dataclass(value) and not isinstance(value, type):
        excluded = _portable_exclusions(type(value))
        return {
            item.name: to_portable(getattr(value, item.name))
            for item in fields(value)
            if item.name not in excluded
        }
    return value


@to_portable.register(BaseModel)
def _to_portable_model(value: BaseModel) -> dict:
    return {
        name: to_portable(getattr(value, name)) for name in type(value).model_fields
    }


@to_portable.register(tuple)
@to_portable.register(list)
def _to_portable_sequence(value: tuple | list) -> list:
    return [to_portable(item) for item in value]


@to_portable.register(dict)
def _to_portable_dict(value: dict) -> dict:
    return {str(key): to_portable(item) for key, item in value.items()}


@to_portable.register(Path)
def _to_portable_path(value: Path) -> str:
    return str(value)


@to_portable.register(Structure)
def _to_portable_structure(value: Structure) -> dict:
    """A structure in a published record is identified by its formula and
    atom count (e.g. the simulated cell in ``records.magnetic``, #128):
    enough to see which cell an input was written for, without the full
    structure document."""
    return {"formula": value.composition.formula, "nat": len(value)}


@to_portable.register(np.ndarray)
def _to_portable_ndarray(value: np.ndarray) -> list:
    return value.tolist()


@to_portable.register(np.generic)
def _to_portable_generic(value: np.generic) -> Any:
    return value.item()
