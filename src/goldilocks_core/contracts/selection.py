from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import PurePath, PurePosixPath, PureWindowsPath

from goldilocks_core.contracts.provenance import Provenance
from goldilocks_core.contracts.serial import to_jsonable
from goldilocks_core.contracts.types import (
    JsonDict,
    PseudoAccuracy,
    PseudoType,
    RelativisticTreatment,
)
from goldilocks_core.contracts.validate import (
    _validate_finite_positive,
    _validate_optional_nonempty_str,
    _validate_relativistic_mode,
)
from goldilocks_core.functionals import normalize_functional_label


@dataclass(frozen=True, slots=True)
class PseudoCutoffs:
    ecutwfc_ry: float | None = None
    ecutrho_ry: float | None = None

    def __post_init__(self) -> None:
        for field_name in ("ecutwfc_ry", "ecutrho_ry"):
            value = getattr(self, field_name)
            if value is not None:
                _validate_finite_positive(value, f"PseudoCutoffs.{field_name}")
                object.__setattr__(self, field_name, float(value))


@dataclass(frozen=True, slots=True)
class PseudoMetadata:
    filepath: str
    filename: str
    header_format: str
    provider: str | None = None
    accuracy: PseudoAccuracy | None = None
    element: str | None = None
    pseudo_type: PseudoType | None = None
    functional: str | None = None
    relativistic: RelativisticTreatment | None = None
    z_valence: float | None = None
    table_id: str | None = None
    cutoffs: PseudoCutoffs | None = None
    source_identifier: str | None = None
    content_sha256: str | None = None
    content_size_bytes: int | None = None
    frozen_4f_core: bool = False
    pseudo_info: JsonDict = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("filepath", "filename", "header_format"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"PseudoMetadata.{field_name} must be a non-empty string; "
                    f"got {value!r}"
                )
        if (
            self.filename in {".", ".."}
            or PurePath(self.filename).name != self.filename
            or "/" in self.filename
            or "\\" in self.filename
        ):
            raise ValueError("PseudoMetadata.filename must be one filename")
        for field_name in ("provider", "element", "source_identifier", "table_id"):
            _validate_optional_nonempty_str(
                getattr(self, field_name), f"PseudoMetadata.{field_name}"
            )
        if self.source_identifier is not None and (
            PurePosixPath(self.source_identifier).is_absolute()
            or PureWindowsPath(self.source_identifier).is_absolute()
            or self.source_identifier.startswith("~")
        ):
            raise ValueError(
                "PseudoMetadata.source_identifier must be a portable source identity, "
                "not a host path"
            )
        if (self.content_sha256 is None) != (self.content_size_bytes is None):
            raise ValueError(
                "PseudoMetadata content_sha256 and content_size_bytes must both be "
                "present or both be None"
            )
        if (
            self.content_sha256 is not None
            and re.fullmatch(r"[0-9a-f]{64}", self.content_sha256) is None
        ):
            raise ValueError(
                "PseudoMetadata.content_sha256 must be a lowercase SHA-256 digest"
            )
        if self.content_size_bytes is not None and (
            isinstance(self.content_size_bytes, bool)
            or not isinstance(self.content_size_bytes, int)
            or self.content_size_bytes < 0
        ):
            raise ValueError(
                "PseudoMetadata.content_size_bytes must be a non-negative integer"
            )
        if self.accuracy is not None and self.accuracy not in {
            "efficiency",
            "precision",
        }:
            raise ValueError(
                "PseudoMetadata.accuracy must be 'efficiency', 'precision', "
                f"or None; got {self.accuracy!r}"
            )
        if self.pseudo_type is not None and self.pseudo_type not in {
            "NC",
            "USPP",
            "PAW",
        }:
            raise ValueError(
                "PseudoMetadata.pseudo_type must be NC, USPP, PAW, or None; "
                f"got {self.pseudo_type!r}"
            )
        _validate_relativistic_mode(self.relativistic, "PseudoMetadata.relativistic")
        functional = normalize_functional_label(self.functional)
        object.__setattr__(self, "functional", functional)
        if self.z_valence is not None:
            _validate_finite_positive(self.z_valence, "PseudoMetadata.z_valence")
            object.__setattr__(self, "z_valence", float(self.z_valence))
        if self.cutoffs is not None and not isinstance(self.cutoffs, PseudoCutoffs):
            if not isinstance(self.cutoffs, Mapping):
                raise ValueError(
                    "PseudoMetadata.cutoffs must be PseudoCutoffs, an object, or None"
                )
            try:
                cutoffs = PseudoCutoffs(**dict(self.cutoffs))
            except TypeError as error:
                raise ValueError(f"Invalid PseudoMetadata.cutoffs: {error}") from error
            object.__setattr__(self, "cutoffs", cutoffs)
        if not isinstance(self.frozen_4f_core, bool):
            raise ValueError("PseudoMetadata.frozen_4f_core must be a boolean")
        if not isinstance(self.pseudo_info, dict):
            raise ValueError("PseudoMetadata.pseudo_info must be a dictionary")
        object.__setattr__(self, "pseudo_info", dict(self.pseudo_info))
        if not isinstance(self.warnings, tuple):
            object.__setattr__(self, "warnings", tuple(self.warnings))
        if any(
            not isinstance(warning, str) or not warning for warning in self.warnings
        ):
            raise ValueError("PseudoMetadata.warnings must contain non-empty strings")

    def to_dict(self) -> JsonDict:
        return {
            "filename": self.filename,
            "header_format": self.header_format,
            "provider": self.provider,
            "accuracy": self.accuracy,
            "element": self.element,
            "pseudo_type": self.pseudo_type,
            "functional": self.functional,
            "relativistic": self.relativistic,
            "z_valence": self.z_valence,
            "table_id": self.table_id,
            "cutoffs": to_jsonable(self.cutoffs),
            "source_identifier": self.source_identifier,
            "content_sha256": self.content_sha256,
            "content_size_bytes": self.content_size_bytes,
            "frozen_4f_core": self.frozen_4f_core,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class PseudopotentialSelection:
    element: str
    filename: str | None
    filepath: str | None
    functional: str | None
    relativistic: RelativisticTreatment | None
    ecutwfc_ry: float | None
    ecutrho_ry: float | None
    provenance: Provenance
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.element, str) or not self.element.strip():
            raise ValueError(
                "PseudopotentialSelection.element must be a non-empty string"
            )
        if (self.filename is None) != (self.filepath is None):
            raise ValueError(
                "PseudopotentialSelection filename and filepath must both be "
                "present or both be None"
            )
        for field_name in ("filename", "filepath"):
            _validate_optional_nonempty_str(
                getattr(self, field_name), f"PseudopotentialSelection.{field_name}"
            )
        functional = normalize_functional_label(self.functional)
        object.__setattr__(self, "functional", functional)
        _validate_relativistic_mode(
            self.relativistic, "PseudopotentialSelection.relativistic"
        )
        for field_name in ("ecutwfc_ry", "ecutrho_ry"):
            value = getattr(self, field_name)
            if value is not None:
                _validate_finite_positive(
                    value, f"PseudopotentialSelection.{field_name}"
                )
                object.__setattr__(self, field_name, float(value))
        if self.filename is None and any(
            value is not None
            for value in (
                self.functional,
                self.relativistic,
                self.ecutwfc_ry,
                self.ecutrho_ry,
            )
        ):
            raise ValueError(
                "An unresolved PseudopotentialSelection cannot carry scientific "
                "metadata"
            )

    def to_dict(self) -> JsonDict:
        document = to_jsonable(self)
        document.pop("filepath")
        return document


@dataclass(frozen=True, slots=True)
class SelectionRecord:
    pseudopotentials: tuple[PseudopotentialSelection, ...]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> JsonDict:
        return {
            "pseudopotentials": [item.to_dict() for item in self.pseudopotentials],
            "warnings": list(self.warnings),
        }
