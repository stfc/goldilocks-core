"""Structured pseudopotential metadata definitions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class PseudoMetadata:
    """Structured pseudopotential metadata extracted from a UPF file.

    Produced by ``parse_upf_metadata()`` and consumed by pseudo
    selection. Not frozen: callers may mutate fields when
    synthesizing test metadata.

    Attributes:
        filepath: full path to the UPF file on disk.
        filename: basename of the UPF file (e.g. ``Si.UPF``).
        header_format: UPF header format: ``attr`` or ``text``.
        library: pseudo library name (e.g. ``SSSP``), extracted
            from the file path.
        source_set: source set within the library (e.g.
            ``efficiency``, ``precision``).
        element: element symbol this pseudo is for (e.g.
            ``Si``).
        pseudo_type: normalized pseudo type: ``NC``, ``USPP``,
            or ``PAW``.
        functional: normalized functional label (e.g. ``PBE``,
            ``PBESOL``, ``LDA``).
        relativistic: normalized relativistic mode: ``scalar``,
            ``full``, or ``non-relativistic``.
        z_valence: valence charge.
        pseudo_info: raw header fields not mapped to typed
            attributes.
        is_sssp: whether this pseudo is from the SSSP library.
        source_pseudopotential: original pseudo identifier from
            the UPF header.
        sssp_recommended_cutoff: SSSP recommended cutoffs dict
            with ``ecutwfc_ry`` and ``ecutrho_ry`` in Rydberg.
    """

    filepath: str
    filename: str
    header_format: str
    library: str | None = None
    source_set: str | None = None
    element: str | None = None
    pseudo_type: str | None = None
    functional: str | None = None
    relativistic: str | None = None
    z_valence: float | None = None
    pseudo_info: dict[str, Any] = field(default_factory=dict)
    is_sssp: bool = False
    source_pseudopotential: str | None = None
    sssp_recommended_cutoff: dict[str, Any] | None = None

    def to_dict(self) -> dict:
        """Return a dictionary representation of the metadata."""
        return asdict(self)
