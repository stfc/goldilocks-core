from __future__ import annotations

from dataclasses import dataclass

from goldilocks_core.contracts.provenance import Provenance
from goldilocks_core.contracts.serial import to_jsonable
from goldilocks_core.contracts.types import (
    JsonDict,
    PseudoAccuracy,
    PseudoType,
    RelativisticTreatment,
    VdwMethod,
)
from goldilocks_core.contracts.validate import _validate_relativistic_mode
from goldilocks_core.functionals import normalize_functional_label


@dataclass(frozen=True, slots=True)
class SmearingAdvice:
    """Advised occupation treatment.

    ``smearing_type`` ``None`` or ``"fixed"`` means fixed occupations; a
    named smearing type activates ``width_ry``, which is in Rydberg and
    ``None`` only alongside fixed occupations. ``provenance`` states the
    source precedence: an operator hint wins over the structure analysis,
    which wins over the package default.
    """

    smearing_type: str | None
    width_ry: float | None
    provenance: Provenance

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class MagnetismAdvice:
    spin_polarized: bool
    magnetic_elements: tuple[str, ...]
    provenance: Provenance

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class SpinOrbitAdvice:
    enabled: bool
    consider: bool
    heavy_elements: tuple[str, ...]
    provenance: Provenance

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class PseudopotentialRequirements:
    functional: str
    accuracy: PseudoAccuracy
    pseudo_type: PseudoType | None
    relativistic: RelativisticTreatment
    provenance: Provenance

    def __post_init__(self) -> None:
        functional = normalize_functional_label(self.functional)
        if functional is None:
            raise ValueError(
                "PseudopotentialRequirements.functional must be a non-empty "
                f"string; got {self.functional!r}"
            )
        object.__setattr__(self, "functional", functional)
        if self.accuracy not in {"efficiency", "precision"}:
            raise ValueError(
                "PseudopotentialRequirements.accuracy must be 'efficiency' or "
                f"'precision'; got {self.accuracy!r}"
            )
        if self.pseudo_type is not None and self.pseudo_type not in {
            "NC",
            "USPP",
            "PAW",
        }:
            raise ValueError(
                "PseudopotentialRequirements.pseudo_type must be NC, USPP, "
                f"PAW, or None; got {self.pseudo_type!r}"
            )
        _validate_relativistic_mode(
            self.relativistic, "PseudopotentialRequirements.relativistic"
        )

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class ConvergenceAdvice:
    conv_thr: float
    provenance: Provenance
    mixing_beta: float = 0.4
    electron_maxstep: int = 80

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class VdwAdvice:
    use_vdw: bool
    method: VdwMethod | None
    provenance: Provenance

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class ParameterAdvice:
    smearing: SmearingAdvice
    magnetism: MagnetismAdvice
    spin_orbit: SpinOrbitAdvice
    pseudopotential_requirements: PseudopotentialRequirements
    convergence: ConvergenceAdvice
    vdw: VdwAdvice

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)
