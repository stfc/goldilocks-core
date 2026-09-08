from __future__ import annotations

from typing import TypedDict

from goldilocks_core.analysis import StructureAnalysisRecord
from goldilocks_core.calculation import CalculationHints, CalculationIntent
from goldilocks_core.provenance import Provenance
from goldilocks_core.types import (
    PseudoAccuracy,
    PseudoType,
    RelativisticTreatment,
    SmearingType,
    VdwMethod,
)

DEFAULT_CONV_THR = 1e-6
DEFAULT_MIXING_BETA = 0.4
DEFAULT_ELECTRON_MAXSTEP = 80
METALLIC_SMEARING_WIDTH_RY = 0.01


class SmearingAdvice(TypedDict):
    smearing_type: SmearingType | None
    width_ry: float | None
    provenance: Provenance


class MagnetismAdvice(TypedDict):
    spin_polarized: bool
    magnetic_elements: list[str]
    provenance: Provenance


class SpinOrbitAdvice(TypedDict):
    enabled: bool
    consider: bool
    heavy_elements: list[str]
    provenance: Provenance


class PseudopotentialRequirements(TypedDict):
    functional: str
    accuracy: PseudoAccuracy
    pseudo_type: PseudoType | None
    relativistic: RelativisticTreatment
    provenance: Provenance


class ConvergenceAdvice(TypedDict):
    conv_thr: float
    provenance: Provenance
    mixing_beta: float
    electron_maxstep: int


class VdwAdvice(TypedDict):
    use_vdw: bool
    method: VdwMethod | None
    provenance: Provenance


class ParameterAdvice(TypedDict):
    smearing: SmearingAdvice
    magnetism: MagnetismAdvice
    spin_orbit: SpinOrbitAdvice
    pseudopotential_requirements: PseudopotentialRequirements
    convergence: ConvergenceAdvice
    vdw: VdwAdvice


def advise_parameters(
    analysis: StructureAnalysisRecord,
    intent: CalculationIntent | None = None,
    hints: CalculationHints | None = None,
) -> ParameterAdvice:
    """Resolve coupled scientific choices from analysis, intent, and user hints.

    SOC remains opt-in and determines the default pseudopotential relativity.
    Each decision carries its own provenance; explicit hints take precedence.
    """
    intent = intent or CalculationIntent()
    hints = hints or CalculationHints()

    spin_orbit = _advise_spin_orbit(analysis, hints)

    return {
        "smearing": _advise_smearing(analysis, hints),
        "magnetism": _advise_magnetism(analysis, hints),
        "spin_orbit": spin_orbit,
        "pseudopotential_requirements": _advise_pseudopotential_requirements(
            intent, hints, spin_orbit
        ),
        "convergence": _advise_convergence(hints),
        "vdw": _advise_vdw(analysis, hints),
    }


__all__ = ["ParameterAdvice", "PseudopotentialRequirements", "advise_parameters"]


def _advise_smearing(
    analysis: StructureAnalysisRecord,
    hints: CalculationHints,
) -> SmearingAdvice:
    if hints.smearing_type is not None or hints.smearing_width_ry is not None:
        return {
            "smearing_type": hints.smearing_type,
            "width_ry": hints.smearing_width_ry,
            "provenance": Provenance(
                source="user_hint",
                reason="Use operator-provided smearing settings.",
            ),
        }

    if analysis["electronic_character"] == "metal":
        return {
            "smearing_type": "cold",
            "width_ry": METALLIC_SMEARING_WIDTH_RY,
            "provenance": Provenance(
                source="analysis",
                reason=(
                    "Model-classified metallic systems benefit from modest smearing."
                ),
            ),
        }

    if analysis["electronic_character"] == "likely_metal":
        return {
            "smearing_type": "cold",
            "width_ry": METALLIC_SMEARING_WIDTH_RY,
            "provenance": Provenance(
                source="analysis",
                reason="Likely metallic composition benefits from modest smearing.",
                warnings=("Metallicity was inferred from structure-only heuristics.",),
            ),
        }

    if analysis["electronic_character"] == "insulator":
        return {
            "smearing_type": "fixed",
            "width_ry": None,
            "provenance": Provenance(
                source="analysis",
                reason="Insulating electronic character supports fixed occupations.",
            ),
        }

    return {
        "smearing_type": "fixed",
        "width_ry": None,
        "provenance": Provenance(
            source="default",
            reason="Metallicity is unknown; use fixed occupations by default.",
        ),
    }


def _advise_magnetism(
    analysis: StructureAnalysisRecord,
    hints: CalculationHints,
) -> MagnetismAdvice:
    if hints.spin_polarized is not None:
        return {
            "spin_polarized": hints.spin_polarized,
            "magnetic_elements": analysis["magnetic_elements"],
            "provenance": Provenance(
                source="user_hint",
                reason="Use the operator-provided spin-polarization setting.",
            ),
        }

    if analysis["magnetic_elements"]:
        return {
            "spin_polarized": True,
            "magnetic_elements": analysis["magnetic_elements"],
            "provenance": Provenance(
                source="analysis",
                reason="Magnetic candidate elements are present in the structure.",
            ),
        }

    return {
        "spin_polarized": False,
        "magnetic_elements": [],
        "provenance": Provenance(
            source="default",
            reason="No magnetic candidate elements were detected.",
        ),
    }


