from __future__ import annotations

from dataclasses import dataclass

from goldilocks_core.advice._hints import has_hint
from goldilocks_core.advice.soc import SpinOrbitAdvice
from goldilocks_core.calculation import CalculationIntent, PseudoHints
from goldilocks_core.functionals import normalize_functional_label
from goldilocks_core.provenance import Provenance
from goldilocks_core.types import (
    PseudoAccuracy,
    PseudoType,
    RelativisticTreatment,
)
from goldilocks_core.validation import validate_relativistic_mode


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
                f"precision'; got {self.accuracy!r}"
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
        validate_relativistic_mode(
            self.relativistic, "PseudopotentialRequirements.relativistic"
        )


def advise_pseudopotential_requirements(
    intent: CalculationIntent,
    hints: PseudoHints,
    spin_orbit: SpinOrbitAdvice,
) -> PseudopotentialRequirements:
    accuracy = hints.accuracy or intent.pseudo_accuracy
    relativistic = hints.relativistic_mode or (
        "full" if spin_orbit.enabled else "scalar"
    )
    source = "user_hint" if has_hint(hints) else "default"
    warnings: tuple[str, ...] = ()

    if spin_orbit.enabled and hints.relativistic_mode is None:
        source = spin_orbit.provenance.source
    elif spin_orbit.consider and not spin_orbit.enabled:
        warnings = (
            "Heavy elements are present; fully-relativistic pseudos may be needed "
            "if SOC is enabled.",
        )

    return PseudopotentialRequirements(
        functional=intent.functional,
        accuracy=accuracy,
        pseudo_type=hints.pseudo_type,
        relativistic=relativistic,
        provenance=Provenance(
            source=source,
            reason=(
                "Derive pseudopotential requirements from calculation intent, "
                "operator hints, and spin-orbit policy."
            ),
            warnings=warnings,
        ),
    )
