"""Shared request deserialization for HTTP and MCP transports.

One :func:`from_dict` parser is used by both transports: it turns a JSON-like
mapping into a validated :class:`~goldilocks_core.contracts.PresetRequest`
(when no ``outputs`` are named) or
:class:`~goldilocks_core.contracts.QueryRequest` (when ``outputs`` names a
record subset). Unknown keys and bad types are rejected with named-field
:class:`RequestError` messages; stage ``ValueError``\\ s are not caught here and
surface to the transport's error handler.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import fields
from typing import Any, get_args

from pymatgen.core import Structure

from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    JobMode,
    ModelSource,
    ModelSpec,
    ModelType,
    PresetRequest,
    PseudoMetadata,
    QueryRequest,
    resolve_output_types,
)

__all__ = ["RequestError", "from_dict"]

_ALLOWED_TOP_LEVEL = frozenset(
    {
        "structure",
        "intent",
        "hints",
        "mode",
        "outputs",
        "output_dir",
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
_MODEL_REQUIRED = _MODEL_FIELDS - {"revision"}
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
    pass


def from_dict(data: Mapping[str, Any]) -> PresetRequest | QueryRequest:
    """Parse a JSON-like mapping into a validated Core job request.

    Returns a :class:`QueryRequest` when ``outputs`` names record types, and a
    :class:`PresetRequest` (selected by ``mode``) otherwise.
    """
    if not isinstance(data, Mapping):
        raise RequestError("Request body must be a JSON object.")
    _reject_unknown(data, _ALLOWED_TOP_LEVEL, "request")
    if "structure" not in data or data["structure"] is None:
        raise RequestError("Request body requires 'structure'.")

    mode = _parse_mode(data.get("mode"))
    outputs = _parse_outputs(data.get("outputs"))
    output_dir = _parse_output_dir(data.get("output_dir"), mode, outputs)

    structure = _parse_structure(data["structure"])
    intent = _parse_intent(data.get("intent"))
    hints = _parse_hints(data.get("hints"))
    pseudo_metadata, pseudo_root, pseudo_table = _parse_pseudo_source(data)
    kmesh_model = _parse_kmesh_model(data.get("kmesh_model"))

    if outputs is not None:
        return QueryRequest(
            structure=structure,
            outputs=outputs,
            intent=intent,
            hints=hints,
            pseudo_metadata=pseudo_metadata,
            pseudo_root=pseudo_root,
            pseudo_table=pseudo_table,
            kmesh_model=kmesh_model,
        )
    return PresetRequest(
        structure=structure,
        intent=intent,
        hints=hints,
        mode=mode,
        pseudo_metadata=pseudo_metadata,
        pseudo_root=pseudo_root,
        pseudo_table=pseudo_table,
        output_dir=output_dir,
        kmesh_model=kmesh_model,
    )


def _reject_unknown(
    data: Mapping[str, Any], allowed: frozenset[str], section: str
) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise RequestError(f"Unknown {section} fields: {', '.join(unknown)}")


def _parse_structure(value: Any) -> str | Structure:
    if isinstance(value, str):
        if "\n" in value or value.lstrip().startswith("data_"):
            return _parse_structure_text(value, None)
        return value
    if not isinstance(value, Mapping):
        raise RequestError(
            "Field 'structure' must be a file path, inline CIF/POSCAR string, "
            "inline content object, or pymatgen Structure object."
        )
    if (
        value.get("@module") == "pymatgen.core.structure"
        and value.get("@class") == "Structure"
    ):
        try:
            return Structure.from_dict(dict(value))
        except (KeyError, TypeError, ValueError) as error:
            raise RequestError(
                f"Could not parse pymatgen structure object: {error}"
            ) from error
    _reject_unknown(value, frozenset({"content", "format"}), "structure")
    content = value.get("content")
    fmt = value.get("format")
    if not isinstance(content, str):
        raise RequestError("Inline 'structure' requires a 'content' string.")
    if fmt is not None and not isinstance(fmt, str):
        raise RequestError("Field 'structure.format' must be a string or null.")
    return _parse_structure_text(content, fmt)


def _parse_structure_text(content: str, fmt: str | None) -> Structure:
    """Parse inline CIF or POSCAR content, trying the declared format first."""
    formats = (fmt,) if fmt is not None else ("cif", "poscar")
    last_error: Exception | None = None
    for structure_format in formats:
        try:
            return Structure.from_str(content, fmt=structure_format)
        except (IndexError, KeyError, TypeError, ValueError) as error:
            last_error = error
    raise RequestError(f"Could not parse inline structure content: {last_error}")


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


def _parse_mode(value: Any) -> JobMode:
    if value is None:
        return "recommend"
    if not isinstance(value, str) or value not in {"recommend", "generate"}:
        raise RequestError("Field 'mode' must be 'recommend' or 'generate'.")
    return value  # type: ignore[return-value]


def _parse_outputs(value: Any) -> tuple[type, ...] | None:
    if value is None:
        return None
    if not _is_sequence(value):
        raise RequestError("Field 'outputs' must be a list of record type names.")
    if any(not isinstance(item, str) for item in value):
        raise RequestError("Field 'outputs' must be a list of record type names.")
    try:
        return resolve_output_types(list(value))
    except ValueError as error:
        raise RequestError(str(error)) from error


def _parse_output_dir(
    value: Any, mode: JobMode, outputs: tuple[type, ...] | None
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RequestError("Field 'output_dir' must be a string or null.")
    if not value.strip():
        raise RequestError("Field 'output_dir' must be a non-empty string.")
    if mode != "generate" or outputs is not None:
        raise RequestError("Field 'output_dir' is only valid for generate requests.")
    return value


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
