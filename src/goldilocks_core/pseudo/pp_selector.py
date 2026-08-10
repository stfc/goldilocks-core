"""Pseudopotential selection utilities."""

from __future__ import annotations

from goldilocks_core.pseudo.pp_metadata import PseudoMetadata
from goldilocks_core.pseudo.pp_registry import (
    filter_by_element,
    filter_by_functional,
    filter_by_pseudo_type,
    filter_by_relativistic,
)


def select_pseudos(
    metadata_list: list[PseudoMetadata],
    *,
    element: str | None = None,
    functional: str | None = None,
    pseudo_type: str | None = None,
    relativistic: str | None = None,
) -> list[PseudoMetadata]:
    """Select pseudopotentials matching optional filter criteria."""
    selected = metadata_list

    if element is not None:
        selected = filter_by_element(selected, element)
    if functional is not None:
        selected = filter_by_functional(selected, functional)
    if pseudo_type is not None:
        selected = filter_by_pseudo_type(selected, pseudo_type)
    if relativistic is not None:
        selected = filter_by_relativistic(selected, relativistic)

    return selected
