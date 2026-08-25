from __future__ import annotations

from dataclasses import dataclass

from goldilocks_core.contracts.serial import to_jsonable
from goldilocks_core.contracts.types import (
    CalcTask,
    CodeName,
    JsonDict,
    KPointGrid,
    PseudoAccuracy,
    PseudoType,
    RelativisticTreatment,
    SmearingType,
    VdwMethod,
)
from goldilocks_core.contracts.validate import (
    _validate_finite_positive,
    _validate_kpoint_grid,
    _validate_optional_boolean,
    _validate_positive_integer,
    _validate_relativistic_mode,
    _validate_smearing,
    _validate_vdw_method,
)
from goldilocks_core.functionals import normalize_functional_label


@dataclass(frozen=True, slots=True)
class KmeshHints:
    k_grid: KPointGrid | None = None
    k_spacing: float | None = None


@dataclass(frozen=True, slots=True)
class SmearingHints:
    smearing_type: SmearingType | None = None
    smearing_width_ry: float | None = None


@dataclass(frozen=True, slots=True)
class SpinHints:
    spin_polarized: bool | None = None
    spin_orbit_coupling: bool | None = None


@dataclass(frozen=True, slots=True)
class PseudoHints:
    accuracy: PseudoAccuracy | None = None
    pseudo_type: PseudoType | None = None
    relativistic_mode: RelativisticTreatment | None = None


@dataclass(frozen=True, slots=True)
class ConvergenceHints:
    conv_thr: float | None = None
    mixing_beta: float | None = None
    electron_maxstep: int | None = None


@dataclass(frozen=True, slots=True)
class VdwHints:
    use_vdw: bool | None = None
    vdw_method: VdwMethod | None = None


@dataclass(frozen=True, slots=True)
class CalculationIntent:
    code: CodeName = "quantum_espresso"
    task: CalcTask = "scf_single_point"
    functional: str = "PBEsol"
    pseudo_accuracy: PseudoAccuracy = "efficiency"

    def __post_init__(self) -> None:
        for field_name in ("code", "task"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"CalculationIntent.{field_name} must be a non-empty string; "
                    f"got {value!r}"
                )
        if self.pseudo_accuracy not in {"efficiency", "precision"}:
            raise ValueError(
                "CalculationIntent.pseudo_accuracy must be 'efficiency' or "
                f"'precision'; got {self.pseudo_accuracy!r}"
            )

        functional = normalize_functional_label(self.functional)
        if functional is None:
            raise ValueError(
                "CalculationIntent.functional must be a non-empty string; "
                f"got {self.functional!r}"
            )
        object.__setattr__(self, "functional", functional)

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class CalculationHints:
    """Optional operator overrides. ``None`` means let Core decide.
    Non-None records ``user_hint`` provenance. Partial overrides supported.
    Units: ``k_spacing`` in Å⁻¹ (VASP KSPACING),
    ``smearing_width_ry`` and ``conv_thr`` in Rydberg."""

    k_spacing: float | None = None
    k_grid: KPointGrid | None = None
    smearing_type: SmearingType | None = None
    smearing_width_ry: float | None = None
    spin_polarized: bool | None = None
    spin_orbit_coupling: bool | None = None
    pseudo_accuracy: PseudoAccuracy | None = None
    pseudo_type: PseudoType | None = None
    relativistic_mode: RelativisticTreatment | None = None
    conv_thr: float | None = None
    mixing_beta: float | None = None
    electron_maxstep: int | None = None
    use_vdw: bool | None = None
    vdw_method: VdwMethod | None = None

    def __post_init__(self) -> None:
        if self.k_spacing is not None:
            _validate_finite_positive(self.k_spacing, "CalculationHints.k_spacing")
        if self.k_grid is not None:
            object.__setattr__(
                self,
                "k_grid",
                _validate_kpoint_grid(self.k_grid, "CalculationHints.k_grid"),
            )
        _validate_optional_boolean(
            self.spin_polarized, "CalculationHints.spin_polarized"
        )
        _validate_optional_boolean(
            self.spin_orbit_coupling, "CalculationHints.spin_orbit_coupling"
        )
        _validate_optional_boolean(self.use_vdw, "CalculationHints.use_vdw")

        _validate_smearing(
            self.smearing_type,
            self.smearing_width_ry,
            type_field="CalculationHints.smearing_type",
            width_field="CalculationHints.smearing_width_ry",
        )

        if self.conv_thr is not None:
            _validate_finite_positive(self.conv_thr, "CalculationHints.conv_thr")
        if self.mixing_beta is not None:
            _validate_finite_positive(self.mixing_beta, "CalculationHints.mixing_beta")
        if self.electron_maxstep is not None:
            _validate_positive_integer(
                self.electron_maxstep, "CalculationHints.electron_maxstep"
            )
        if self.vdw_method is not None:
            _validate_vdw_method(self.vdw_method, "CalculationHints.vdw_method")
        if self.use_vdw is False and self.vdw_method is not None:
            raise ValueError(
                "CalculationHints.vdw_method must be None when use_vdw is False"
            )
        if self.pseudo_accuracy is not None and self.pseudo_accuracy not in {
            "efficiency",
            "precision",
        }:
            raise ValueError(
                "CalculationHints.pseudo_accuracy must be 'efficiency', "
                f"'precision', or None; got {self.pseudo_accuracy!r}"
            )
        if self.pseudo_type not in {None, "NC", "USPP", "PAW"}:
            raise ValueError(
                "CalculationHints.pseudo_type must be 'NC', 'USPP', 'PAW', "
                f"or None; got {self.pseudo_type!r}"
            )
        _validate_relativistic_mode(
            self.relativistic_mode, "CalculationHints.relativistic_mode"
        )

    @property
    def kmesh(self) -> KmeshHints:
        return KmeshHints(k_grid=self.k_grid, k_spacing=self.k_spacing)

    @property
    def smearing(self) -> SmearingHints:
        return SmearingHints(
            smearing_type=self.smearing_type,
            smearing_width_ry=self.smearing_width_ry,
        )

    @property
    def spin(self) -> SpinHints:
        return SpinHints(
            spin_polarized=self.spin_polarized,
            spin_orbit_coupling=self.spin_orbit_coupling,
        )

    @property
    def pseudo(self) -> PseudoHints:
        return PseudoHints(
            accuracy=self.pseudo_accuracy,
            pseudo_type=self.pseudo_type,
            relativistic_mode=self.relativistic_mode,
        )

    @property
    def convergence(self) -> ConvergenceHints:
        return ConvergenceHints(
            conv_thr=self.conv_thr,
            mixing_beta=self.mixing_beta,
            electron_maxstep=self.electron_maxstep,
        )

    @property
    def vdw(self) -> VdwHints:
        return VdwHints(use_vdw=self.use_vdw, vdw_method=self.vdw_method)

    def to_dict(self) -> JsonDict:
        return to_jsonable(self)
