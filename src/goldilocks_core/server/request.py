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
from dataclasses import fields
from typing import Any

from pymatgen.core import Structure

from goldilocks_core.contracts import (
    CalculationDraft,
    CalculationHints,
    CalculationIntent,
    ComputeRequest,
    InlineStructureSource,
    InMemoryStructureSource,
    ModelSource,
    ModelSpec,
    ModelType,
    PathStructureSource,
    PresetSelection,
    PseudoMetadata,
    RecordSelection,
    StructureSource,
    resolve_output_types,
)

__all__ = ["RequestError", "from_dict"]

_ALLOWED_TOP_LEVEL = frozenset({"draft", "selection"})
_ALLOWED_DRAFT = frozenset(
    {
        "structure",
        "intent",
        "hints",
        "pseudo_metadata",
        "pseudo_root",
        "pseudo_table",
        "kmesh_model",
    }
)
_INTENT_FIELDS = frozenset(field.name for field in fields(CalculationIntent))
_HINT_FIELDS = frozenset(field.name for field in fields(CalculationHints))
_PSEUDO_FIELDS = frozenset(field.name for field in fields(PseudoMetadata))
_MODEL_FIELDS = frozenset(field.name for field in fields(ModelSpec))
_MODEL_REQUIRED = _MODEL_FIELDS - {
    "revision",
    "licence",
    "licence_text",
    "citation",
}
_STRING_HINTS = {
    "smearing_type",
    "pseudo_accuracy",
    "pseudo_type",
    "relativistic_mode",
    "vdw_method",
}
_FLOAT_HINTS = {
    "k_spacing",
    "smearing_width_ry",
    "conv_thr",
    "mixing_beta",
}
_BOOL_HINTS = {"spin_polarized", "spin_orbit_coupling", "use_vdw"}


class RequestError(ValueError):
    """A malformed transport request."""


def from_dict(data: Mapping[str, Any]) -> ComputeRequest:
    if not isinstance(data, Mapping):
        raise RequestError("Request body must be a JSON object.")
    _reject_unknown(data, _ALLOWED_TOP_LEVEL, "request")
    if "draft" not in data or data["draft"] is None:
        raise RequestError("Request body requires 'draft'.")
    if "selection" not in data or data["selection"] is None:
        raise RequestError("Request body requires 'selection'.")
    draft_data = data["draft"]
    if not isinstance(draft_data, Mapping):
        raise RequestError("Field 'draft' must be a JSON object.")
    _reject_unknown(draft_data, _ALLOWED_DRAFT, "draft")
    if "structure" not in draft_data or draft_data["structure"] is None:
        raise RequestError("Field 'draft' requires 'structure'.")

    pseudo_metadata, pseudo_root, pseudo_table = _parse_pseudo_source(draft_data)
    draft = CalculationDraft(
        structure=_parse_structure(draft_data["structure"]),
        intent=_parse_intent(draft_data.get("intent")),
        hints=_parse_hints(draft_data.get("hints")),
        pseudo_metadata=pseudo_metadata,
        pseudo_root=pseudo_root,
        pseudo_table=pseudo_table,
        kmesh_model=_parse_kmesh_model(draft_data.get("kmesh_model")),
    )
    return ComputeRequest(
        draft=draft,
        selection=_parse_selection(data["selection"]),
    )


def _reject_unknown(
    data: Mapping[str, Any], allowed: frozenset[str], section: str
) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise RequestError(f"Unknown {section} fields: {', '.join(unknown)}")


