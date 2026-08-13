"""Normalized installed-table manifest shared by pseudo providers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from goldilocks_core.assets import InstalledAsset
from goldilocks_core.contracts import PseudoMetadata
from goldilocks_core.pseudo.registry import PseudoTable

TABLE_MANIFEST = "pseudo-table.json"
_RELATIVISTIC = {"SR": "scalar", "FR": "full", "NR": "non-relativistic"}


def write_table_manifest(
    destination: Path,
    table: PseudoTable,
    entries: list[dict[str, Any]],
) -> None:
    """Write the complete provider-independent pseudopotential table manifest."""
    elements = {entry["element"] for entry in entries}
    expected = set(table.elements)
    if elements != expected:
        missing = ", ".join(sorted(expected - elements)) or "none"
        extra = ", ".join(sorted(elements - expected)) or "none"
        raise ValueError(f"table coverage mismatch; missing: {missing}; extra: {extra}")
    document = {
        "schema_version": 1,
        "id": table.id,
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
        json.dumps(document, indent=2, sort_keys=True) + "\n"
    )


def load_installed_table(installed: InstalledAsset) -> tuple[PseudoMetadata, ...]:
    """Load selection metadata solely from a verified installed manifest."""
    manifest_path = installed.path(TABLE_MANIFEST)
    data = json.loads(manifest_path.read_text())
    if data["id"] != installed.id or str(data["version"]) != installed.version:
        raise ValueError("pseudopotential manifest identity does not match asset")
    relativistic = _RELATIVISTIC[data["relativistic"]]
    metadata: list[PseudoMetadata] = []
    for entry in data["entries"]:
        path = installed.path(entry["path"])
        metadata.append(
            PseudoMetadata(
                filepath=str(path),
                filename=path.name,
                header_format=entry.get("header_format", "attr"),
                library=data["provider"],
                source_set=data["accuracy"],
                element=entry["element"],
                pseudo_type=entry.get("pseudo_type"),
                functional=data["functional"],
                relativistic=relativistic,
                z_valence=entry.get("z_valence"),
                pseudo_info={
                    "table_id": data["id"],
                    "table_version": str(data["version"]),
                    "licence": data["licence"],
                    "citation": data["citation"],
                    "cutoff_hints": entry.get("cutoff_hints"),
                    "f_in_core": entry.get("f_in_core"),
                },
                is_sssp=data["provider"] == "sssp",
                source_pseudopotential=entry.get("source_pseudopotential"),
                sssp_recommended_cutoff={
                    "ecutwfc_ry": entry["ecutwfc_ry"],
                    "ecutrho_ry": entry["ecutrho_ry"],
                },
            )
        )
    return tuple(metadata)
