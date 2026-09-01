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
    """Advised occupation smearing settings.

    When ``smearing_type`` is None, the generator writes fixed
    occupations.

    Attributes:
        smearing_type: smearing method (e.g. ``cold``,
            ``gaussian``, ``mp``, ``fixed``), or None for fixed
            occupations.
        width_ry: smearing width in Rydberg, or None when using
            fixed occupations.
        provenance: why this advice was chosen.
    """

    smearing_type: str | None
    width_ry: float | None
    provenance: Provenance

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class MagnetismAdvice:
    """Advised spin-polarization setting.

    ``spin_polarized`` is True when magnetic candidate elements are
    present or when the operator explicitly requests it.

    Attributes:
        spin_polarized: whether to run a spin-polarized calculation.
        magnetic_elements: elements that triggered magnetic
            consideration.
        provenance: why this advice was chosen.
    """

    spin_polarized: bool
    magnetic_elements: tuple[str, ...]
    provenance: Provenance

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class SpinOrbitAdvice:
    """Advised spin-orbit setting and SOC relevance facts.

    SOC is never enabled automatically. When ``consider`` is True,
    the operator should evaluate whether to enable SOC via
    ``CalculationHints(spin_orbit_coupling=True)``.

    Attributes:
        enabled: whether SOC is enabled in the recommendation.
        consider: whether SOC is worth considering (heavy
            elements present, not yet enabled).
        heavy_elements: elements with period ≥ 5 that make SOC
            relevant.
        provenance: why this advice was chosen.
    """

    enabled: bool
    consider: bool
    heavy_elements: tuple[str, ...]
    provenance: Provenance

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class PseudopotentialRequirements:
    """Scientific constraints used to select pseudopotentials.

    The record contains no provider, table, filename, path, or cutoff choice.
    Advise derives it from calculation intent, operator hints, and SOC policy;
    Select resolves it against explicitly available metadata.
    """

    functional: str
    accuracy: PseudoAccuracy
    pseudo_type: PseudoType | None
    relativistic: RelativisticTreatment
    provenance: Provenance

    def __post_init__(self) -> None:
        """Normalize and validate the scientific selection constraints."""
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
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class ConvergenceAdvice:
    """Advised convergence defaults for the calculation.

    All values are in Rydberg or unitless unless otherwise noted.

    Attributes:
        conv_thr: SCF energy convergence threshold in Rydberg.
        provenance: why these values were chosen.
        mixing_beta: charge-density mixing factor.
        electron_maxstep: maximum number of SCF iterations.
    """

    conv_thr: float
    provenance: Provenance
    mixing_beta: float = 0.4
    electron_maxstep: int = 80

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class VdwAdvice:
    """Advised van der Waals dispersion correction.

    Method labels are code-agnostic physics names; the generator maps them
    to code-specific settings (e.g. ``d3bj`` → QE
    ``vdw_corr='grimme-d3'`` with ``dftd3_version=4``).

    The built-in Advise stage treats its connectivity-derived
    low-dimensional heuristic as a conservative D3BJ default because
    dispersion may be important. It does not establish that dispersion
    dominates; the operator can override the setting or method with
    ``CalculationHints``. Heavy elements only mark SOC for consideration
    because SOC changes calculation cost, setup, and pseudopotential
    requirements.

    Attributes:
        use_vdw: whether a dispersion correction is applied.
        method: dispersion method (``d3``, ``d3bj``, ``ts``, ``mbd``), or
            None when ``use_vdw`` is False.
        provenance: why this advice was chosen.
    """

    use_vdw: bool
    method: VdwMethod | None
    provenance: Provenance

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class ParameterAdvice:
    """Complete Advise-stage output.

    Advice records contain scientific and numerical policy only. Concrete
    pseudopotential resources remain Select-stage output.
    """

    smearing: SmearingAdvice
    magnetism: MagnetismAdvice
    spin_orbit: SpinOrbitAdvice
    pseudopotential_requirements: PseudopotentialRequirements
    convergence: ConvergenceAdvice
    vdw: VdwAdvice

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)
