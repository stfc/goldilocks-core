"""Shared deserialization for HTTP and MCP scientific requests.

Transports accept an inline Structure Source, calculation intent, scientist
hints, one registered pseudopotential-table ID, and a computation selection.
The server resolves paths, pseudopotential contents, models, and publication
locations from its own environment. The wire carries scientific content and
registered identity, never server paths or loadable artifacts.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from typing import Any, Literal

from goldilocks_core.contracts import (
    CalculationDraft,
    CalculationHints,
    CalculationIntent,
    ComputeRequest,
    DirectoryOutput,
    InlineStructureSource,
    OutputTarget,
    PresetSelection,
    RecordSelection,
    StructureSource,
    resolve_output_types,
)

__all__ = [
    "RequestError",
    "TransportOutput",
    "compute_from_dict",
    "inspection_source_from_dict",
    "mcp_output_from_dict",
]

_INTENT_FIELDS = frozenset(field.name for field in fields(CalculationIntent))
_HINT_FIELDS = frozenset(field.name for field in fields(CalculationHints))
_DRAFT_FIELDS = frozenset({"structure", "intent", "hints", "pseudo_table"})


class RequestError(ValueError):
    """A malformed transport request."""


@dataclass(frozen=True, slots=True)
class TransportOutput:
    kind: Literal["memory", "automatic"]
    target: OutputTarget | None


def inspection_source_from_dict(data: Mapping[str, Any]) -> StructureSource:
    body = _mapping(data, "Request body")
    _reject_unknown(body, frozenset({"source"}), "request")
    if "source" not in body:
        raise RequestError("Request body requires 'source'.")
    return _structure_source(body["source"])


def compute_from_dict(data: Mapping[str, Any]) -> ComputeRequest:
    body = _mapping(data, "Request body")
    _reject_unknown(body, frozenset({"draft", "selection"}), "request")
    if "draft" not in body:
        raise RequestError("Request body requires 'draft'.")
    if "selection" not in body:
        raise RequestError("Request body requires 'selection'.")

    draft_data = _mapping(body["draft"], "Field 'draft'")
    _reject_unknown(draft_data, _DRAFT_FIELDS, "draft")
    if "structure" not in draft_data:
        raise RequestError("Field 'draft' requires 'structure'.")

    try:
        intent = _contract(CalculationIntent, draft_data.get("intent"), "intent")
        hints = _contract(CalculationHints, draft_data.get("hints"), "hints")
        draft = CalculationDraft(
            structure=_structure_source(draft_data["structure"]),
            intent=intent,
            hints=hints,
            pseudo_table=draft_data.get("pseudo_table"),
        )
        return ComputeRequest(draft=draft, selection=_selection(body["selection"]))
    except TypeError as error:
        raise RequestError(str(error)) from error


def mcp_output_from_dict(data: Mapping[str, Any] | None) -> TransportOutput:
    if data is None:
        return TransportOutput("automatic", DirectoryOutput())
    output = _mapping(data, "Field 'output'")
    _reject_unknown(output, frozenset({"kind"}), "output")
    if output.get("kind") != "memory":
        raise RequestError(
            "MCP output must be omitted for automatic publication or set to memory."
        )
    return TransportOutput("memory", None)


def _contract(contract_type: type, value: Any, name: str):
    if value is None:
        return contract_type()
    document = _mapping(value, f"Field '{name}'")
    allowed = _INTENT_FIELDS if contract_type is CalculationIntent else _HINT_FIELDS
    _reject_unknown(document, allowed, name)
    return contract_type(**document)


def _structure_source(value: Any) -> StructureSource:
    if isinstance(value, str):
        raise RequestError(
            "Transports do not accept file paths. Read the file and pass its text "
            "as an inline Structure Source."
        )
    source = _mapping(value, "Field 'source'")
    if source.get("kind") == "path" or "path" in source:
        raise RequestError(
            "Transports do not accept file paths. Read the file and pass its text "
            "as an inline Structure Source."
        )
    _reject_unknown(source, frozenset({"kind", "name", "content", "format"}), "source")
    kind = source.get("kind", "inline")
    if kind != "inline":
        raise RequestError(f"Unsupported Structure Source kind: {kind!r}.")
    missing = [name for name in ("name", "content") if name not in source]
    if missing:
        raise RequestError(
            "Inline Structure Source requires "
            + " and ".join(repr(name) for name in missing)
            + "."
        )
    try:
        return InlineStructureSource(
            name=source["name"],
            content=source["content"],
            format=source.get("format"),
        )
    except TypeError as error:
        raise RequestError(str(error)) from error


def _selection(value: Any) -> PresetSelection | RecordSelection:
    selection = _mapping(value, "Field 'selection'")
    _reject_unknown(selection, frozenset({"preset", "records"}), "selection")
    choices = [name for name in ("preset", "records") if name in selection]
    if len(choices) != 1:
        raise RequestError(
            "Field 'selection' requires exactly one of 'preset' or 'records'."
        )
    if choices[0] == "preset":
        return PresetSelection(selection["preset"])
    record_ids = selection["records"]
    if not _sequence(record_ids) or any(
        not isinstance(record_id, str) for record_id in record_ids
    ):
        raise RequestError("Field 'selection.records' must be a list of record ids.")
    return RecordSelection(resolve_output_types(tuple(record_ids)))


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RequestError(f"{label} must be a JSON object.")
    if any(not isinstance(key, str) for key in value):
        raise RequestError(f"{label} keys must be strings.")
    return value


def _sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


def _reject_unknown(
    data: Mapping[str, Any], allowed: frozenset[str], section: str
) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise RequestError(f"Unknown {section} fields: {', '.join(unknown)}")
