"""Structured pseudopotential metadata definitions."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, fields
from numbers import Real
from typing import Any

from goldilocks_core.functionals import normalize_functional_label


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
            ``PBEsol``, ``LDA``).
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

    def __post_init__(self) -> None:
        """Canonicalize supported functional labels from metadata producers."""
        self.functional = normalize_functional_label(self.functional)

    def to_dict(self) -> dict:
        """Return a dictionary representation of the metadata."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: object) -> PseudoMetadata:
        """Construct from a JSON-serializable dictionary.

        ``filepath``, ``filename``, and ``header_format`` are required; the
        remaining fields default to their constructor defaults when absent.
        Unknown keys and malformed value types are rejected so transport
        request errors surface as ``ValueError`` at this boundary rather than
        as a ``TypeError`` deeper in construction.

        Raises:
            ValueError: If ``data`` is not a dict, lacks a required field,
                contains unknown keys, or a value has an unexpected type.
        """
        if not isinstance(data, dict):
            raise ValueError(
                "PseudoMetadata.from_dict requires a JSON object; "
                f"got {type(data).__name__}"
            )
        known = frozenset(field.name for field in fields(cls))
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValueError(f"Unknown PseudoMetadata keys: {', '.join(unknown)}")
        missing = [
            name
            for name in ("filepath", "filename", "header_format")
            if name not in data
        ]
        if missing:
            raise ValueError(f"PseudoMetadata requires fields: {', '.join(missing)}")
        for required in ("filepath", "filename", "header_format"):
            if not isinstance(data[required], str):
                raise ValueError(
                    f"PseudoMetadata.{required} must be a string; "
                    f"got {data[required]!r}"
                )
        for optional_str_field in (
            "library",
            "source_set",
            "element",
            "pseudo_type",
            "functional",
            "relativistic",
            "source_pseudopotential",
        ):
            value = data.get(optional_str_field)
            if value is not None and not isinstance(value, str):
                raise ValueError(
                    f"PseudoMetadata.{optional_str_field} must be a string or None; "
                    f"got {value!r}"
                )
        z_valence = data.get("z_valence")
        if z_valence is not None and (
            isinstance(z_valence, bool) or not isinstance(z_valence, Real)
        ):
            raise ValueError(
                f"PseudoMetadata.z_valence must be a number or None; got {z_valence!r}"
            )
        if z_valence is not None and not math.isfinite(z_valence):
            raise ValueError(
                f"PseudoMetadata.z_valence must be a finite number; got {z_valence!r}"
            )
        pseudo_info = data.get("pseudo_info", {})
        if not isinstance(pseudo_info, dict):
            raise ValueError(
                "PseudoMetadata.pseudo_info must be an object or None; "
                f"got {pseudo_info!r}"
            )
        is_sssp = data.get("is_sssp", False)
        if not isinstance(is_sssp, bool):
            raise ValueError(
                f"PseudoMetadata.is_sssp must be a boolean; got {is_sssp!r}"
            )
        sssp_recommended_cutoff = data.get("sssp_recommended_cutoff")
        if sssp_recommended_cutoff is not None and not isinstance(
            sssp_recommended_cutoff, dict
        ):
            raise ValueError(
                "PseudoMetadata.sssp_recommended_cutoff must be an object or None; "
                f"got {sssp_recommended_cutoff!r}"
            )
        return cls(
            filepath=data["filepath"],
            filename=data["filename"],
            header_format=data["header_format"],
            library=data.get("library"),
            source_set=data.get("source_set"),
            element=data.get("element"),
            pseudo_type=data.get("pseudo_type"),
            functional=data.get("functional"),
            relativistic=data.get("relativistic"),
            z_valence=z_valence,
            pseudo_info=dict(pseudo_info),
            is_sssp=is_sssp,
            source_pseudopotential=data.get("source_pseudopotential"),
            sssp_recommended_cutoff=sssp_recommended_cutoff,
        )
