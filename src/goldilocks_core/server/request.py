"""Shared request deserialization for Core transports.

A single :func:`from_dict` parser used by both the HTTP and MCP transports.
It turns a JSON mapping into a validated :class:`CoreJobRequest` and is the
**only** place that performs that conversion. Unknown keys and bad types are
rejected with a :class:`RequestError` naming the field — fields are never
silently dropped.

Transport only: no auth, persistence, queue, or pod management lives here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pymatgen.core import Structure

from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    CoreJobRequest,
    JobMode,
    ModelSpec,
)
from goldilocks_core.pseudo.pp_metadata import PseudoMetadata
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata

__all__ = ["RequestError", "from_dict"]

# Top-level keys accepted by ``from_dict``. The transport (endpoint or tool)
# selects ``mode``; the body may also carry it so a single dict round-trips
# through the Python API, but it must be a valid mode.
_ALLOWED_TOP_LEVEL: frozenset[str] = frozenset(
    {
        "structure",
        "intent",
        "hints",
        "mode",
        "pseudo_metadata",
        "pseudo_root",
        "output_dir",
        "kmesh_model",
    }
)

# Required ModelSpec fields; ``revision`` is optional.
_MODELSPEC_REQUIRED: frozenset[str] = frozenset(
    {
        "name",
        "version",
        "model_type",
        "target",
        "feature_set",
        "source",
        "location",
    }
)

_VALID_MODES: frozenset[str] = frozenset({"recommend", "generate"})

# CalculationHints fields and their expected scalar-ness for type checks.
_HINT_FIELDS: tuple[str, ...] = (
    "k_spacing",
    "k_grid",
    "smearing_type",
    "smearing_width_ry",
    "spin_polarized",
    "spin_orbit_coupling",
    "pseudo_mode",
    "pseudo_type",
    "relativistic_mode",
    "conv_thr",
    "mixing_beta",
    "electron_maxstep",
    "use_vdw",
    "vdw_method",
)

# PseudoMetadata fields accepted in a per-request dict entry.
_PSEUDO_FIELDS: tuple[str, ...] = (
    "filepath",
    "filename",
    "header_format",
    "library",
    "source_set",
    "element",
    "pseudo_type",
    "functional",
    "relativistic",
    "z_valence",
    "pseudo_info",
    "is_sssp",
    "source_pseudopotential",
    "sssp_recommended_cutoff",
)

# CalculationIntent fields accepted in the intent dict.
_INTENT_FIELDS: tuple[str, ...] = ("code", "task", "functional", "pseudo_mode")


class RequestError(ValueError):
    """Invalid transport request body.

    Carries a ``kind`` suitable for HTTP status mapping (``invalid_request``
    maps to 422; ``stage_error`` maps to 400) and a human-readable message.
    """

    def __init__(self, kind: str, message: str) -> None:
        """Store the kind and message; remain a ValueError subclass."""
        super().__init__(message)
        self.kind = kind
        self.message = message


def from_dict(data: Mapping[str, Any]) -> CoreJobRequest:
    """Parse a transport request mapping into a validated ``CoreJobRequest``.

    Accepted top-level keys: ``structure`` (required), ``intent``, ``hints``,
    ``mode``, ``pseudo_metadata``, ``pseudo_root``, ``output_dir``,
    ``kmesh_model``. Unknown keys, bad types, and explicit ``null`` for
    non-optional sections are rejected with a :class:`RequestError`.

    Args:
        data: Parsed JSON mapping (the request body).

    Returns:
        A validated ``CoreJobRequest`` ready for a :class:`CoreRuntime`
        entrypoint.

    Raises:
        RequestError: If the body is malformed, has unknown keys, or a
            downstream constructor rejects a value.
    """
    if not isinstance(data, Mapping):
        raise RequestError("invalid_request", "Request body must be a JSON object.")

    _reject_unknown_keys(data, _ALLOWED_TOP_LEVEL)

    if "structure" not in data or data["structure"] is None:
        raise RequestError("invalid_request", "Request body requires 'structure'.")

    structure = _parse_structure(data["structure"])

    intent = _parse_intent(data.get("intent"))
    hints = _parse_hints(data.get("hints"))
    mode = _parse_mode(data.get("mode"))
    output_dir = _parse_output_dir(data.get("output_dir"), mode)
    pseudo_metadata = _parse_pseudo_metadata(data)
    kmesh_model = _parse_kmesh_model(data.get("kmesh_model"))

    try:
        return CoreJobRequest(
            structure=structure,
            intent=intent,
            hints=hints,
            mode=mode,
            pseudo_metadata=pseudo_metadata,
            output_dir=output_dir,
            kmesh_model=kmesh_model,
        )
    except RequestError:
        raise
    except ValueError as error:
        raise RequestError("invalid_request", str(error)) from error


def _reject_unknown_keys(data: Mapping[str, Any], allowed: frozenset[str]) -> None:
    """Raise naming any top-level key not in ``allowed``."""
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise RequestError(
            "invalid_request",
            f"Unknown request fields: {', '.join(unknown)}",
        )


def _parse_structure(field: Any) -> str | Structure:
    """Parse the ``structure`` field into a path string or pymatgen Structure.

    Accepts a path string (minimal, primary surface) or an inline dict with
    ``content`` (CIF/POSCAR text) and optional ``format``. A path string is
    returned as-is for :func:`load_structure` to resolve at stage time; inline
    content is parsed into a ``Structure`` here.
    """
    if isinstance(field, str):
        return field
    if isinstance(field, Mapping):
        return _parse_inline_structure(field)
    raise RequestError(
        "invalid_request",
        "Field 'structure' must be a path string or an inline content object.",
    )


def _parse_inline_structure(field: Mapping[str, Any]) -> Structure:
    """Parse an inline structure dict (``content`` + optional ``format``)."""
    allowed = frozenset({"content", "format"})
    _reject_unknown_keys(field, allowed)
    if "content" not in field or not isinstance(field["content"], str):
        raise RequestError(
            "invalid_request",
            "Inline 'structure' requires a 'content' string.",
        )
    fmt = field.get("format")
    if fmt is not None and not isinstance(fmt, str):
        raise RequestError(
            "invalid_request",
            "Field 'structure.format' must be a string or null.",
        )
    content = field["content"]
    try:
        from pymatgen.core import Structure as _Structure

        return (
            _Structure.from_str(content, fmt=fmt)
            if fmt
            else _Structure.from_str(content)
        )
    except Exception as error:  # noqa: BLE001 - surface as invalid_request
        raise RequestError(
            "invalid_request",
            f"Could not parse inline structure content: {error}",
        ) from error


def _parse_intent(field: Any) -> CalculationIntent:
    """Parse the optional ``intent`` mapping into a ``CalculationIntent``."""
    if field is None:
        return CalculationIntent()
    if not isinstance(field, Mapping):
        raise RequestError(
            "invalid_request",
            "Field 'intent' must be a JSON object or null.",
        )
    _reject_unknown_keys(field, frozenset(_INTENT_FIELDS))
    kwargs: dict[str, Any] = {}
    for name in _INTENT_FIELDS:
        if name in field:
            value = field[name]
            if value is not None and not isinstance(value, str):
                raise RequestError(
                    "invalid_request",
                    f"Field 'intent.{name}' must be a string or null.",
                )
            if value is not None:
                kwargs[name] = value
    try:
        return CalculationIntent(**kwargs)
    except ValueError as error:
        raise RequestError("invalid_request", str(error)) from error


def _parse_hints(field: Any) -> CalculationHints:
    """Parse the optional ``hints`` mapping into a ``CalculationHints``."""
    if field is None:
        return CalculationHints()
    if not isinstance(field, Mapping):
        raise RequestError(
            "invalid_request",
            "Field 'hints' must be a JSON object or null.",
        )
    _reject_unknown_keys(field, frozenset(_HINT_FIELDS))
    kwargs: dict[str, Any] = {}
    for name in _HINT_FIELDS:
        if name in field:
            value = field[name]
            if value is not None:
                kwargs[name] = _coerce_hint_value(name, value)
    try:
        return CalculationHints(**kwargs)
    except ValueError as error:
        raise RequestError("invalid_request", str(error)) from error


def _coerce_hint_value(name: str, value: Any) -> Any:
    """Validate and coerce a single hint value from its JSON representation."""
    if name == "k_grid":
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            raise RequestError(
                "invalid_request",
                "Field 'hints.k_grid' must be a list of three integers.",
            )
        if len(value) != 3:
            raise RequestError(
                "invalid_request",
                "Field 'hints.k_grid' must contain exactly three integers.",
            )
        return tuple(int(v) for v in value)
    return value


def _parse_mode(field: Any) -> JobMode:
    """Parse the optional ``mode`` field, defaulting to ``recommend``."""
    if field is None:
        return "recommend"
    if not isinstance(field, str):
        raise RequestError(
            "invalid_request",
            "Field 'mode' must be a string ('recommend' or 'generate').",
        )
    if field not in _VALID_MODES:
        raise RequestError(
            "invalid_request",
            f"Field 'mode' must be one of {sorted(_VALID_MODES)}; got {field!r}",
        )
    return field  # type: ignore[return-value]


def _parse_output_dir(field: Any, mode: JobMode) -> str | None:
    """Parse the optional ``output_dir`` field, meaningful only with generate."""
    if field is None:
        return None
    if not isinstance(field, str):
        raise RequestError(
            "invalid_request",
            "Field 'output_dir' must be a string or null.",
        )
    return field


def _parse_pseudo_metadata(data: Mapping[str, Any]) -> tuple[PseudoMetadata, ...]:
    """Parse pseudopotential metadata from the request body.

    Accepts either ``pseudo_metadata`` (a list of metadata dicts, parsed into
    ``PseudoMetadata``) or ``pseudo_root`` (a path string loaded via
    :func:`load_pseudo_metadata`, mirroring the CLI). ``pseudo_metadata`` takes
    precedence when both are present.
    """
    if "pseudo_metadata" in data:
        entries = data["pseudo_metadata"]
        if entries is None:
            return ()
        if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
            raise RequestError(
                "invalid_request",
                "Field 'pseudo_metadata' must be a list or null.",
            )
        return tuple(_parse_one_pseudo(entry) for entry in entries)
    if "pseudo_root" in data:
        root = data["pseudo_root"]
        if root is None:
            return ()
        if not isinstance(root, str):
            raise RequestError(
                "invalid_request",
                "Field 'pseudo_root' must be a path string or null.",
            )
        try:
            return tuple(load_pseudo_metadata(Path(root)))
        except Exception as error:  # noqa: BLE101 - surface as invalid_request
            raise RequestError(
                "invalid_request",
                f"Could not load pseudo metadata from {root!r}: {error}",
            ) from error
    return ()


def _parse_one_pseudo(entry: Any) -> PseudoMetadata:
    """Parse one ``pseudo_metadata`` list entry into a ``PseudoMetadata``."""
    if not isinstance(entry, Mapping):
        raise RequestError(
            "invalid_request",
            "Each 'pseudo_metadata' entry must be a JSON object.",
        )
    _reject_unknown_keys(entry, frozenset(_PSEUDO_FIELDS))
    kwargs: dict[str, Any] = {}
    for name in _PSEUDO_FIELDS:
        if name in entry:
            kwargs[name] = entry[name]
    try:
        return PseudoMetadata(**kwargs)
    except (TypeError, ValueError) as error:
        raise RequestError("invalid_request", str(error)) from error


def _parse_kmesh_model(field: Any) -> ModelSpec | None:
    """Parse the optional ``kmesh_model`` mapping into a ``ModelSpec``."""
    if field is None:
        return None
    if not isinstance(field, Mapping):
        raise RequestError(
            "invalid_request",
            "Field 'kmesh_model' must be a JSON object or null.",
        )
    _reject_unknown_keys(field, _MODELSPEC_REQUIRED | frozenset({"revision"}))
    missing = sorted(_MODELSPEC_REQUIRED - set(field))
    if missing:
        raise RequestError(
            "invalid_request",
            f"Field 'kmesh_model' is missing required keys: {', '.join(missing)}",
        )
    try:
        return ModelSpec(
            name=field["name"],
            version=field["version"],
            model_type=field["model_type"],
            target=field["target"],
            feature_set=field["feature_set"],
            source=field["source"],
            location=field["location"],
            revision=field.get("revision"),
        )
    except (TypeError, ValueError) as error:
        raise RequestError("invalid_request", str(error)) from error
