"""Shared request deserialization for HTTP and MCP transports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import fields
from pathlib import Path
from typing import Any, get_args

from pymatgen.core import Structure

from goldilocks_core._lint import allow_swallow
from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    CoreJobRequest,
    JobMode,
    ModelSource,
    ModelSpec,
    ModelType,
    resolve_output_types,
)
from goldilocks_core.pseudo.pp_metadata import PseudoMetadata
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata

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
    "pseudo_mode",
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


def from_dict(data: Mapping[str, Any]) -> CoreJobRequest:
    """Parse a JSON-like mapping into a validated Core job request."""
    if not isinstance(data, Mapping):
        raise RequestError("Request body must be a JSON object.")
    _reject_unknown(data, _ALLOWED_TOP_LEVEL, "request")
    if "structure" not in data or data["structure"] is None:
        raise RequestError("Request body requires 'structure'.")

    mode = _parse_mode(data.get("mode"))
    outputs = _parse_outputs(data.get("outputs"))
    output_dir = _parse_output_dir(data.get("output_dir"), mode, outputs)

    try:
        return CoreJobRequest(
            structure=_parse_structure(data["structure"]),
            intent=_parse_intent(data.get("intent")),
            hints=_parse_hints(data.get("hints")),
            mode=mode,
            outputs=outputs,
            output_dir=output_dir,
            pseudo_metadata=_parse_pseudo_metadata(data),
            kmesh_model=_parse_kmesh_model(data.get("kmesh_model")),
        )
    except RequestError:
        raise
    except (TypeError, ValueError) as error:
        raise RequestError(str(error)) from error


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
            "or inline content object."
        )
    _reject_unknown(value, frozenset({"content", "format"}), "structure")
    content = value.get("content")
    fmt = value.get("format")
    if not isinstance(content, str):
        raise RequestError("Inline 'structure' requires a 'content' string.")
    if fmt is not None and not isinstance(fmt, str):
        raise RequestError("Field 'structure.format' must be a string or null.")
    return _parse_structure_text(content, fmt)


@allow_swallow
def _parse_structure_text(content: str, fmt: str | None) -> Structure:
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
    if mode != "generate" or outputs is not None:
        raise RequestError("Field 'output_dir' is only valid for generate requests.")
    return value


def _parse_pseudo_metadata(data: Mapping[str, Any]) -> tuple[PseudoMetadata, ...]:
    if "pseudo_metadata" in data:
        value = data["pseudo_metadata"]
        if value is None:
            return ()
        if not _is_sequence(value):
            raise RequestError("Field 'pseudo_metadata' must be a list or null.")
        return tuple(_parse_pseudo(item) for item in value)
    root = data.get("pseudo_root")
    if root is None:
        return ()
    if not isinstance(root, str):
        raise RequestError("Field 'pseudo_root' must be a path string or null.")
    try:
        return tuple(load_pseudo_metadata(Path(root)))
    except (OSError, TypeError, ValueError) as error:
        raise RequestError(
            f"Could not load pseudo metadata from {root!r}: {error}"
        ) from error


def _parse_pseudo(value: Any) -> PseudoMetadata:
    if not isinstance(value, Mapping):
        raise RequestError("Each 'pseudo_metadata' entry must be a JSON object.")
    _reject_unknown(value, _PSEUDO_FIELDS, "pseudo_metadata")
    string_fields = _PSEUDO_FIELDS - {
        "z_valence",
        "pseudo_info",
        "is_sssp",
        "sssp_recommended_cutoff",
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
    if "pseudo_info" in value and not isinstance(value["pseudo_info"], Mapping):
        raise RequestError("Field 'pseudo_metadata.pseudo_info' must be an object.")
    if "is_sssp" in value and not isinstance(value["is_sssp"], bool):
        raise RequestError("Field 'pseudo_metadata.is_sssp' must be a boolean.")
    cutoff = value.get("sssp_recommended_cutoff")
    if cutoff is not None and not isinstance(cutoff, Mapping):
        raise RequestError(
            "Field 'pseudo_metadata.sssp_recommended_cutoff' must be an object or null."
        )
    try:
        return PseudoMetadata(**value)
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
