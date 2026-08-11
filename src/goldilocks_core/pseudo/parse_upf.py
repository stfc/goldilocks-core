from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from goldilocks_core.contracts import PseudoMetadata
from goldilocks_core.functionals import normalize_functional_label


def _read_text(path: Path) -> str:
    """Read a UPF file as text."""
    return path.read_text(errors="ignore")


def _clean_string(value: object) -> str | None:
    """Return a stripped string, or None for missing or empty values."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_float(value: object) -> float | None:
    """Convert a value to float when possible."""
    text = _clean_string(value)
    if text is None:
        return None
    return float(text)


def _extract_library(filepath: str) -> str | None:
    """Extract the top-level pseudo library from the path."""
    parts = Path(filepath).parts
    if "pseudopotentials" not in parts:
        return None

    index = parts.index("pseudopotentials")
    if index + 1 >= len(parts):
        return None
    return parts[index + 1]


def _normalize_element(value: object) -> str | None:
    """Normalize element strings such as 'B ' -> 'B'."""
    text = _clean_string(value)
    if text is None:
        return None
    return text[0].upper() + text[1:].lower()


def _extract_element_from_filename(filename: str) -> str | None:
    """Extract the leading element symbol from a pseudo filename."""
    stem = Path(filename).stem

    match = re.match(r"^([A-Z][a-z]?)", stem)
    if match:
        return match.group(1)

    match = re.match(r"^([a-z]{1,2})(?:[_\.-]|$)", stem)
    if match:
        return match.group(1).capitalize()

    return None


def _normalize_relativistic(value: object) -> str | None:
    """Normalize relativistic mode labels."""
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
    """Normalize pseudo type labels."""
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
    """Detect whether PP_HEADER is attribute-style or text-style."""
    if re.search(r"<PP_HEADER\b[^>]*?/>", text, re.IGNORECASE | re.DOTALL):
        return "attr"

    if re.search(r"<PP_HEADER>\s*.*?\s*</PP_HEADER>", text, re.IGNORECASE | re.DOTALL):
        return "text"

    raise ValueError("PP_HEADER not found or unsupported format")


def _parse_attr_header(text: str) -> dict[str, Any]:
    """Parse an attribute-style PP_HEADER block."""
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
    """Map text-style header keys onto the standard internal field names."""
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
    """Parse a text-style PP_HEADER block."""
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
    """Parse supplemental PP_INFO data."""
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
    """Get an element from parsed header data, with filename fallback."""
    element = _normalize_element(header_data.get("element"))
    if element is not None:
        return element

    element = _normalize_element(header_data.get("Element"))
    if element is not None:
        return element

    if filename is not None:
        return _extract_element_from_filename(filename)

    return None


def _is_sssp_folder(path: Path) -> bool:
    """Return True if the file is inside an SSSP directory."""
    return path.parent.name.startswith("SSSP")


def _load_sssp_json(path: Path) -> dict[str, Any] | None:
    """Load the SSSP sidecar JSON when available."""
    folder_name = path.parent.name
    json_path = path.parent.parent / f"{folder_name}.json"

    if not json_path.exists():
        return None

    return json.loads(json_path.read_text())


def _get_sssp_info(
    path: Path, element: str | None
) -> tuple[bool, str | None, dict[str, Any] | None]:
    """Return SSSP-specific metadata derived from the sidecar JSON."""
    is_sssp = _is_sssp_folder(path)

    if not is_sssp:
        return False, path.parent.name, None

    if element is None:
        return True, None, None

    data = _load_sssp_json(path)
    if data is None:
        return True, None, None

    entry = data.get(element)
    if entry is None:
        return True, None, None

    source_pseudopotential = entry.get("pseudopotential")
    sssp_recommended_cutoff = {
        "ecutwfc_ry": entry.get("cutoff_wfc"),
        "ecutrho_ry": entry.get("cutoff_rho"),
    }

    return True, source_pseudopotential, sssp_recommended_cutoff


def parse_upf_metadata(path: str | Path) -> PseudoMetadata:
    """Parse one UPF file into a PseudoMetadata object."""
    path = Path(path)
    text = _read_text(path)

    header_format = _detect_header_format(text)
    if header_format == "attr":
        header_data = _parse_attr_header(text)
    else:
        header_data = _parse_text_header(text)

    pp_info_data = _parse_pp_info(text)
    for key, value in pp_info_data.items():
        header_data.setdefault(key, value)

    element = _get_element(header_data, path.name)
    is_sssp, source_pseudopotential, sssp_recommended_cutoff = _get_sssp_info(
        path, element
    )

    return PseudoMetadata(
        filepath=str(path),
        filename=path.name,
        header_format=header_format,
        library=_extract_library(str(path)),
        source_set=path.parent.name,
        element=_normalize_element(header_data.get("element"))
        or _extract_element_from_filename(path.name),
        pseudo_type=_normalize_pseudo_type(header_data.get("pseudo_type")),
        functional=normalize_functional_label(header_data.get("functional")),
        relativistic=_normalize_relativistic(header_data.get("relativistic")),
        z_valence=_to_float(header_data.get("z_valence")),
        pseudo_info=header_data,
        is_sssp=is_sssp,
        source_pseudopotential=source_pseudopotential,
        sssp_recommended_cutoff=sssp_recommended_cutoff,
    )
