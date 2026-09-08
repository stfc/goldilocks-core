from __future__ import annotations

import types
from dataclasses import fields, is_dataclass
from functools import reduce
from operator import or_
from typing import (
    Annotated,
    Any,
    Literal,
    NotRequired,
    Required,
    TypeAliasType,
    Union,
    get_args,
    get_origin,
    get_type_hints,
    is_typeddict,
)

from pydantic import BaseModel, ConfigDict, JsonValue, create_model

from goldilocks_core.io.structures import StructureInspection
from goldilocks_core.result import ComputationResult
from goldilocks_core.runtime.capabilities import Capabilities
from goldilocks_core.runtime.graph import CalculationTaskCapability
from goldilocks_core.runtime.registry import record_types_by_id
from goldilocks_core.serialization import Portable

_SERIALIZED = ConfigDict(extra="forbid")
_SERIALIZED_MODELS: dict[Any, Any] = {}
_OMIT = object()


def _serialized_annotation(annotation: Any) -> Any:
    """Project domain annotations through the same exclusions as to_portable."""
    if annotation is Any or annotation is JsonValue:
        return JsonValue
    if annotation in _SERIALIZED_MODELS:
        return _SERIALIZED_MODELS[annotation]
    if isinstance(annotation, TypeAliasType):
        return _serialized_annotation(annotation.__value__)
    origin = get_origin(annotation)
    if origin is Annotated:
        inner, *metadata = get_args(annotation)
        for item in metadata:
            if isinstance(item, Portable):
                return (
                    _OMIT
                    if item.annotation is None
                    else _serialized_annotation(item.annotation)
                )
        return _serialized_annotation(inner)
    if origin in (Required, NotRequired):
        return _serialized_annotation(get_args(annotation)[0])
    if is_typeddict(annotation) or (
        isinstance(annotation, type) and is_dataclass(annotation)
    ):
        return _serialized_model(annotation)
    if origin is None or origin is Literal:
        return annotation
    converted = tuple(_serialized_annotation(item) for item in get_args(annotation))
    if origin is tuple:
        return tuple[converted]
    if origin is list:
        return list[converted[0]]
    if origin is dict:
        return dict[converted[0], converted[1]]
    if origin in (types.UnionType, Union):
        return reduce(or_, converted)
    return annotation


def _serialized_model(
    contract: type,
    *,
    overrides: dict[str, Any] | None = None,
) -> type[BaseModel]:
    hints = get_type_hints(contract, include_extras=True)
    names = (
        hints if is_typeddict(contract) else (item.name for item in fields(contract))
    )
    definitions: dict[str, Any] = {}
    for name in names:
        hint = hints[name]
        annotation = (
            overrides[name]
            if overrides is not None and name in overrides
            else _serialized_annotation(hint)
        )
        if annotation is _OMIT:
            continue
        optional = get_origin(hint) is NotRequired or (
            is_typeddict(contract)
            and name in contract.__optional_keys__
            and get_origin(hint) is not Required
        )
        definitions[name] = (annotation, None if optional else ...)
    document = create_model(contract.__name__, __config__=_SERIALIZED, **definitions)
    if overrides is None:
        _SERIALIZED_MODELS[contract] = document
    return document


CapabilitiesDocument = _serialized_model(Capabilities)
StructureInspectionDocument = _serialized_model(StructureInspection)


def computation_result_document(
    tasks: tuple[CalculationTaskCapability, ...],
) -> type[BaseModel]:
    advertised_ids = dict.fromkeys(
        record_id
        for task in tasks
        for record_id in (
            *task["selectable_record_ids"],
            *(
                output_id
                for preset in task["presets"]
                for output_id in preset["output_record_ids"]
            ),
        )
    )
    registered_types = record_types_by_id()
    records_document = create_model(
        "Records",
        __config__=_SERIALIZED,
        **{
            record_id: (_serialized_annotation(registered_types[record_id]), None)
            for record_id in advertised_ids
        },
    )
    return _serialized_model(ComputationResult, overrides={"records": records_document})


def prepared_computation_document(
    tasks: tuple[CalculationTaskCapability, ...],
) -> type[BaseModel]:
    return create_model(
        "PreparedComputation",
        __config__=_SERIALIZED,
        result=(computation_result_document(tasks), ...),
        archive=(bytes | None, None),
    )


ErrorDocument = create_model(
    "Error",
    __config__=ConfigDict(extra="forbid", strict=True),
    kind=(str, ...),
    message=(str, ...),
    retryable=(bool | None, None),
    details=(dict[str, JsonValue] | None, None),
    asset_id=(str | None, None),
    version=(str | None, None),
    reason=(str | None, None),
)
ErrorResponseDocument = create_model(
    "ErrorResponse", __config__=_SERIALIZED, error=(ErrorDocument, ...)
)
