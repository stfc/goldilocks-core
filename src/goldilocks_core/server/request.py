"""Strict HTTP and MCP inputs, converted directly into native Core requests.

Remote callers supply inline content and registered identities, never server
paths, model artifacts, or publication destinations.
"""

from __future__ import annotations

from dataclasses import MISSING, fields
from typing import Annotated, Any, Literal, get_type_hints

from pydantic import ConfigDict, Field, ValidateAs, create_model, model_validator

from goldilocks_core.contracts import (
    CalculationDraft,
    CalculationHints,
    CalculationIntent,
    ComputeRequest,
    InlineStructureSource,
    PresetSelection,
    RecordSelection,
    resolve_output_types,
)

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
        lambda value: RecordSelection(resolve_output_types(value.records)),
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
