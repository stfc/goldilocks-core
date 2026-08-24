"""Shared request deserialization for HTTP and MCP transports.

One :func:`from_dict` parser is used by both transports: it turns a JSON-like
mapping into a validated :class:`~goldilocks_core.contracts.PresetRequest`
(when no ``outputs`` are named) or
:class:`~goldilocks_core.contracts.QueryRequest` (when ``outputs`` names a
record subset). Unknown keys and bad types are rejected with named-field
:class:`RequestError` messages; stage ``ValueError``\\ s are not caught here and
surface to the transport's error handler.

The parser accepts only the calculation itself: an inline Structure Source,
the calculation intent, scientist hints, and (for queries) the requested
record types. Deployment configuration is never request data — model and
pseudopotential selection and output locations are resolved by the server
from its own environment, so no transport field names server-side paths or
loadable artifacts.
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
    PathStructureSource,
    PresetSelection,
    RecordSelection,
    StructureSource,
    resolve_output_types,
)

__all__ = [
    "RequestError",
    "TransportOutput",
    "compute_from_dict",
    "http_output_from_dict",
    "inspection_source_from_dict",
    "local_output_from_dict",
]

_INTENT_FIELDS = frozenset(field.name for field in fields(CalculationIntent))
_HINT_FIELDS = frozenset(field.name for field in fields(CalculationHints))
_DRAFT_FIELDS = frozenset({"structure", "intent", "hints", "pseudo_table"})
_LOCAL_DRAFT_FIELDS = _DRAFT_FIELDS | {"pseudo_root"}


class RequestError(ValueError):
    """A malformed transport request."""


@dataclass(frozen=True, slots=True)
class TransportOutput:
    kind: Literal["memory", "archive", "directory", "automatic"]
    target: OutputTarget | None


def inspection_source_from_dict(
    data: Mapping[str, Any], *, allow_path: bool = False
) -> StructureSource:
    body = _mapping(data, "Request body")
    _reject_unknown(body, frozenset({"source"}), "request")
    if "source" not in body:
        raise RequestError("Request body requires 'source'.")
    return _structure_source(body["source"], allow_path=allow_path)


def compute_from_dict(
    data: Mapping[str, Any],
    *,
    allow_path: bool = False,
    allow_local_assets: bool = False,
) -> ComputeRequest:
    body = _mapping(data, "Request body")
    _reject_unknown(body, frozenset({"draft", "selection"}), "request")
    if "draft" not in body:
        raise RequestError("Request body requires 'draft'.")
    if "selection" not in body:
        raise RequestError("Request body requires 'selection'.")

    draft_data = _mapping(body["draft"], "Field 'draft'")
    allowed_draft = _LOCAL_DRAFT_FIELDS if allow_local_assets else _DRAFT_FIELDS
    _reject_unknown(draft_data, allowed_draft, "draft")
    if "structure" not in draft_data:
        raise RequestError("Field 'draft' requires 'structure'.")

    try:
        intent = _contract(CalculationIntent, draft_data.get("intent"), "intent")
        hints = _contract(CalculationHints, draft_data.get("hints"), "hints")
        draft = CalculationDraft(
            structure=_structure_source(draft_data["structure"], allow_path=allow_path),
            intent=intent,
            hints=hints,
            pseudo_root=draft_data.get("pseudo_root"),
            pseudo_table=draft_data.get("pseudo_table"),
        )
        return ComputeRequest(draft=draft, selection=_selection(body["selection"]))
    except TypeError as error:
        raise RequestError(str(error)) from error


def http_output_from_dict(data: Mapping[str, Any]) -> TransportOutput:
    output = _mapping(data, "Field 'output'")
    _reject_unknown(output, frozenset({"kind"}), "output")
    kind = output.get("kind")
    if kind not in {"memory", "archive"}:
        raise RequestError("Field 'output.kind' must be memory or archive.")
    return TransportOutput(kind, None)


def local_output_from_dict(
    data: Mapping[str, Any] | None, *, default_automatic: bool
) -> TransportOutput:
    if data is None:
        return TransportOutput(
            "automatic" if default_automatic else "memory",
            DirectoryOutput() if default_automatic else None,
        )
    output = _mapping(data, "Field 'output'")
    _reject_unknown(output, frozenset({"kind", "path"}), "output")
    kind = output.get("kind")
    if kind == "memory":
        if "path" in output:
            raise RequestError("Memory output does not accept 'path'.")
        return TransportOutput("memory", None)
    if kind in {"directory", "archive"}:
        path = output.get("path")
        if path is None:
            raise RequestError(f"{kind.title()} output requires 'path'.")
        if kind == "directory":
            return TransportOutput("directory", DirectoryOutput(path))
        from goldilocks_core.contracts import ArchiveOutput

        return TransportOutput("archive", ArchiveOutput(path))
    raise RequestError("Field 'output.kind' must be memory, directory, or archive.")


def _contract(contract_type: type, value: Any, name: str):
    if value is None:
        return contract_type()
    document = _mapping(value, f"Field '{name}'")
    allowed = _INTENT_FIELDS if contract_type is CalculationIntent else _HINT_FIELDS
    _reject_unknown(document, allowed, name)
    return contract_type(**document)


def _structure_source(value: Any, *, allow_path: bool) -> StructureSource:
    if isinstance(value, str):
        if not allow_path:
            raise RequestError("HTTP Structure Sources must use inline content.")
        return PathStructureSource(value)
    source = _mapping(value, "Field 'source'")
    _reject_unknown(source, frozenset({"kind", "name", "content", "format"}), "source")
    kind = source.get("kind", "inline")
    if kind != "inline":
        if kind == "path" and allow_path:
            _reject_unknown(source, frozenset({"kind", "path"}), "source")
            if "path" not in source:
                raise RequestError("Path Structure Source requires 'path'.")
            return PathStructureSource(source["path"])
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
