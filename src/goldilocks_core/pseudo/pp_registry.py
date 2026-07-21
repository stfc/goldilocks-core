"""Local pseudopotential registry utilities."""

from __future__ import annotations

from pathlib import Path

from goldilocks_core.functionals import normalize_functional_label
from goldilocks_core.pseudo.parse_upf import parse_upf_metadata
from goldilocks_core.pseudo.pp_metadata import PseudoMetadata


def load_pseudo_metadata(root: str | Path) -> list[PseudoMetadata]:
    """Load metadata for all UPF files under a local pseudo root."""
    root = Path(root)

    upf_files = sorted(root.rglob("*.upf")) + sorted(root.rglob("*.UPF"))
    return [parse_upf_metadata(path) for path in upf_files]


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
