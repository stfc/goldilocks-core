"""Pseudopotential metadata from verified assets or explicit local roots."""

from __future__ import annotations

import json
from pathlib import Path

from goldilocks_core.assets import AssetStore
from goldilocks_core.contracts import PseudoMetadata
from goldilocks_core.functionals import normalize_functional_label
from goldilocks_core.pseudo.installed import load_installed_table
from goldilocks_core.pseudo.parse_upf import parse_upf_metadata
from goldilocks_core.pseudo.registry import default_table, load_tables


def load_pseudo_metadata(root: str | Path) -> list[PseudoMetadata]:
    """Load UPFs under an explicit root and discover recognized cutoff metadata."""
    root = Path(root).resolve()
    upf_files = sorted(root.rglob("*.upf")) + sorted(root.rglob("*.UPF"))
    metadata = [parse_upf_metadata(path) for path in upf_files]
    for item in metadata:
        if item.sssp_recommended_cutoff is not None:
            continue
        cutoffs = _discover_cutoffs(Path(item.filepath), root, item.element)
        if cutoffs is None:
            subject = item.element or item.filename
            item.pseudo_info.setdefault("warnings", []).append(
                f"No complete cutoff metadata found for {subject} under custom "
                f"pseudopotential root {root}."
            )
        else:
            item.sssp_recommended_cutoff = cutoffs
    return metadata


def load_installed_pseudo_metadata(
    table_id: str | None = None,
    *,
    store: AssetStore | None = None,
) -> tuple[PseudoMetadata, ...]:
    """Load one verified registered table through the shared asset-store seam."""
    tables = load_tables()
    table = tables[table_id] if table_id is not None else default_table(tables)
    installed = (store or AssetStore()).resolve(table.asset.id, table.asset.version)
    return load_installed_table(installed)


def filter_by_element(
    metadata_list: list[PseudoMetadata],
    element: str,
) -> list[PseudoMetadata]:
    """Filter pseudopotential metadata by element symbol."""
    return [metadata for metadata in metadata_list if metadata.element == element]


def filter_by_functional(
    metadata_list: list[PseudoMetadata],
    functional: str,
) -> list[PseudoMetadata]:
    """Filter pseudopotential metadata by canonical functional label."""
    canonical = normalize_functional_label(functional)
    if canonical is None:
        return []
    return [
        metadata
        for metadata in metadata_list
        if normalize_functional_label(metadata.functional) == canonical
    ]


def filter_by_pseudo_type(
    metadata_list: list[PseudoMetadata],
    pseudo_type: str,
) -> list[PseudoMetadata]:
    """Filter pseudopotential metadata by pseudo type."""
    return [
        metadata for metadata in metadata_list if metadata.pseudo_type == pseudo_type
    ]


def filter_by_relativistic(
    metadata_list: list[PseudoMetadata],
    relativistic: str,
) -> list[PseudoMetadata]:
    """Filter pseudopotential metadata by relativistic mode."""
    return [
        metadata for metadata in metadata_list if metadata.relativistic == relativistic
    ]


def _discover_cutoffs(
    upf: Path,
    root: Path,
    element: str | None,
) -> dict[str, float] | None:
    if element is None:
        return None
    directory = upf.parent
    while directory == root or root in directory.parents:
        candidates = sorted(directory.glob("*.json"))
        if directory.parent == root or root in directory.parent.parents:
            candidates += [directory.parent / f"{directory.name}.json"]
        for candidate in dict.fromkeys(candidates):
            if not candidate.is_file():
                continue
            try:
                entry = json.loads(candidate.read_text()).get(element)
            except (AttributeError, json.JSONDecodeError):
                continue
            if not isinstance(entry, dict):
                continue
            wfc = entry.get("ecutwfc_ry", entry.get("cutoff_wfc"))
            rho = entry.get("ecutrho_ry", entry.get("cutoff_rho"))
            try:
                values = {"ecutwfc_ry": float(wfc), "ecutrho_ry": float(rho)}
            except (TypeError, ValueError):
                continue
            if all(value > 0 for value in values.values()):
                return values
        if directory == root:
            break
        directory = directory.parent
    return None
