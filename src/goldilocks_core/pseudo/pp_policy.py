"""Pseudopotential selection policy utilities."""

from __future__ import annotations

from dataclasses import dataclass

from goldilocks_core.pseudo.pp_metadata import PseudoMetadata


@dataclass(frozen=True, slots=True)
class PseudoPolicy:
    """Selection policy describing the allowed pseudo search space.

    Applied by ``apply_pseudo_policy()`` to filter a metadata list
    before ranking.

    Attributes:
        relativistic_mode: required relativistic mode: ``scalar``,
            ``full``, or ``none`` (no filter).
        preferred_functional: only accept pseudos targeting this
            functional.
        allowed_sources: only accept pseudos from these libraries.
            Empty means no filter.
        allowed_pseudo_types: only accept these pseudo types (e.g.
            ``NC``, ``USPP``). Empty means no filter.
    """

    relativistic_mode: str = "none"
    preferred_functional: str | None = None
    allowed_sources: tuple[str, ...] = ()
    allowed_pseudo_types: tuple[str, ...] = ()


def apply_pseudo_policy(
    metadata_list: list[PseudoMetadata],
    policy: PseudoPolicy,
) -> list[PseudoMetadata]:
    """Apply a pseudo selection policy to a metadata list."""
    selected = metadata_list

    if policy.preferred_functional is not None:
        selected = [
            metadata
            for metadata in selected
            if metadata.functional == policy.preferred_functional
        ]

    if policy.allowed_sources:
        selected = [
            metadata
            for metadata in selected
            if metadata.library in policy.allowed_sources
        ]

    if policy.allowed_pseudo_types:
        selected = [
            metadata
            for metadata in selected
            if metadata.pseudo_type in policy.allowed_pseudo_types
        ]

    if policy.relativistic_mode != "none":
        selected = [
            metadata
            for metadata in selected
            if metadata.relativistic == policy.relativistic_mode
        ]

    return selected
