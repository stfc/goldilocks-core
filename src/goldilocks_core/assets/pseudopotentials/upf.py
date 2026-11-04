"""UPF pseudopotential file parsing: header text/attrs -> ``PseudoMetadata``.

Ported near-verbatim from v1's ``pseudo/parse_upf.py`` and ``pseudo/metadata.py``
(v2 epic 3, #4) -- merged into one file because ``PseudoMetadata`` is exactly what
this module produces, matching ``assets/pseudopotentials/``'s naming convention
(goldilocks-core-design.md S8: "file name says what it produces").
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Annotated, Any, TypedDict

from pymatgen.core import Element

from goldilocks_core.functionals import normalize_functional_label
from goldilocks_core.serialization import Portable
from goldilocks_core.types import (
    JsonDict,
    PseudoAccuracy,
    PseudoType,
    RelativisticTreatment,
)
from goldilocks_core.validation import (
    validate_finite_positive,
    validate_optional_nonempty_str,
    validate_relativistic_mode,
)


class PseudoCutoffs(TypedDict):
    """The cutoffs the provider publishes for one file, in Ry: ``None``
    where it publishes none (PseudoDojo has no density cutoff, #180)."""

    ecutwfc_ry: float | None
    ecutrho_ry: float | None


class PseudoCutoffHints(TypedDict):
    """PseudoDojo's published wavefunction cutoff hints, in Ry; ``high``
    is the file's ``ecutwfc_ry``."""

    low: float
    normal: float
    high: float


_HINT_LEVELS = ("low", "normal", "high")


@dataclass(frozen=True, slots=True)
class PseudoMetadata:
    """One UPF file's facts. ``filepath`` (where this machine reads the
    file) and ``pseudo_info`` are ``Portable()``, so no published record
    carries them. An installed table's file is published as ``table_id``,
    ``asset_path`` (its path inside that table's installation, so
    ``filepath`` is ``<asset-store>/<table_id>/<version>/<asset_path>``)
    and ``content_sha256``/``content_size_bytes`` (#177)."""

    filepath: Annotated[str, Portable()]
    filename: str
    header_format: str
    provider: str | None = None
    accuracy: PseudoAccuracy | None = None
    element: str | None = None
    pseudo_type: PseudoType | None = None
    functional: str | None = None
    relativistic: RelativisticTreatment | None = None
    z_valence: float | None = None
    table_id: str | None = None
    asset_path: str | None = None
    cutoffs: PseudoCutoffs | None = None
    cutoff_hints: PseudoCutoffHints | None = None
    source_identifier: str | None = None
    content_sha256: str | None = None
    content_size_bytes: int | None = None
    frozen_4f_core: bool = False
    pseudo_info: Annotated[JsonDict, Portable()] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def _validate_identity(self) -> None:
        for field_name in ("filepath", "filename", "header_format"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"PseudoMetadata.{field_name} must be a non-empty string; "
                    f"got {value!r}"
                )
        if (
            self.filename in {".", ".."}
            or "/" in self.filename
            or "\\" in self.filename
        ):
            raise ValueError("PseudoMetadata.filename must be one filename")
        for field_name in (
            "provider",
            "element",
            "source_identifier",
            "table_id",
            "asset_path",
        ):
            validate_optional_nonempty_str(
                getattr(self, field_name), f"PseudoMetadata.{field_name}"
            )
        for field_name in ("source_identifier", "asset_path"):
            value = getattr(self, field_name)
            if value is not None and (
                PurePosixPath(value).is_absolute()
                or PureWindowsPath(value).is_absolute()
                or value.startswith("~")
            ):
                raise ValueError(
                    f"PseudoMetadata.{field_name} must be portable, not a host path"
                )
        if (self.content_sha256 is None) != (self.content_size_bytes is None):
            raise ValueError(
                "PseudoMetadata content_sha256 and content_size_bytes must both be "
                "present or both be None"
            )
        if (
            self.content_sha256 is not None
            and re.fullmatch(r"[0-9a-f]{64}", self.content_sha256) is None
        ):
            raise ValueError(
                "PseudoMetadata.content_sha256 must be a lowercase SHA-256 digest"
            )
        if self.content_size_bytes is not None and (
            isinstance(self.content_size_bytes, bool)
            or not isinstance(self.content_size_bytes, int)
            or self.content_size_bytes < 0
        ):
            raise ValueError(
                "PseudoMetadata.content_size_bytes must be a non-negative integer"
            )

    def __post_init__(self) -> None:
        self._validate_identity()
        for field_name, allowed, description in (
            (
                "accuracy",
                {None, "efficiency", "precision"},
                "'efficiency', 'precision', or None",
            ),
            ("pseudo_type", {None, "NC", "USPP", "PAW"}, "NC, USPP, PAW, or None"),
        ):
            value = getattr(self, field_name)
            if value not in allowed:
                raise ValueError(
                    f"PseudoMetadata.{field_name} must be {description}; got {value!r}"
                )
        validate_relativistic_mode(self.relativistic, "PseudoMetadata.relativistic")
        functional = normalize_functional_label(self.functional)
        object.__setattr__(self, "functional", functional)
        self._normalize_numerics()
        for field_name, expected, description in (
            ("frozen_4f_core", bool, "a boolean"),
            ("pseudo_info", dict, "a dictionary"),
        ):
            if not isinstance(getattr(self, field_name), expected):
                raise ValueError(f"PseudoMetadata.{field_name} must be {description}")
        object.__setattr__(self, "pseudo_info", dict(self.pseudo_info))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        if any(
            not isinstance(warning, str) or not warning for warning in self.warnings
        ):
            raise ValueError("PseudoMetadata.warnings must contain non-empty strings")

    def _normalize_numerics(self) -> None:
        if self.z_valence is not None:
            validate_finite_positive(self.z_valence, "PseudoMetadata.z_valence")
            object.__setattr__(self, "z_valence", float(self.z_valence))
        if self.cutoffs is not None:
            if not isinstance(self.cutoffs, Mapping):
                raise ValueError("PseudoMetadata.cutoffs must be a mapping or None")
            unknown = set(self.cutoffs) - {"ecutwfc_ry", "ecutrho_ry"}
            if unknown:
                raise ValueError(
                    "PseudoMetadata.cutoffs accepts only ecutwfc_ry and "
                    f"ecutrho_ry; got {sorted(unknown)!r}"
                )
            normalized = {}
            for field_name in ("ecutwfc_ry", "ecutrho_ry"):
                value = self.cutoffs.get(field_name)
                if value is not None:
                    validate_finite_positive(
                        value, f"PseudoMetadata.cutoffs.{field_name}"
                    )
                    value = float(value)
                normalized[field_name] = value
            object.__setattr__(self, "cutoffs", normalized)
        if self.cutoff_hints is not None:
            self._normalize_cutoff_hints()

    def _normalize_cutoff_hints(self) -> None:
        hints = self.cutoff_hints
        if not isinstance(hints, Mapping) or set(hints) != set(_HINT_LEVELS):
            raise ValueError(
                "PseudoMetadata.cutoff_hints must map exactly low, normal and high"
            )
        for level in _HINT_LEVELS:
            validate_finite_positive(
                hints[level], f"PseudoMetadata.cutoff_hints.{level}"
            )
        normalized = {level: float(hints[level]) for level in _HINT_LEVELS}
        object.__setattr__(self, "cutoff_hints", normalized)


def _clean_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_float(value: object) -> float | None:
    text = _clean_string(value)
    if text is None:
        return None
    return float(text)


def _normalize_element(value: object) -> str | None:
    text = _clean_string(value)
    if text is None:
        return None
    return text[0].upper() + text[1:].lower()


def _extract_element_from_filename(filename: str) -> str | None:
    """Guess an element symbol from a bare filename stem, e.g. when a UPF
    header omits it. Some providers write two-letter symbols entirely in
    upper case with a clean boundary after them (``FE.UPF`` for iron),
    which the two regexes below cannot tell apart from a one-letter symbol
    followed by unrelated upper-case text -- so that candidate is only
    accepted once ``Element.is_valid_symbol`` confirms it names a real
    element; otherwise this falls through to the original heuristic
    unchanged."""
    stem = Path(filename).stem

    all_caps = re.match(r"^([A-Z]{2})(?:[_.\-]|$)", stem)
    if all_caps and Element.is_valid_symbol(all_caps.group(1).capitalize()):
        return all_caps.group(1).capitalize()

    match = re.match(r"^([A-Z][a-z]?)", stem)
    if match:
        return match.group(1)

    match = re.match(r"^([a-z]{1,2})(?:[_\.-]|$)", stem)
    if match:
        return match.group(1).capitalize()

    return None


def _normalize_relativistic(value: object) -> str | None:
    text = _clean_string(value)
    if text is None:
        return None

    lower = text.lower()
    if lower in {"scalar", "scalar-relativistic", "scalar relativistic"}:
        return "scalar"
    if lower in {
        "full",
        "fully_relativistic",
        "fully-relativistic",
        "fully relativistic",
    }:
        return "full"
    if lower in {"non-relativistic", "nonrelativistic", "non relativistic"}:
        return "non-relativistic"

    return lower


def _normalize_pseudo_type(value: object) -> str | None:
    text = _clean_string(value)
    if text is None:
        return None

    upper = text.upper()

    if upper in {"US", "USPP", "ULTRASOFT", "ULTRASOFT PSEUDOPOTENTIAL"}:
        return "USPP"
    if upper in {"NC", "NCPP", "NORM-CONSERVING", "NORMCONSERVING"}:
        return "NC"
    if upper in {"PAW"}:
        return "PAW"

    return upper


def _detect_header_format(text: str) -> str:
    if re.search(r"<PP_HEADER\b[^>]*?/>", text, re.IGNORECASE | re.DOTALL):
        return "attr"

    if re.search(r"<PP_HEADER>\s*.*?\s*</PP_HEADER>", text, re.IGNORECASE | re.DOTALL):
        return "text"

    raise ValueError("PP_HEADER not found or unsupported format")


def _parse_attr_header(text: str) -> dict[str, Any]:
    match = re.search(
        r"<PP_HEADER\b([^>]*)/>",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if match is None:
        raise ValueError("Attribute-style PP_HEADER not found")

    header = match.group(1)
    pairs = re.findall(r'(\w+)\s*=\s*"([^"]*)"', header)
    return dict(pairs)


def _normalize_text_header_keys(header_data: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(header_data)

    key_map = {
        "Element": "element",
        "Z valence": "z_valence",
        "Total energy": "total_psenergy",
        "Max angular momentum component": "l_max",
        "Number of points in mesh": "mesh_size",
        "Nonlinear Core Correction": "core_correction",
    }

    for old_key, new_key in key_map.items():
        if old_key in normalized:
            normalized[new_key] = normalized[old_key]

    if "Ultrasoft pseudopotential" in normalized:
        normalized["pseudo_type"] = normalized["Ultrasoft pseudopotential"]

    if "Exchange-Correlation functional" in normalized:
        normalized["functional"] = normalized["Exchange-Correlation functional"]

    if "Suggested cutoff for wfc and rho" in normalized:
        cutoff = normalized["Suggested cutoff for wfc and rho"]
        if isinstance(cutoff, dict):
            normalized["rho_cutoff"] = cutoff.get("ecutrho_ry")

    if "Number of Wavefunctions, Number of Projectors" in normalized:
        counts = normalized["Number of Wavefunctions, Number of Projectors"]
        if isinstance(counts, dict):
            normalized["number_of_wfc"] = counts.get("num_wavefunctions")
            normalized["number_of_proj"] = counts.get("num_projectors")

    return normalized


def _parse_text_header(text: str) -> dict[str, Any]:
    match = re.search(
        r"<PP_HEADER>\s*(.*?)\s*</PP_HEADER>",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if match is None:
        raise ValueError("Text-style PP_HEADER not found")

    block = match.group(1)
    lines = [line.rstrip() for line in block.splitlines() if line.strip()]

    header_data: dict[str, Any] = {}
    raw_lines: list[str] = []
    wavefunctions: list[str] = []
    in_wavefunctions_block = False

    for line in lines:
        raw_lines.append(line)

        if re.match(r"^\s*Wavefunctions\s+nl\s+l\s+occ\s*$", line):
            in_wavefunctions_block = True
            continue

        if in_wavefunctions_block:
            if re.match(r"^\s+\S", line):
                wavefunctions.append(line.strip())
                continue
            in_wavefunctions_block = False

        cutoff_match = re.match(
            r"^\s*(\S+)\s+(\S+)\s+Suggested cutoff for wfc and rho\s*$",
            line,
        )
        if cutoff_match:
            header_data["Suggested cutoff for wfc and rho"] = {
                "ecutwfc_ry": cutoff_match.group(1),
                "ecutrho_ry": cutoff_match.group(2),
            }
            continue

        counts_match = re.match(
            r"^\s*(\S+)\s+(\S+)\s+Number of Wavefunctions, Number of Projectors\s*$",
            line,
        )
        if counts_match:
            header_data["Number of Wavefunctions, Number of Projectors"] = {
                "num_wavefunctions": counts_match.group(1),
                "num_projectors": counts_match.group(2),
            }
            continue

        xc_match = re.match(
            r"^\s*(.+?)\s{2,}Exchange-Correlation functional\s*$",
            line,
        )
        if xc_match:
            header_data["Exchange-Correlation functional"] = xc_match.group(1).strip()
            continue

        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) == 2:
            value, key = parts
            header_data[key] = value

    header_data["Wavefunctions"] = wavefunctions
    header_data["_raw_lines"] = raw_lines
    return _normalize_text_header_keys(header_data)


def _parse_pp_info(text: str) -> dict[str, Any]:
    match = re.search(
        r"<PP_INFO>\s*(.*?)\s*</PP_INFO>",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if match is None:
        return {}

    block = match.group(1)
    lines = [line.strip() for line in block.splitlines() if line.strip()]

    info: dict[str, Any] = {}

    for line in lines:
        lower = line.lower()

        if "scalar-relativistic" in lower:
            info["relativistic"] = "scalar"
        elif "fully-relativistic" in lower or "full-relativistic" in lower:
            info["relativistic"] = "full"
        elif "non-relativistic" in lower:
            info["relativistic"] = "non-relativistic"

    return info


def _get_element(
    header_data: dict[str, Any], filename: str | None = None
) -> str | None:
    element = _normalize_element(header_data.get("element"))
    if element is not None:
        return element

    element = _normalize_element(header_data.get("Element"))
    if element is not None:
        return element

    if filename is not None:
        return _extract_element_from_filename(filename)

    return None


def parse_upf_metadata(path: str | Path) -> PseudoMetadata:
    path = Path(path)
    content = path.read_bytes()
    text = content.decode(errors="ignore")

    header_format = _detect_header_format(text)
    if header_format == "attr":
        header_data = _parse_attr_header(text)
    else:
        header_data = _parse_text_header(text)

    pp_info_data = _parse_pp_info(text)
    for key, value in pp_info_data.items():
        header_data.setdefault(key, value)

    element = _get_element(header_data, path.name)

    return PseudoMetadata(
        filepath=str(path),
        filename=path.name,
        header_format=header_format,
        element=element,
        pseudo_type=_normalize_pseudo_type(header_data.get("pseudo_type")),
        functional=normalize_functional_label(header_data.get("functional")),
        relativistic=_normalize_relativistic(header_data.get("relativistic")),
        z_valence=_to_float(header_data.get("z_valence")),
        content_sha256=hashlib.sha256(content).hexdigest(),
        content_size_bytes=len(content),
        pseudo_info=header_data,
    )