def _parse_structure(value: Any) -> StructureSource:
    if isinstance(value, str):
        try:
            return PathStructureSource(value)
        except ValueError as error:
            raise RequestError(str(error)) from error
    if not isinstance(value, Mapping):
        raise RequestError(
            "Field 'structure' must be an inline, path, or in-memory "
            "Structure Source object."
        )

    kind = value.get("kind", "inline")
    try:
        if kind == "inline":
            _reject_unknown(
                value,
                frozenset({"kind", "name", "content", "format"}),
                "structure",
            )
            name = value.get("name")
            content = value.get("content")
            fmt = value.get("format")
            if not isinstance(name, str):
                raise RequestError("Inline 'structure' requires a 'name' string.")
            if not isinstance(content, str):
                raise RequestError("Inline 'structure' requires a 'content' string.")
            if fmt is not None and not isinstance(fmt, str):
                raise RequestError("Field 'structure.format' must be a string or null.")
            return InlineStructureSource(name=name, content=content, format=fmt)
        if kind == "path":
            _reject_unknown(value, frozenset({"kind", "path"}), "structure")
            path = value.get("path")
            if not isinstance(path, str):
                raise RequestError("Path 'structure' requires a 'path' string.")
            return PathStructureSource(path)
        if kind == "in_memory":
            _reject_unknown(value, frozenset({"kind", "structure"}), "structure")
            document = value.get("structure")
            if not isinstance(document, Mapping):
                raise RequestError(
                    "In-memory 'structure' requires a pymatgen structure object."
                )
            return InMemoryStructureSource(Structure.from_dict(dict(document)))
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, RequestError):
            raise
        raise RequestError(str(error)) from error
    raise RequestError(f"Unknown Structure Source kind: {kind!r}.")


def _parse_intent(value: Any) -> CalculationIntent:
    if value is None:
        return CalculationIntent()
    if not isinstance(value, Mapping):
        raise RequestError("Field 'intent' must be a JSON object or null.")
    _reject_unknown(value, _INTENT_FIELDS, "intent")
    for name, item in value.items():
        if not isinstance(item, str):
            raise RequestError(f"Field 'intent.{name}' must be a string.")
    try:
        return CalculationIntent(**value)
    except (TypeError, ValueError) as error:
        raise RequestError(str(error)) from error


def _parse_hints(value: Any) -> CalculationHints:
    if value is None:
        return CalculationHints()
    if not isinstance(value, Mapping):
        raise RequestError("Field 'hints' must be a JSON object or null.")
    _reject_unknown(value, _HINT_FIELDS, "hints")
    parsed = {
        name: _parse_hint(name, item)
        for name, item in value.items()
        if item is not None
    }
    try:
        return CalculationHints(**parsed)
    except (TypeError, ValueError) as error:
        raise RequestError(str(error)) from error


def _parse_hint(name: str, value: Any) -> Any:
    if name == "k_grid":
        if not _is_sequence(value) or len(value) != 3:
            raise RequestError("Field 'hints.k_grid' must be a list of three integers.")
        if any(not isinstance(item, int) or isinstance(item, bool) for item in value):
            raise RequestError("Field 'hints.k_grid' must be a list of three integers.")
        return tuple(value)
    if name in _STRING_HINTS and not isinstance(value, str):
        raise RequestError(f"Field 'hints.{name}' must be a string or null.")
    if name in _FLOAT_HINTS and (
        not isinstance(value, (int, float)) or isinstance(value, bool)
    ):
        raise RequestError(f"Field 'hints.{name}' must be a number or null.")
    if name in _BOOL_HINTS and not isinstance(value, bool):
        raise RequestError(f"Field 'hints.{name}' must be a boolean or null.")
    if name == "electron_maxstep" and (
        not isinstance(value, int) or isinstance(value, bool)
    ):
        raise RequestError("Field 'hints.electron_maxstep' must be an integer or null.")
    return value


def _parse_selection(value: Any) -> PresetSelection | RecordSelection:
    if not isinstance(value, Mapping):
        raise RequestError("Field 'selection' must be a JSON object.")
    _reject_unknown(value, frozenset({"preset", "records"}), "selection")
    choices = [name for name in ("preset", "records") if name in value]
    if len(choices) != 1:
        raise RequestError(
            "Field 'selection' requires exactly one of 'preset' or 'records'."
        )

    if choices[0] == "preset":
        preset = value["preset"]
        if not isinstance(preset, str) or not preset.strip():
            raise RequestError("Field 'selection.preset' must be a non-empty string.")
        return PresetSelection(preset)

    records = value["records"]
    if not _is_sequence(records) or any(not isinstance(item, str) for item in records):
        raise RequestError(
            "Field 'selection.records' must be a list of record type names."
        )
    try:
        return RecordSelection(resolve_output_types(list(records)))
    except ValueError as error:
        raise RequestError(str(error)) from error