def _advise_spin_orbit(
    analysis: StructureAnalysisRecord,
    hints: CalculationHints,
) -> SpinOrbitAdvice:
    """SOC is never auto-enabled. Heavy elements set ``consider=True``;
    the operator must set ``spin_orbit_coupling=True`` to enable it."""
    if hints.spin_orbit_coupling is not None:
        return {
            "enabled": hints.spin_orbit_coupling,
            "consider": False,
            "heavy_elements": analysis["heavy_elements"],
            "provenance": Provenance(
                source="user_hint",
                reason="Use the operator-provided SOC setting.",
            ),
        }

    if analysis["heavy_elements"]:
        return {
            "enabled": False,
            "consider": True,
            "heavy_elements": analysis["heavy_elements"],
            "provenance": Provenance(
                source="analysis",
                reason="Period-5-or-heavier elements make SOC worth considering.",
                warnings=(
                    "SOC is not enabled automatically because it changes cost "
                    "and setup.",
                ),
            ),
        }

    return {
        "enabled": False,
        "consider": False,
        "heavy_elements": [],
        "provenance": Provenance(
            source="default",
            reason="No period-5-or-heavier elements were detected.",
        ),
    }


def _advise_pseudopotential_requirements(
    intent: CalculationIntent,
    hints: CalculationHints,
    spin_orbit: SpinOrbitAdvice,
) -> PseudopotentialRequirements:
    accuracy = hints.pseudo_accuracy or intent.pseudo_accuracy
    relativistic = hints.relativistic_mode or (
        "full" if spin_orbit["enabled"] else "scalar"
    )
    hinted = (
        hints.pseudo_accuracy is not None
        or hints.pseudo_type is not None
        or hints.relativistic_mode is not None
    )
    source = "user_hint" if hinted else "default"
    warnings: tuple[str, ...] = ()

    if spin_orbit["enabled"] and hints.relativistic_mode is None:
        source = spin_orbit["provenance"].source
    elif spin_orbit["consider"] and not spin_orbit["enabled"]:
        warnings = (
            "Heavy elements are present; fully-relativistic pseudos may be needed "
            "if SOC is enabled.",
        )

    return {
        "functional": intent.functional,
        "accuracy": accuracy,
        "pseudo_type": hints.pseudo_type,
        "relativistic": relativistic,
        "provenance": Provenance(
            source=source,
            reason=(
                "Derive pseudopotential requirements from calculation intent, "
                "operator hints, and spin-orbit policy."
            ),
            warnings=warnings,
        ),
    }


def _advise_convergence(hints: CalculationHints) -> ConvergenceAdvice:
    if (
        hints.conv_thr is not None
        or hints.mixing_beta is not None
        or hints.electron_maxstep is not None
    ):
        return {
            "conv_thr": hints.conv_thr
            if hints.conv_thr is not None
            else DEFAULT_CONV_THR,
            "provenance": Provenance(
                source="user_hint",
                reason="Use operator-provided convergence settings where supplied.",
            ),
            "mixing_beta": hints.mixing_beta
            if hints.mixing_beta is not None
            else DEFAULT_MIXING_BETA,
            "electron_maxstep": hints.electron_maxstep
            if hints.electron_maxstep is not None
            else DEFAULT_ELECTRON_MAXSTEP,
        }

    return {
        "conv_thr": DEFAULT_CONV_THR,
        "provenance": Provenance(
            source="default",
            reason="Use package default SCF convergence settings.",
        ),
        "mixing_beta": DEFAULT_MIXING_BETA,
        "electron_maxstep": DEFAULT_ELECTRON_MAXSTEP,
    }


def _advise_vdw(
    analysis: StructureAnalysisRecord,
    hints: CalculationHints,
) -> VdwAdvice:
    """Low-dimensional structures default to D3BJ;
    3D/unknown defaults to no correction. Operator hints always win."""
    if hints.use_vdw is not None:
        method = (hints.vdw_method or "d3bj") if hints.use_vdw else None
        return {
            "use_vdw": hints.use_vdw,
            "method": method,
            "provenance": Provenance(
                source="user_hint",
                reason="Use the operator-provided vdW dispersion setting.",
            ),
        }

    if analysis["low_dimensional"]:
        method = hints.vdw_method or "d3bj"
        reason = (
            f"Connectivity-derived {analysis['dimensionality']} classification "
            "indicates a low-dimensional heuristic; D3BJ is the "
            "conservative package default because dispersion may be important. "
            "Override with CalculationHints(use_vdw=..., vdw_method=...) as needed."
            if hints.vdw_method is None
            else (
                f"Connectivity-derived {analysis['dimensionality']} classification "
                "indicates a low-dimensional heuristic; use the "
                f"operator-provided {method} vdW method. Override with "
                "CalculationHints(use_vdw=...) as needed."
            )
        )
        return {
            "use_vdw": True,
            "method": method,
            "provenance": Provenance(
                source="analysis",
                reason=reason,
            ),
        }

    warnings: tuple[str, ...] = ()
    if hints.vdw_method is not None:
        warnings = (
            f"vdw_method={hints.vdw_method!r} was ignored because vdW is off for "
            "this 3D/undetermined system; pass use_vdw=True to force it.",
        )

    return {
        "use_vdw": False,
        "method": None,
        "provenance": Provenance(
            source="default",
            reason=(
                "3D bulk or undetermined dimensionality; no vdW correction by "
                "default. Set use_vdw=True for layered or molecular systems."
            ),
            warnings=warnings,
        ),
    }
