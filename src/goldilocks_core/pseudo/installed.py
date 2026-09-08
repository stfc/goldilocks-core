from __future__ import annotations

import hashlib
import json
import re
import tarfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any, BinaryIO

from goldilocks_core.assets.records import InstalledAsset
from goldilocks_core.assets.store import AssetCorrupt
from goldilocks_core.pseudo.metadata import PseudoMetadata
from goldilocks_core.pseudo.parse_upf import parse_upf_metadata
from goldilocks_core.pseudo.registry import PseudoTable
from goldilocks_core.pseudo.validation import (
    PseudoImportError,
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
    "pseudo_type",
    "z_valence",
    "ecutwfc_ry",
    "ecutrho_ry",
    "source_identifier",
    "frozen_4f_core",
}
_OPTIONAL_ENTRY_FIELDS = {"cutoff_hints", "upf_relativistic"}


def write_table_manifest(
    destination: Path,
    table: PseudoTable,
    entries: list[dict[str, Any]],
) -> None:
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


def archive_files(archive: Path, suffix: str = "") -> Iterator[tuple[str, BinaryIO]]:
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile() or not member.name.lower().endswith(suffix):
                continue
            source = tar.extractfile(member)
            if source is None:
                raise PseudoImportError(f"cannot extract {member.name}")
            with source:
                yield member.name, source


def extract_upf(
    source: BinaryIO,
    target: Path,
    element: str,
    table: PseudoTable,
    md5: str,
    mismatch: str,
) -> dict[str, Any]:
    digest = hashlib.md5()
    with target.open("xb") as output:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            output.write(chunk)
    if digest.hexdigest() != md5.lower():
        raise PseudoImportError(mismatch)
    parsed = parse_upf_metadata(target)
    if parsed.element != element:
        raise PseudoImportError(
            f"{element}: UPF element is {parsed.element or 'unknown'}"
        )
    functional = required_functional(parsed.functional, f"UPF functional for {element}")
    if functional != table.functional:
        raise PseudoImportError(
            f"{element}: UPF functional {functional} does not match "
            f"table functional {table.functional}"
        )
    if parsed.relativistic != table.relativistic and not (
        table.relativistic == "scalar" and parsed.relativistic == "non-relativistic"
    ):
        raise PseudoImportError(
            f"{element}: UPF relativistic treatment "
            f"{parsed.relativistic or 'unknown'} does not match table "
            f"treatment {table.relativistic}"
        )
    return {
        "element": element,
        "path": f"pseudos/{target.name}",
        "md5": digest.hexdigest(),
        "header_format": parsed.header_format,
        "upf_relativistic": parsed.relativistic,
        "pseudo_type": parsed.pseudo_type,
        "z_valence": parsed.z_valence,
    }


def _validate_manifest(
    data: Any,
    installed: InstalledAsset,
    table: PseudoTable | None,
) -> None:
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
    for field in ("provider", "licence", "citation"):
        data[field] = _nonempty_string(data[field], field)
    data["functional"] = required_functional(data["functional"], "table functional")
    for field, allowed, label in (
        ("accuracy", {"efficiency", "precision"}, "accuracy"),
        ("relativistic", _RELATIVISTIC, "relativistic treatment"),
    ):
        if data[field] not in allowed:
            raise ValueError(f"unsupported table {label} {data[field]!r}")
    if not isinstance(data["entries"], list) or not data["entries"]:
        raise ValueError("pseudopotential manifest entries must be non-empty")
    if table is not None:
        declared = {
            field: getattr(table, field)
            for field in (
                "version",
                "provider",
                "functional",
                "accuracy",
                "relativistic",
                "licence",
                "citation",
            )
        }
        declared["id"] = table.asset.id
        if declared != {field: data[field] for field in declared}:
            raise ValueError(
                "pseudopotential manifest disagrees with registry declaration"
            )


def load_installed_table(
    installed: InstalledAsset,
    *,
    table: PseudoTable | None = None,
) -> tuple[PseudoMetadata, ...]:
    try:
        manifest_path = installed.path(TABLE_MANIFEST)
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        _validate_manifest(data, installed, table)
        metadata: list[PseudoMetadata] = []
        elements: list[str] = []
        paths: list[str] = []
        for entry in data["entries"]:
            _validate_entry_shape(entry)
            element = _nonempty_string(entry["element"], "entry element")
            relative_path = _nonempty_string(entry["path"], "entry path")
            path = installed.path(relative_path)
            if _md5(path) != entry["md5"].lower():
                raise ValueError(f"entry md5 does not match {relative_path}")
            entry_relativistic = entry.get("upf_relativistic", data["relativistic"])
            metadata.append(
                PseudoMetadata(
                    filepath=str(path),
                    filename=path.name,
                    header_format=_nonempty_string(
                        entry["header_format"], "header_format"
                    ),
                    provider=data["provider"],
                    accuracy=data["accuracy"],
                    element=element,
                    pseudo_type=entry["pseudo_type"],
                    functional=data["functional"],
                    relativistic=entry_relativistic,
                    z_valence=entry["z_valence"],
                    table_id=data["id"],
                    cutoffs={
                        field: finite_positive_cutoff(
                            entry[field], f"{element} {field}"
                        )
                        for field in ("ecutwfc_ry", "ecutrho_ry")
                    },
                    source_identifier=entry["source_identifier"],
                    frozen_4f_core=entry["frozen_4f_core"],
                    pseudo_info={
                        "table_version": data["version"],
                        "table_relativistic": data["relativistic"],
                        "licence": data["licence"],
                        "citation": data["citation"],
                        "upf_relativistic": entry_relativistic,
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
    extra = sorted(fields - (_ENTRY_FIELDS | _OPTIONAL_ENTRY_FIELDS))
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
    upf_relativistic = entry.get("upf_relativistic")
    if upf_relativistic is not None and upf_relativistic not in _RELATIVISTIC:
        raise ValueError(f"unsupported UPF relativistic treatment {upf_relativistic!r}")


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
