from __future__ import annotations

import types
from dataclasses import MISSING, fields, is_dataclass
from functools import reduce
from operator import or_
from typing import Any, Literal, TypeAliasType, get_args, get_origin, get_type_hints

from pydantic import BaseModel, ConfigDict, JsonValue, create_model

from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    GeneratedContent,
    InputArtifact,
    InstalledArtifactReference,
    ModelSpec,
    PseudoMetadata,
    PseudopotentialSelection,
    Publication,
    RuntimeAssetIdentity,
    RuntimeIdentity,
    StructureInspection,
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
type LocalOutputDocument = (
    MemoryOutputDocument | DirectoryOutputDocument | ArchiveOutputDocument
)
ComputeRequestDocument = create_model(
    "ComputeRequest",
    __config__=_STRICT,
    draft=(DraftDocument, ...),
    selection=(SelectionDocument, ...),
    output=(MemoryOutputDocument | HttpArchiveOutputDocument, ...),
)
_SERIALIZED = ConfigDict(extra="forbid")
_SERIALIZED_MODELS: dict[type | TypeAliasType, Any] = {}


def _serialized_annotation(annotation: Any) -> Any:
    if annotation in _SERIALIZED_MODELS:
        return _SERIALIZED_MODELS[annotation]
    if isinstance(annotation, TypeAliasType):
        return _serialized_annotation(annotation.__value__)
    if isinstance(annotation, type) and is_dataclass(annotation):
        return _serialized_model(annotation)

    origin = get_origin(annotation)
    if origin is None or origin is Literal:
        return annotation
    converted = tuple(_serialized_annotation(item) for item in get_args(annotation))
    if origin is tuple:
        if len(converted) == 2 and converted[1] is Ellipsis:
            return tuple[converted[0], ...]
        return tuple[converted]
    if origin is list:
        return list[converted[0]]
    if origin is dict:
        return dict[converted[0], converted[1]]
    if origin is types.UnionType:
        return reduce(or_, converted)
    return annotation


def _serialized_model(
    contract: type,
    *,
    name: str | None = None,
    exclude: frozenset[str] = frozenset(),
    overrides: dict[str, Any] | None = None,
) -> type[BaseModel]:
    hints = get_type_hints(contract)
    replacements = overrides or {}
    definitions: dict[str, Any] = {}
    for item in fields(contract):
        if item.name in exclude:
            continue
        annotation = _serialized_annotation(
            replacements.get(item.name, hints[item.name])
        )
        definitions[item.name] = (annotation, ...)
    document = create_model(
        name or contract.__name__, __config__=_SERIALIZED, **definitions
    )
    if not exclude and not replacements:
        _SERIALIZED_MODELS[contract] = document
    return document


SerializedIntentDocument = _serialized_model(
    CalculationIntent,
    name="SerializedCalculationIntent",
)
SerializedHintsDocument = _serialized_model(
    CalculationHints,
    name="SerializedCalculationHints",
)
SerializedModelDocument = _serialized_model(
    ModelSpec,
    name="SerializedModel",
    exclude=frozenset({"location", "licence_text"}),
)
_SERIALIZED_MODELS[ModelSpec] = SerializedModelDocument
SerializedPseudoMetadataDocument = _serialized_model(
    PseudoMetadata,
    name="SerializedPseudoMetadata",
    exclude=frozenset({"filepath", "pseudo_info"}),
)
_SERIALIZED_MODELS[PseudoMetadata] = SerializedPseudoMetadataDocument
SerializedPseudopotentialDocument = _serialized_model(
    PseudopotentialSelection,
    name="SerializedPseudopotentialSelection",
    exclude=frozenset({"filepath"}),
)
_SERIALIZED_MODELS[PseudopotentialSelection] = SerializedPseudopotentialDocument

GeneratedArtifactSourceDocument = create_model(
    "GeneratedArtifactSource",
    __config__=_SERIALIZED,
    kind=(Literal["generated"], ...),
    identity=(str, ...),
)
InstalledArtifactSourceDocument = create_model(
    "InstalledArtifactSource",
    __config__=_SERIALIZED,
    kind=(Literal["installed"], ...),
    asset_id=(str, ...),
    asset_version=(str, ...),
    preparation_fingerprint=(str, ...),
    path=(str, ...),
)
_SERIALIZED_MODELS[GeneratedContent] = GeneratedArtifactSourceDocument
_SERIALIZED_MODELS[InstalledArtifactReference] = InstalledArtifactSourceDocument
ArtifactSourceDocument = (
    GeneratedArtifactSourceDocument | InstalledArtifactSourceDocument
)
SerializedInputArtifactDocument = _serialized_model(
    InputArtifact,
    name="SerializedInputArtifact",
    overrides={"source": ArtifactSourceDocument},
)
_SERIALIZED_MODELS[InputArtifact] = SerializedInputArtifactDocument
RuntimeAssetFileDocument = create_model(
    "RuntimeAssetFile",
    __config__=_SERIALIZED,
    path=(str, ...),
    role=(str, ...),
    sha256=(str, ...),
    size_bytes=(int, ...),
)
SerializedRuntimeAssetDocument = _serialized_model(
    RuntimeAssetIdentity,
    name="SerializedRuntimeAsset",
    overrides={
        "model": SerializedModelDocument,
        "files": list[RuntimeAssetFileDocument],
    },
)
_SERIALIZED_MODELS[RuntimeAssetIdentity] = SerializedRuntimeAssetDocument
SerializedRuntimeDocument = _serialized_model(
    RuntimeIdentity,
    name="SerializedRuntime",
    overrides={"models": list[SerializedModelDocument]},
)
_SERIALIZED_MODELS[RuntimeIdentity] = SerializedRuntimeDocument

LocalPseudoRootDocument = create_model(
    "LocalPseudoRoot",
    __config__=_SERIALIZED,
    kind=(Literal["local_root"], ...),
)
SerializedCalculationDraftDocument = create_model(
    "SerializedCalculationDraft",
    __config__=_SERIALIZED,
    structure=(StructureInspection, ...),
    intent=(SerializedIntentDocument, ...),
    hints=(SerializedHintsDocument, ...),
    pseudo_metadata=(list[SerializedPseudoMetadataDocument] | None, ...),
    pseudo_root=(LocalPseudoRootDocument | None, ...),
    pseudo_table=(str | None, ...),
    kmesh_model=(SerializedModelDocument | None, ...),
)
RecordsDocument = create_model(
    "Records",
    __config__=_SERIALIZED,
    **{
        record_id: (_serialized_annotation(record_type), None)
        for record_id, record_type in OUTPUT_TYPES_BY_ID.items()
    },
)
ComputationResultDocument = create_model(
    "ComputationResult",
    __config__=_STRICT,
    schema_version=(Literal[1], ...),
    draft=(SerializedCalculationDraftDocument, ...),
    task=(str, ...),
    task_revision=(str, ...),
    selection=(SelectionDocument, ...),
    records=(RecordsDocument, ...),
    warnings=(list[str], ...),
    publication=(_serialized_annotation(Publication) | None, ...),
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
    reason=(str | None, None),
)
ErrorResponseDocument = create_model(
    "ErrorResponse", __config__=_STRICT, error=(ErrorDocument, ...)
)
