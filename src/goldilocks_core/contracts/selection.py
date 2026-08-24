from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

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
        for field_name in ("provider", "element", "source_identifier", "table_id"):
            _validate_optional_nonempty_str(
                getattr(self, field_name), f"PseudoMetadata.{field_name}"
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
        document = to_jsonable(self)
        document.pop("filepath")
        return document


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
