"""Domain registry for complete pseudopotential-table assets."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import quote

from goldilocks_core.assets import AssetFile, AssetSpec
from goldilocks_core.contracts import PathLike

PSEUDO_REGISTRY_ENV = "GOLDILOCKS_PSEUDO_REGISTRY"
_REGISTRY_RESOURCE = "registry.toml"


@dataclass(frozen=True, slots=True)
class PseudoTable:
    """Scientific table facts and its complete acquisition description."""

    id: str
    provider: str
    upstream_table: str
    version: str
    functional: str
    relativistic: str
    accuracy: str
    licence: str
    citation: str
    elements: tuple[str, ...]
    asset: AssetSpec
    note: str = ""
    default: bool = False

    def covers(self, element: str) -> bool:
        """Return whether the table contains the element."""
        return element in self.elements


def load_tables(path: PathLike | None = None) -> dict[str, PseudoTable]:
    """Load complete table entries from an explicit or packaged registry."""
    registry_path = path or os.environ.get(PSEUDO_REGISTRY_ENV)
    if registry_path:
        with Path(registry_path).open("rb") as source:
            data = tomllib.load(source)
    else:
        registry = resources.files("goldilocks_core.pseudo").joinpath(
            _REGISTRY_RESOURCE
        )
        with registry.open("rb") as source:
            data = tomllib.load(source)
    return {
        table_id: _parse_table(table_id, entry, data["sources"])
        for table_id, entry in data["tables"].items()
    }


def default_table(tables: dict[str, PseudoTable] | None = None) -> PseudoTable:
    """Return the single table marked as the shipped default."""
    defaults = [table for table in (tables or load_tables()).values() if table.default]
    if len(defaults) != 1:
        names = ", ".join(table.id for table in defaults) or "none"
        raise LookupError(f"registry must have one default table; found {names}")
    return defaults[0]


def table_asset_specs(path: PathLike | None = None) -> tuple[AssetSpec, ...]:
    """Return all pseudopotential asset declarations."""
    return tuple(table.asset for table in load_tables(path).values())


def _parse_table(
    table_id: str,
    entry: dict[str, Any],
    sources: dict[str, Any],
) -> PseudoTable:
    provider = entry["provider"]
    upstream = entry["upstream_table"]
    version = str(entry["version"])
    if provider == "pseudodojo":
        base = sources["pseudodojo"]["base_url"].rstrip("/")
        files = (
            AssetFile(
                "pseudopotentials", "source/upf.tgz", f"{base}/{upstream}_upf.tgz"
            ),
            AssetFile("metadata", "source/djrepo.tgz", f"{base}/{upstream}_djrepo.tgz"),
        )
    elif provider == "sssp":
        api = sources["sssp"]["api_url"].rstrip("/")
        record = entry["record"]
        encoded = quote(upstream)
        prefix = f"{api}/records/{record}/files"
        files = (
            AssetFile(
                "pseudopotentials",
                "source/table.tar.gz",
                f"{prefix}/{encoded}.tar.gz/content",
            ),
            AssetFile(
                "metadata", "source/table.json", f"{prefix}/{encoded}.json/content"
            ),
        )
    else:
        raise ValueError(f"unsupported pseudopotential provider: {provider}")
    return PseudoTable(
        id=table_id,
        provider=provider,
        upstream_table=upstream,
        version=version,
        functional=entry["functional"],
        relativistic=entry["relativistic"],
        accuracy=entry["accuracy"],
        licence=entry["licence"],
        citation=entry["citation"],
        elements=tuple(entry["elements"]),
        asset=AssetSpec(table_id, version, files),
        note=entry.get("note", "").strip(),
        default=entry.get("default", False),
    )
