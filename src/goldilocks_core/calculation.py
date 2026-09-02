from __future__ import annotations

from dataclasses import dataclass

from goldilocks_core.functionals import normalize_functional_label
from goldilocks_core.types import (
    CalcTask,
    CodeName,
    KPointGrid,
    PseudoAccuracy,
    PseudoType,
    RelativisticTreatment,
    SmearingType,
    VdwMethod,
)
from goldilocks_core.validation import (
    validate_finite_positive,
    validate_kpoint_grid,
    validate_optional_boolean,
    validate_positive_integer,
    validate_relativistic_mode,
    validate_smearing,
    validate_vdw_method,
)


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
            validate_finite_positive(self.k_spacing, "CalculationHints.k_spacing")
        if self.k_grid is not None:
            object.__setattr__(
                self,
                "k_grid",
                validate_kpoint_grid(self.k_grid, "CalculationHints.k_grid"),
            )
        validate_optional_boolean(
            self.spin_polarized, "CalculationHints.spin_polarized"
        )
        validate_optional_boolean(
            self.spin_orbit_coupling, "CalculationHints.spin_orbit_coupling"
        )
        validate_optional_boolean(self.use_vdw, "CalculationHints.use_vdw")

        validate_smearing(
            self.smearing_type,
            self.smearing_width_ry,
            type_field="CalculationHints.smearing_type",
            width_field="CalculationHints.smearing_width_ry",
        )

        if self.conv_thr is not None:
            validate_finite_positive(self.conv_thr, "CalculationHints.conv_thr")
        if self.mixing_beta is not None:
            validate_finite_positive(self.mixing_beta, "CalculationHints.mixing_beta")
        if self.electron_maxstep is not None:
            validate_positive_integer(
                self.electron_maxstep, "CalculationHints.electron_maxstep"
            )
        if self.vdw_method is not None:
            validate_vdw_method(self.vdw_method, "CalculationHints.vdw_method")
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
        validate_relativistic_mode(
            self.relativistic_mode, "CalculationHints.relativistic_mode"
        )
