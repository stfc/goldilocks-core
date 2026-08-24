from __future__ import annotations

from dataclasses import MISSING, fields
from typing import Any, Literal, get_type_hints

from pydantic import BaseModel, ConfigDict, JsonValue, create_model

from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    Publication,
)
from goldilocks_core.contracts.outputs import OUTPUT_TYPES_BY_ID

_STRICT = ConfigDict(extra="forbid", strict=True)
_RECORD_IDS = Literal[tuple(OUTPUT_TYPES_BY_ID)]


def _model_from_dataclass(contract: type, name: str) -> type[BaseModel]:
    hints = get_type_hints(contract)
    definitions: dict[str, Any] = {}
    for item in fields(contract):
        annotation = hints[item.name]
        if item.default is not MISSING:
            definitions[item.name] = (annotation, item.default)
        elif item.default_factory is not MISSING:
            definitions[item.name] = (annotation, item.default_factory)
        else:
            definitions[item.name] = (annotation, ...)
    return create_model(name, __config__=_STRICT, **definitions)


_IntentBase = _model_from_dataclass(CalculationIntent, "CalculationIntentBase")
IntentDocument = create_model(
    "CalculationIntent",
    __base__=_IntentBase,
    pseudo_accuracy=(str, "efficiency"),
)
_HintsBase = _model_from_dataclass(CalculationHints, "CalculationHintsBase")
HintsDocument = create_model(
    "CalculationHints",
    __base__=_HintsBase,
    k_grid=(list[int] | None, None),
    pseudo_accuracy=(str | None, None),
    vdw_method=(str | None, None),
)
InlineStructureDocument = create_model(
    "InlineStructureSource",
    __config__=_STRICT,
    kind=(Literal["inline"], "inline"),
    name=(str, ...),
    content=(str, ...),
    format=(Literal["cif", "poscar"] | None, None),
)
InspectRequestDocument = create_model(
    "StructureInspectionRequest",
    __config__=_STRICT,
    source=(InlineStructureDocument, ...),
)
DraftDocument = create_model(
    "CalculationDraft",
    __config__=_STRICT,
    structure=(InlineStructureDocument, ...),
    intent=(IntentDocument | None, None),
    hints=(HintsDocument | None, None),
    pseudo_table=(str | None, None),
)
LocalDraftDocument = create_model(
    "LocalCalculationDraft",
    __config__=_STRICT,
    structure=(str | InlineStructureDocument, ...),
    intent=(IntentDocument | None, None),
    hints=(HintsDocument | None, None),
    pseudo_table=(str | None, None),
    pseudo_root=(str | None, None),
)
PresetSelectionDocument = create_model(
    "PresetSelection", __config__=_STRICT, preset=(str, ...)
)
RecordSelectionDocument = create_model(
    "RecordSelection", __config__=_STRICT, records=(list[_RECORD_IDS], ...)
)
type SelectionDocument = PresetSelectionDocument | RecordSelectionDocument
MemoryOutputDocument = create_model(
    "MemoryOutput", __config__=_STRICT, kind=(Literal["memory"], ...)
)
HttpArchiveOutputDocument = create_model(
    "HttpArchiveOutput", __config__=_STRICT, kind=(Literal["archive"], ...)
)
DirectoryOutputDocument = create_model(
    "DirectoryOutput",
    __config__=_STRICT,
    kind=(Literal["directory"], ...),
    path=(str, ...),
)
ArchiveOutputDocument = create_model(
    "ArchiveOutput",
    __config__=_STRICT,
    kind=(Literal["archive"], ...),
    path=(str, ...),
)
AutomaticOutputDocument = create_model(
    "AutomaticOutput", __config__=_STRICT, kind=(Literal["automatic"], ...)
)
type LocalOutputDocument = (
    MemoryOutputDocument
    | DirectoryOutputDocument
    | ArchiveOutputDocument
    | AutomaticOutputDocument
)
ComputeRequestDocument = create_model(
    "ComputeRequest",
    __config__=_STRICT,
    draft=(DraftDocument, ...),
    selection=(SelectionDocument, ...),
    output=(MemoryOutputDocument | HttpArchiveOutputDocument, ...),
)
ComputationResultDocument = create_model(
    "ComputationResult",
    __config__=_STRICT,
    schema_version=(Literal[1], ...),
    draft=(dict[str, JsonValue], ...),
    task=(str, ...),
    task_revision=(str, ...),
    selection=(dict[str, JsonValue], ...),
    records=(dict[str, JsonValue], ...),
    warnings=(list[str], ...),
    publication=(Publication | None, ...),
)
ErrorDocument = create_model(
    "Error",
    __config__=_STRICT,
    kind=(str, ...),
    message=(str, ...),
    retryable=(bool | None, None),
    details=(dict[str, JsonValue] | None, None),
    asset_id=(str | None, None),
    version=(str | None, None),
    root=(str | None, None),
)
ErrorResponseDocument = create_model(
    "ErrorResponse", __config__=_STRICT, error=(ErrorDocument, ...)
)
