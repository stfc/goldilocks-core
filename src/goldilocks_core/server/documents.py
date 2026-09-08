"""Strict remote inputs and portable response schemas derived from native records.

Only this optional module depends on Pydantic. Input projections construct native
values directly through ValidateAs; output projections describe trusted portable
values and never revalidate execution results. Remote drafts deliberately expose
only inline structures and registered pseudopotential identities.
"""

from __future__ import annotations

import types
from dataclasses import MISSING, fields, is_dataclass
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

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidateAs,
    create_model,
    model_validator,
)

from goldilocks_core.calculation import CalculationHints, CalculationIntent
from goldilocks_core.io.structures import InlineStructureSource, StructureInspection
from goldilocks_core.request import (
    CalculationDraft,
    ComputeRequest,
    PresetSelection,
    RecordSelection,
)
from goldilocks_core.result import ComputationResult, PreparedComputation
from goldilocks_core.runtime.capabilities import Capabilities
from goldilocks_core.runtime.graph import CalculationTaskCapability
from goldilocks_core.runtime.registry import record_types_by_id
from goldilocks_core.serialization import Portable

_STRICT = ConfigDict(extra="forbid", strict=True)


def _contract_document(contract: type, **overrides: Any) -> Any:
    hints = get_type_hints(contract)
    definitions: dict[str, Any] = {}
    for item in fields(contract):
        default = (
            Field(default_factory=item.default_factory)
            if item.default_factory is not MISSING
            else item.default
            if item.default is not MISSING
            else ...
        )
        definitions[item.name] = (hints[item.name], default)
    model = create_model(
        contract.__name__, __config__=_STRICT, **(definitions | overrides)
    )
    return Annotated[contract, ValidateAs(model, lambda value: contract(**vars(value)))]


IntentDocument = _contract_document(CalculationIntent)
HintsDocument = _contract_document(CalculationHints, k_grid=(list[int] | None, None))


def _inline_structure(value: Any) -> Any:
    if isinstance(value, str) or (
        isinstance(value, dict) and (value.get("kind") == "path" or "path" in value)
    ):
        raise ValueError(
            "Transports do not accept file paths. Read the file and pass its "
            "text as an inline Structure Source."
        )
    return value


InlineStructureDocument = Annotated[
    InlineStructureSource,
    ValidateAs(
        create_model(
            "InlineStructureSource",
            __config__=_STRICT,
            __validators__={
                "inline_structure": model_validator(mode="before")(_inline_structure)
            },
            kind=(Literal["inline"], "inline"),
            name=(str, ...),
            content=(str, ...),
            format=(Literal["cif", "poscar"] | None, None),
        ),
        lambda value: InlineStructureSource(value.name, value.content, value.format),
    ),
]
InspectRequestDocument = create_model(
    "StructureInspectionRequest",
    __config__=_STRICT,
    source=(InlineStructureDocument, ...),
)
DraftDocument = Annotated[
    CalculationDraft,
    ValidateAs(
        create_model(
            "CalculationDraft",
            __config__=_STRICT,
            structure=(InlineStructureDocument, ...),
            intent=(IntentDocument | None, None),
            hints=(HintsDocument | None, None),
            pseudo_table=(str | None, None),
        ),
        lambda value: CalculationDraft(
            structure=value.structure,
            intent=value.intent or CalculationIntent(),
            hints=value.hints or CalculationHints(),
            pseudo_table=value.pseudo_table,
        ),
    ),
]
PresetSelectionDocument = _contract_document(PresetSelection)
RecordSelectionDocument = Annotated[
    RecordSelection,
    ValidateAs(
        create_model("RecordSelection", __config__=_STRICT, records=(list[str], ...)),
        lambda value: RecordSelection.from_ids(value.records),
    ),
]
type SelectionDocument = PresetSelectionDocument | RecordSelectionDocument
MemoryOutputDocument = create_model(
    "MemoryOutput", __config__=_STRICT, kind=(Literal["memory"], ...)
)
ComputeRequestDocument = Annotated[
    ComputeRequest,
    ValidateAs(
        create_model(
            "ComputeRequest",
            __config__=_STRICT,
            draft=(DraftDocument, ...),
            selection=(SelectionDocument, ...),
        ),
        lambda value: ComputeRequest(value.draft, value.selection),
    ),
]


_SERIALIZED = ConfigDict(extra="forbid")
_SERIALIZED_MODELS: dict[Any, Any] = {}
_OMIT = object()


def _serialized_annotation(annotation: Any) -> Any:
    """Project domain annotations through the same exclusions as to_portable."""
    if annotation is Any or annotation is JsonValue:
        return JsonValue
    if isinstance(annotation, TypeAliasType):
        return _serialized_annotation(annotation.__value__)
    origin = get_origin(annotation)
    if origin in (Annotated, Required, NotRequired):
        inner, *metadata = get_args(annotation)
        for item in metadata:
            if isinstance(item, Portable):
                return (
                    _OMIT
                    if item.annotation is None
                    else _serialized_annotation(item.annotation)
                )
        return _serialized_annotation(inner)
    if is_typeddict(annotation) or (
        isinstance(annotation, type) and is_dataclass(annotation)
    ):
        return _serialized_model(annotation)
    if origin is None or origin is Literal:
        return annotation
    converted = tuple(_serialized_annotation(item) for item in get_args(annotation))
    if origin in (tuple, list, dict):
        return origin[converted]
    if origin in (types.UnionType, Union):
        return reduce(or_, converted)
    return annotation


def _serialized_model(
    contract: type,
    *,
    overrides: dict[str, Any] | None = None,
) -> type[BaseModel]:
    if overrides is None and contract in _SERIALIZED_MODELS:
        return _SERIALIZED_MODELS[contract]
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
    hints = get_type_hints(PreparedComputation)
    result_document = computation_result_document(tasks)
    return create_model(
        PreparedComputation.__name__,
        __config__=_SERIALIZED,
        **{
            item.name: (
                result_document
                if item.name == "result"
                else _serialized_annotation(hints[item.name]),
                ... if item.default is MISSING else item.default,
            )
            for item in fields(PreparedComputation)
        },
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
