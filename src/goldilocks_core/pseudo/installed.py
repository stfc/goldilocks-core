"""Strict provider-neutral manifest for installed pseudopotential tables."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from goldilocks_core.assets import AssetCorrupt, InstalledAsset
from goldilocks_core.contracts import PseudoCutoffs, PseudoMetadata
from goldilocks_core.pseudo.registry import PseudoTable
from goldilocks_core.pseudo.validation import (
    finite_positive_cutoff,
    required_functional,
)

TABLE_MANIFEST = "pseudo-table.json"
_SCHEMA_VERSION = 2
_RELATIVISTIC = frozenset({"scalar", "full", "non-relativistic"})
_TOP_LEVEL_FIELDS = {
    "schema_version",
    "id",
    "version",
    "provider",
    "functional",
    "accuracy",
    "relativistic",
    "licence",
    "citation",
    "entries",
}
_ENTRY_FIELDS = {
    "element",
    "path",
    "md5",
    "header_format",
    "upf_relativistic",
    "pseudo_type",
    "z_valence",
    "ecutwfc_ry",
    "ecutrho_ry",
    "source_identifier",
    "frozen_4f_core",
}


def write_table_manifest(
    destination: Path,
    table: PseudoTable,
    entries: list[dict[str, Any]],
) -> None:
    """Validate and write one complete provider-neutral table manifest."""
    elements = [entry.get("element") for entry in entries]
    expected = set(table.elements)
    if len(elements) != len(set(elements)):
        raise ValueError("pseudopotential table entries must have unique elements")
    if set(elements) != expected:
        missing = ", ".join(sorted(expected - set(elements))) or "none"
        extra = (
            ", ".join(sorted(str(element) for element in set(elements) - expected))
            or "none"
        )
        raise ValueError(f"table coverage mismatch; missing: {missing}; extra: {extra}")
    for entry in entries:
        _validate_entry_shape(entry)

    document = {
        "schema_version": _SCHEMA_VERSION,
        "id": table.asset.id,
        "version": table.version,
        "provider": table.provider,
        "functional": table.functional,
        "accuracy": table.accuracy,
        "relativistic": table.relativistic,
        "licence": table.licence,
        "citation": table.citation,
        "entries": sorted(entries, key=lambda entry: entry["element"]),
    }
    (destination / TABLE_MANIFEST).write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def load_installed_table(
    installed: InstalledAsset,
    *,
    table: PseudoTable | None = None,
) -> tuple[PseudoMetadata, ...]:
    """Strictly parse selection metadata from one verified installed table."""
    try:
        manifest_path = installed.path(TABLE_MANIFEST)
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) != _TOP_LEVEL_FIELDS:
            raise ValueError("pseudopotential manifest fields are invalid")
        if (
            isinstance(data["schema_version"], bool)
            or data["schema_version"] != _SCHEMA_VERSION
        ):
            raise ValueError(
                "unsupported pseudopotential manifest schema_version "
                f"{data['schema_version']!r}"
            )
        if data["id"] != installed.id or data["version"] != installed.version:
            raise ValueError("pseudopotential manifest identity does not match asset")
        provider = _nonempty_string(data["provider"], "provider")
        functional = required_functional(data["functional"], "table functional")
        accuracy = data["accuracy"]
        if accuracy not in {"efficiency", "precision"}:
            raise ValueError(f"unsupported table accuracy {accuracy!r}")
        relativistic = data["relativistic"]
        if relativistic not in _RELATIVISTIC:
            raise ValueError(
                f"unsupported table relativistic treatment {relativistic!r}"
            )
        licence = _nonempty_string(data["licence"], "licence")
        citation = _nonempty_string(data["citation"], "citation")
        raw_entries = data["entries"]
        if not isinstance(raw_entries, list) or not raw_entries:
            raise ValueError("pseudopotential manifest entries must be non-empty")

        if table is not None:
            declared = (
                table.asset.id,
                table.version,
                table.provider,
                table.functional,
                table.accuracy,
                table.relativistic,
                table.licence,
                table.citation,
            )
            manifested = (
                data["id"],
                data["version"],
                provider,
                functional,
                accuracy,
                relativistic,
                licence,
                citation,
            )
            if declared != manifested:
                raise ValueError(
                    "pseudopotential manifest disagrees with registry declaration"
                )

        metadata: list[PseudoMetadata] = []
        elements: list[str] = []
        paths: list[str] = []
        for entry in raw_entries:
            _validate_entry_shape(entry)
            element = _nonempty_string(entry["element"], "entry element")
            relative_path = _nonempty_string(entry["path"], "entry path")
            path = installed.path(relative_path)
            if _md5(path) != entry["md5"].lower():
                raise ValueError(f"entry md5 does not match {relative_path}")
            metadata.append(
                PseudoMetadata(
                    filepath=str(path),
                    filename=path.name,
                    header_format=_nonempty_string(
                        entry["header_format"], "header_format"
                    ),
                    provider=provider,
                    accuracy=accuracy,
                    element=element,
                    pseudo_type=entry["pseudo_type"],
                    functional=functional,
                    relativistic=relativistic,
                    z_valence=entry["z_valence"],
                    table_id=data["id"],
                    cutoffs=PseudoCutoffs(
                        ecutwfc_ry=finite_positive_cutoff(
                            entry["ecutwfc_ry"], f"{element} ecutwfc_ry"
                        ),
                        ecutrho_ry=finite_positive_cutoff(
                            entry["ecutrho_ry"], f"{element} ecutrho_ry"
                        ),
                    ),
                    source_identifier=entry["source_identifier"],
                    frozen_4f_core=entry["frozen_4f_core"],
                    pseudo_info={
                        "table_version": data["version"],
                        "licence": licence,
                        "citation": citation,
                    },
                )
            )
            elements.append(element)
            paths.append(relative_path)

        if len(elements) != len(set(elements)) or len(paths) != len(set(paths)):
            raise ValueError(
                "pseudopotential entries must have unique elements and paths"
            )
        if table is not None and set(elements) != set(table.elements):
            raise ValueError(
                "pseudopotential manifest coverage disagrees with registry"
            )
        return tuple(metadata)
    except (
        KeyError,
        OSError,
        TypeError,
        UnicodeError,
        json.JSONDecodeError,
        ValueError,
    ) as error:
        raise AssetCorrupt(
            f"invalid installed pseudopotential manifest for "
            f"{installed.id}@{installed.version}: {error}"
        ) from error


def _validate_entry_shape(entry: Any) -> None:
    if not isinstance(entry, dict):
        raise ValueError("pseudopotential entries must be objects")
    fields = set(entry)
    missing = sorted(_ENTRY_FIELDS - fields)
    extra = sorted(fields - (_ENTRY_FIELDS | {"cutoff_hints"}))
    if missing or extra:
        missing_names = ", ".join(missing) or "none"
        extra_names = ", ".join(extra) or "none"
        raise ValueError(
            f"pseudopotential entry fields mismatch; "
            f"missing: {missing_names}; extra: {extra_names}"
        )
    digest = entry["md5"]
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-fA-F]{32}", digest) is None:
        raise ValueError("pseudopotential entry md5 is invalid")
    if not isinstance(entry["frozen_4f_core"], bool):
        raise ValueError("frozen_4f_core must be a boolean")
    if entry["source_identifier"] is not None:
        _nonempty_string(entry["source_identifier"], "source_identifier")


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