def _parse_pseudo_source(
    data: Mapping[str, Any],
) -> tuple[tuple[PseudoMetadata, ...] | None, str | None, str | None]:
    metadata: tuple[PseudoMetadata, ...] | None = None
    if "pseudo_metadata" in data and data["pseudo_metadata"] is not None:
        value = data["pseudo_metadata"]
        if not _is_sequence(value):
            raise RequestError("Field 'pseudo_metadata' must be a list or null.")
        metadata = tuple(_parse_pseudo(item) for item in value)

    root = data.get("pseudo_root")
    if root is not None and (not isinstance(root, str) or not root.strip()):
        raise RequestError(
            "Field 'pseudo_root' must be a non-empty path string or null."
        )
    table = data.get("pseudo_table")
    if table is not None and (not isinstance(table, str) or not table.strip()):
        raise RequestError("Field 'pseudo_table' must be a non-empty string or null.")
    if (
        sum(
            (
                metadata is not None,
                root is not None,
                table is not None,
            )
        )
        > 1
    ):
        raise RequestError(
            "Request accepts only one of 'pseudo_metadata', 'pseudo_root', "
            "or 'pseudo_table'."
        )
    return metadata, root, table


def _parse_pseudo(value: Any) -> PseudoMetadata:
    if not isinstance(value, Mapping):
        raise RequestError("Each 'pseudo_metadata' entry must be a JSON object.")
    _reject_unknown(value, _PSEUDO_FIELDS, "pseudo_metadata")
    string_fields = _PSEUDO_FIELDS - {
        "z_valence",
        "content_size_bytes",
        "cutoffs",
        "frozen_4f_core",
        "pseudo_info",
        "warnings",
    }
    for name in string_fields:
        item = value.get(name)
        if item is not None and not isinstance(item, str):
            raise RequestError(
                f"Field 'pseudo_metadata.{name}' must be a string or null."
            )
    z_valence = value.get("z_valence")
    if z_valence is not None and (
        not isinstance(z_valence, (int, float)) or isinstance(z_valence, bool)
    ):
        raise RequestError(
            "Field 'pseudo_metadata.z_valence' must be a number or null."
        )
    pseudo_info = value.get("pseudo_info", {})
    if not isinstance(pseudo_info, Mapping):
        raise RequestError("Field 'pseudo_metadata.pseudo_info' must be an object.")
    cutoffs = value.get("cutoffs")
    if cutoffs is not None and not isinstance(cutoffs, Mapping):
        raise RequestError("Field 'pseudo_metadata.cutoffs' must be an object or null.")
    frozen_4f_core = value.get("frozen_4f_core", False)
    if not isinstance(frozen_4f_core, bool):
        raise RequestError("Field 'pseudo_metadata.frozen_4f_core' must be a boolean.")
    warnings = value.get("warnings", ())
    if not _is_sequence(warnings) or any(
        not isinstance(warning, str) for warning in warnings
    ):
        raise RequestError(
            "Field 'pseudo_metadata.warnings' must be a list of strings."
        )
    normalized = dict(value)
    normalized["pseudo_info"] = dict(pseudo_info)
    normalized["warnings"] = tuple(warnings)
    try:
        return PseudoMetadata(**normalized)
    except (TypeError, ValueError) as error:
        raise RequestError(str(error)) from error


def _parse_kmesh_model(value: Any) -> ModelSpec | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise RequestError("Field 'kmesh_model' must be a JSON object or null.")
    _reject_unknown(value, _MODEL_FIELDS, "kmesh_model")
    missing = sorted(_MODEL_REQUIRED - set(value))
    if missing:
        raise RequestError(
            f"Field 'kmesh_model' is missing required keys: {', '.join(missing)}"
        )
    for name, item in value.items():
        if item is not None and not isinstance(item, str):
            raise RequestError(f"Field 'kmesh_model.{name}' must be a string.")
    if value["model_type"] not in get_args(ModelType):
        raise RequestError(f"Unsupported model type: {value['model_type']!r}")
    if value["source"] not in get_args(ModelSource):
        raise RequestError(f"Unsupported model source: {value['source']!r}")
    try:
        return ModelSpec(**value)
    except (TypeError, ValueError) as error:
        raise RequestError(str(error)) from error


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))
