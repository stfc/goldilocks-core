"""Typed contracts for the staged Core recommendation pipeline."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from numbers import Integral, Real
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable, Literal, Sequence

import numpy as np
from pymatgen.core import Structure

from goldilocks_core.pseudo.pp_metadata import PseudoMetadata

ProvenanceSource = Literal[
    "analysis",
    "user_hint",
    "default",
    "model",
    "lookup",
    "fallback",
]
"""Origin of a scientific recommendation or selection.

- ``analysis``: derived from structure facts (e.g. heavy elements → SOC consideration).
- ``user_hint``: explicitly provided by the operator via ``CalculationHints``.
- ``default``: package-level default when no analysis or hint applies.
- ``model``: ML model prediction (e.g. k-index from the CSLR advisor).
- ``lookup``: resolved from supplied metadata (e.g. pseudo selection from a registry).
- ``fallback``: no matching data was available; the value is a placeholder.
"""

JsonDict = dict[str, Any]
"""JSON-serializable dictionary type."""

PathLike = str | Path
"""String or path-like object accepted as a file location."""

StructureInput = Structure | PathLike
"""Structure input: a pymatgen ``Structure`` or a path to a structure file."""

CodeName = Literal["quantum_espresso"]
"""Target DFT code. Only Quantum ESPRESSO is currently supported."""

CalcTask = Literal["scf_single_point"]
"""Calculation task. Only SCF single-point is currently supported."""

AccuracyLevel = Literal["low", "standard", "high"]
"""Desired accuracy/cost tradeoff for the recommendation."""

ModelSource = Literal["huggingface", "local"]
"""Where a trained model or supporting artifact is resolved from."""

ModelType = Literal["random_forest", "cgcnn", "xgboost"]
"""ML model architecture. Only ``random_forest`` is currently supported."""

KPointGrid = tuple[int, int, int]
"""Uniform immutable k-point mesh as (nk1, nk2, nk3)."""

KPointShift = tuple[int, int, int]
"""Immutable Monkhorst-Pack shift as (s1, s2, s3) with values 0 or 1."""

StageName = Literal[
    "load",
    "analyze",
    "advise",
    "kmesh",
    "select",
    "generate",
    "bundle",
]
"""Name of a stage in the fixed Core pipeline graph."""

JobMode = Literal["recommend", "generate", "bundle"]
"""How far the fixed Core pipeline runs.

- ``recommend``: Load → Analyze → Advise → Kmesh → Select.
- ``generate``: … → Generate.
- ``bundle``: … → Bundle.
"""

StageStatus = Literal["completed"]
"""Execution status of a pipeline stage. Currently always ``completed``."""

Dimensionality = Literal["3d", "2d", "1d", "molecule", "unknown"]
"""Structure dimensionality classification. Currently always ``unknown``."""

ElectronicCharacter = Literal["metal", "insulator", "likely_metal", "unknown"]
"""Conservative electronic-character classification from structure facts.

- ``likely_metal``: all elements are metallic; treat as likely, not confirmed.
- ``unknown``: cannot determine from structure alone; verify manually.
"""

VdwMethod = Literal["d3", "d3bj", "ts", "mbd"]
"""Code-agnostic van der Waals dispersion method label.

Translated to code-specific keywords in the Generate stage (e.g. ``d3bj`` →
QE ``vdw_corr='grimme-d3'`` with ``dftd3_version=4``).
"""

_VALID_VDW_METHODS = frozenset({"d3", "d3bj", "ts", "mbd"})


def _validate_finite_positive(value: Real, field_name: str) -> None:
    """Require a finite number greater than zero."""
    if (
        isinstance(value, bool)
        or not isinstance(value, Real)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(
            f"{field_name} must be a finite positive number; got {value!r}"
        )


def _validate_positive_integer(value: int, field_name: str) -> None:
    """Require a positive integer without accepting booleans."""
    if isinstance(value, bool) or not isinstance(value, Integral) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer; got {value!r}")


def _validate_kpoint_grid(grid: object, field_name: str) -> KPointGrid:
    """Return an immutable grid of exactly three positive integer dimensions."""
    if not isinstance(grid, tuple | list) or len(grid) != 3:
        raise ValueError(
            f"{field_name} must contain exactly three positive integers; got {grid!r}"
        )

    for index, value in enumerate(grid):
        _validate_positive_integer(value, f"{field_name}[{index}]")

    return tuple(int(value) for value in grid)


def _validate_kpoint_shift(shift: object, field_name: str) -> KPointShift:
    """Return an immutable sequence of exactly three zero-or-one shift flags."""
    if not isinstance(shift, tuple | list) or len(shift) != 3:
        raise ValueError(
            f"{field_name} must contain exactly three shift flags; got {shift!r}"
        )

    for index, value in enumerate(shift):
        if (
            isinstance(value, bool)
            or not isinstance(value, Integral)
            or value not in {0, 1}
        ):
            raise ValueError(f"{field_name}[{index}] must be 0 or 1; got {value!r}")

    return tuple(int(value) for value in shift)


def _validate_boolean(value: object, field_name: str) -> None:
    """Require a built-in boolean rather than a truthy value."""
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean; got {value!r}")


def _validate_optional_boolean(value: object, field_name: str) -> None:
    """Require None or a built-in boolean."""
    if value is not None:
        _validate_boolean(value, field_name)


def _validate_smearing(
    smearing_type: str | None,
    width: float | None,
    *,
    type_field: str,
    width_field: str,
) -> None:
    """Require fixed occupations without width or smearing with positive width."""
    if smearing_type is not None and (
        not isinstance(smearing_type, str) or not smearing_type.strip()
    ):
        raise ValueError(
            f"{type_field} must be a non-empty string or None; got {smearing_type!r}"
        )

    fixed_occupations = smearing_type in {None, "fixed"}
    if fixed_occupations and width is not None:
        raise ValueError(
            f"{width_field} must be None when {type_field} is {smearing_type!r}"
        )
    if not fixed_occupations and width is None:
        raise ValueError(
            f"{width_field} is required when {type_field} is {smearing_type!r}"
        )
    if width is not None:
        _validate_finite_positive(width, width_field)


def _validate_vdw_method(method: object, field_name: str) -> None:
    """Require a supported code-agnostic vdW method label."""
    if not isinstance(method, str) or method not in _VALID_VDW_METHODS:
        valid = ", ".join(sorted(_VALID_VDW_METHODS))
        raise ValueError(f"{field_name} must be one of {valid}; got {method!r}")


def _validate_generated_path(path: str, field_name: str) -> str:
    """Require a non-empty portable relative path without traversal."""
    if not isinstance(path, str) or not path.strip():
        raise ValueError(f"{field_name} must be a non-empty relative path")

    posix_path = PurePosixPath(path)
    windows_path = PureWindowsPath(path)
    if posix_path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise ValueError(f"{field_name} must be relative; got {path!r}")
    if not posix_path.parts or posix_path == PurePosixPath("."):
        raise ValueError(f"{field_name} must identify a file; got {path!r}")
    if ".." in posix_path.parts or ".." in windows_path.parts:
        raise ValueError(f"{field_name} must not contain '..' traversal; got {path!r}")

    return str(posix_path)


@dataclass(slots=True)
class StructureFeatureVector:
    """Named numerical feature vector extracted from a structure.

    Used by ML advisors for k-index prediction.

    Attributes:
        values: feature values in the same order as ``feature_names``.
        feature_names: human-readable names for each feature dimension.
    """

    values: np.ndarray
    feature_names: list[str]

    def __post_init__(self) -> None:
        """Validate feature shape and numerical values."""
        if not isinstance(self.values, np.ndarray):
            raise ValueError(
                "StructureFeatureVector.values must be a NumPy array; "
                f"got {type(self.values).__name__}"
            )
        if self.values.ndim != 1:
            raise ValueError(
                "StructureFeatureVector.values must be one-dimensional; "
                f"got shape {self.values.shape}"
            )
        if len(self.values) != len(self.feature_names):
            raise ValueError(
                "StructureFeatureVector.values and feature_names must have the "
                f"same length; got {len(self.values)} values and "
                f"{len(self.feature_names)} names"
            )
        if np.iscomplexobj(self.values):
            raise ValueError(
                "StructureFeatureVector.values must contain finite real numbers"
            )
        try:
            values_are_finite = bool(np.isfinite(self.values).all())
        except TypeError as error:
            raise ValueError(
                "StructureFeatureVector.values must contain finite numbers"
            ) from error
        if not values_are_finite:
            raise ValueError(
                "StructureFeatureVector.values must contain only finite numbers"
            )

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(slots=True)
class ModelSpec:
    """Metadata describing a trained model used by the package.

    Attributes:
        name: human-readable model identifier.
        version: model version string.
        model_type: architecture type (e.g. ``random_forest``).
        target: prediction target (e.g. ``k_index``).
        feature_set: feature set name (e.g. ``cslr``).
        source: where the model is loaded from (``local`` or ``huggingface``).
        location: file path or source-specific artifact identifier.
        revision: optional immutable source revision.
    """

    name: str
    version: str
    model_type: ModelType
    target: str
    feature_set: str
    source: ModelSource
    location: str
    revision: str | None = None


@dataclass(frozen=True, slots=True)
class KMeshEntry:
    """One indexed k-mesh entry produced from a structure scan.

    Used by the ML k-mesh advisor to map a predicted k-index to a
    concrete mesh.

    Attributes:
        k_index: 1-based index into the ordered k-mesh table.
        mesh: uniform k-point grid for this entry.
        k_distance_interval: VASP-style k-distance range (Å⁻¹)
            that maps to this mesh. ``None`` as the upper endpoint means
            the interval is unbounded above.
        k_line_density_interval: k-line-density range, or None if
            mesh is invalid for a scalar density.
        k_pra: k-points-per-reciprocal-atom for this mesh.
        n_reduced_kpoints: number of symmetry-reduced k-points.
    """

    k_index: int
    mesh: KPointGrid
    k_distance_interval: tuple[float, float | None]
    k_line_density_interval: tuple[float, float] | None
    k_pra: float
    n_reduced_kpoints: int

    def __post_init__(self) -> None:
        """Validate and normalize the concrete mesh dimensions."""
        object.__setattr__(
            self,
            "mesh",
            _validate_kpoint_grid(self.mesh, "KMeshEntry.mesh"),
        )


@dataclass(frozen=True, slots=True)
class Provenance:
    """Reason and source for a scientific recommendation or selection.

    Every advice and selection record carries provenance so callers can
    understand why a value was chosen and whether to trust or override it.

    Attributes:
        source: why this value was chosen. One of ``analysis``,
            ``user_hint``, ``default``, ``model``, ``lookup``, or
            ``fallback``.
        reason: human-readable explanation of the choice.
        data_source: origin of supporting data (e.g. model name,
            pseudo library, SSSP version).
        confidence: optional confidence score in [0, 1]. Not
            currently populated by Core.
        warnings: caveats the caller should be aware of.
    """

    source: ProvenanceSource
    reason: str
    data_source: str | None = None
    confidence: float | None = None
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate the optional confidence score."""
        if self.confidence is not None and (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, Real)
            or not math.isfinite(self.confidence)
            or not 0 <= self.confidence <= 1
        ):
            raise ValueError(
                "Provenance.confidence must be a finite number in [0, 1]; "
                f"got {self.confidence!r}"
            )

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class CalculationIntent:
    """Operator intent for a Core recommendation.

    Expresses what the operator wants to calculate, not how to
    calculate it. Core uses intent to steer advice and generation.

    Attributes:
        code: target DFT code for input generation.
        task: type of calculation to prepare.
        functional: exchange-correlation functional label
            (e.g. ``PBE``, ``PBEsol``, ``LDA``).
        accuracy_level: desired accuracy/cost tradeoff.
        pseudo_mode: pseudopotential family preference
            (e.g. ``efficiency``, ``precision``).
    """

    code: CodeName = "quantum_espresso"
    task: CalcTask = "scf_single_point"
    functional: str = "PBE"
    accuracy_level: AccuracyLevel = "standard"
    pseudo_mode: str = "efficiency"

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class CalculationHints:
    """Optional operator overrides for values Core can otherwise decide.

    All fields default to ``None``. A ``None`` value means "let Core
    decide." A non-None value overrides the Core default and records
    ``user_hint`` provenance. Partial overrides are supported: e.g.
    setting ``conv_thr`` without setting ``mixing_beta``.

    Attributes:
        k_spacing: VASP-style k-point spacing in Å⁻¹. Ignored
            when ``k_grid`` is also set.
        k_grid: explicit uniform k-point grid. Takes precedence
            over ``k_spacing``.
        smearing_type: smearing method (e.g. ``cold``,
            ``gaussian``, ``mp``, ``fixed``).
        smearing_width_ry: smearing width in Rydberg. Must be
            finite and positive when smearing is enabled.
        spin_polarized: force spin-polarized (``True``) or
            non-magnetic (``False``) calculation.
        spin_orbit_coupling: force SOC on (``True``) or off
            (``False``).
        pseudo_mode: override pseudo family preference (e.g.
            ``efficiency``, ``precision``).
        pseudo_type: override pseudo type (e.g. ``NC``,
            ``USPP``, ``PAW``).
        relativistic_mode: override relativistic treatment
            (``scalar``, ``full``, ``non-relativistic``).
        conv_thr: SCF convergence threshold in Rydberg. Must be
            positive.
        mixing_beta: charge-density mixing beta. Must be
            positive.
        electron_maxstep: maximum number of SCF iterations. Must
            be ≥ 1.
    """

    k_spacing: float | None = None
    k_grid: KPointGrid | None = None
    smearing_type: str | None = None
    smearing_width_ry: float | None = None
    spin_polarized: bool | None = None
    spin_orbit_coupling: bool | None = None
    pseudo_mode: str | None = None
    pseudo_type: str | None = None
    relativistic_mode: str | None = None
    conv_thr: float | None = None
    mixing_beta: float | None = None
    electron_maxstep: int | None = None
    use_vdw: bool | None = None
    vdw_method: str | None = None

    def __post_init__(self) -> None:
        """Validate numerical and coupled hint fields at the request boundary."""
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

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class StructureAnalysisRecord:
    """Facts reported by the Analyze stage without parameter decisions.

    Analysis is read-only: it reports what the structure *is*, not what
    parameters to use. Later stages consume these facts to make
    provenance-backed decisions.

    Attributes:
        formula: full chemical formula (e.g. ``Fe2O31``).
        reduced_formula: reduced formula (e.g. ``Fe2O3``).
        site_count: number of sites in the structure.
        elements: sorted unique element symbols.
        contains_transition_metals: True if any element is a
            transition metal (pymatgen classification).
        contains_lanthanides: True if any element is a lanthanide.
        contains_actinides: True if any element is an actinide.
        contains_heavy_elements: True if any element has
            period ≥ 5 (row ≥ 5 in pymatgen).
        magnetic_elements: elements that are transition metals,
            lanthanides, or actinides — magnetic candidates.
        heavy_elements: elements with period ≥ 5, relevant for
            SOC consideration.
        disorder_warnings: per-site warnings for partial
            occupancies.
        disordered_site_count: number of sites with partial
            occupancies.
        space_group_symbol: Hermann-Mauguin symbol, or None for
            disordered structures.
        space_group_number: International space group number
            (1–230), or None.
        crystal_system: crystal system name (e.g. ``cubic``), or
            None.
        dimensionality: structure dimensionality from a bonded-cluster
            analysis (``3d``, ``2d``, ``1d``, ``molecule``), or
            ``unknown`` when detection fails.
        has_vacuum: whether the cell has vacuum in at least one
            direction (dimensionality below 3D).
        electronic_character: conservative electronic-character
            heuristic.
        analysis_warnings: warnings about heuristic limitations
            (e.g. metallicity uncertainty).
    """

    formula: str
    reduced_formula: str
    site_count: int
    elements: tuple[str, ...]
    contains_transition_metals: bool
    contains_lanthanides: bool
    contains_actinides: bool
    contains_heavy_elements: bool
    magnetic_elements: tuple[str, ...]
    heavy_elements: tuple[str, ...]
    disorder_warnings: tuple[str, ...] = ()
    disordered_site_count: int = 0
    space_group_symbol: str | None = None
    space_group_number: int | None = None
    crystal_system: str | None = None
    dimensionality: Dimensionality = "unknown"
    has_vacuum: bool = False
    electronic_character: ElectronicCharacter = "unknown"
    analysis_warnings: tuple[str, ...] = ()

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class KPointAdvice:
    """Advised reciprocal-space sampling intent.

    Exactly one of ``spacing`` or ``explicit_grid`` is set.

    Attributes:
        spacing: VASP-style k-point spacing in Å⁻¹, or None
            when explicit grid is used.
        explicit_grid: explicit k-point grid, or None when
            spacing is used.
        mesh_type: mesh type label (e.g. ``monkhorst-pack``).
        provenance: why this advice was chosen.
    """

    spacing: float | None
    explicit_grid: KPointGrid | None
    mesh_type: str
    provenance: Provenance

    def __post_init__(self) -> None:
        """Enforce exactly one of spacing or explicit_grid."""
        has_spacing = self.spacing is not None
        has_grid = self.explicit_grid is not None
        if has_spacing == has_grid:
            raise ValueError(
                "KPointAdvice must have exactly one of spacing or an explicit grid set"
            )
        if self.spacing is not None:
            _validate_finite_positive(self.spacing, "KPointAdvice.spacing")
        if self.explicit_grid is not None:
            object.__setattr__(
                self,
                "explicit_grid",
                _validate_kpoint_grid(
                    self.explicit_grid,
                    "KPointAdvice.explicit_grid",
                ),
            )

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


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

    def __post_init__(self) -> None:
        """Validate the occupation type and width combination."""
        _validate_smearing(
            self.smearing_type,
            self.width_ry,
            type_field="SmearingAdvice.smearing_type",
            width_field="SmearingAdvice.width_ry",
        )

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

    def __post_init__(self) -> None:
        """Require an explicit spin-polarization control value."""
        _validate_boolean(self.spin_polarized, "MagnetismAdvice.spin_polarized")

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

    def __post_init__(self) -> None:
        """Require explicit SOC control and consideration values."""
        _validate_boolean(self.enabled, "SpinOrbitAdvice.enabled")
        _validate_boolean(self.consider, "SpinOrbitAdvice.consider")

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class PseudopotentialAdvice:
    """Advised pseudopotential family and treatment intent.

    Select uses this to filter and rank pseudopotential candidates.

    Attributes:
        functional: exchange-correlation functional the pseudos
            should target (e.g. ``PBE``).
        pseudo_mode: pseudo family preference (e.g.
            ``efficiency``, ``precision``).
        pseudo_type: pseudo type filter (e.g. ``NC``, ``USPP``,
            ``PAW``), or None to accept any.
        relativistic_mode: relativistic treatment: ``scalar``,
            ``full``, or ``non-relativistic``.
        provenance: why this advice was chosen.
    """

    functional: str
    pseudo_mode: str
    pseudo_type: str | None
    relativistic_mode: str
    provenance: Provenance

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

    def __post_init__(self) -> None:
        """Validate finite positive convergence controls."""
        _validate_finite_positive(self.conv_thr, "ConvergenceAdvice.conv_thr")
        _validate_finite_positive(self.mixing_beta, "ConvergenceAdvice.mixing_beta")
        _validate_positive_integer(
            self.electron_maxstep, "ConvergenceAdvice.electron_maxstep"
        )

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class VdwAdvice:
    """Advised van der Waals dispersion correction.

    Method labels are code-agnostic physics names; the generator maps them
    to code-specific strings (e.g. ``d3bj`` → QE ``grimme-d3bj``).

    Attributes:
        use_vdw: whether a dispersion correction is applied.
        method: dispersion method (``d3``, ``d3bj``, ``ts``, ``mbd``), or
            None when ``use_vdw`` is False.
        provenance: why this advice was chosen.
    """

    use_vdw: bool
    method: VdwMethod | None
    provenance: Provenance

    def __post_init__(self) -> None:
        """Validate that enabled vdW advice has exactly one supported method."""
        _validate_boolean(self.use_vdw, "VdwAdvice.use_vdw")
        if self.use_vdw and self.method is None:
            raise ValueError("VdwAdvice.method is required when use_vdw is True")
        if not self.use_vdw and self.method is not None:
            raise ValueError("VdwAdvice.method must be None when use_vdw is False")
        if self.method is not None:
            _validate_vdw_method(self.method, "VdwAdvice.method")

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class ParameterAdvice:
    """Complete Advise-stage output.

    Contains one advice record per recommendation category. Each record
    carries its own ``Provenance`` explaining why that value was chosen.

    Attributes:
        k_points: reciprocal-space sampling intent.
        smearing: occupation smearing settings.
        magnetism: spin-polarization setting.
        spin_orbit: SOC relevance and setting.
        pseudopotentials: pseudo family and treatment intent.
        convergence: SCF convergence parameters.
        vdw: VdwAdvice.
    """

    k_points: KPointAdvice
    smearing: SmearingAdvice
    magnetism: MagnetismAdvice
    spin_orbit: SpinOrbitAdvice
    pseudopotentials: PseudopotentialAdvice
    convergence: ConvergenceAdvice
    vdw: VdwAdvice

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class KPointSelection:
    """Concrete k-point grid selected from advice or a model.

    Produced by the Kmesh stage from ``KPointAdvice`` and optional
    operator hints.

    Attributes:
        grid: uniform k-point grid (nk1, nk2, nk3).
        shift: Monkhorst-Pack shift (s1, s2, s3), currently
            always (0, 0, 0).
        mesh_type: mesh type label (e.g. ``monkhorst-pack``).
        provenance: how this grid was derived from advice.
    """

    grid: KPointGrid
    shift: KPointShift
    mesh_type: str
    provenance: Provenance

    def __post_init__(self) -> None:
        """Validate and normalize the concrete grid and target shift flags."""
        object.__setattr__(
            self,
            "grid",
            _validate_kpoint_grid(self.grid, "KPointSelection.grid"),
        )
        object.__setattr__(
            self,
            "shift",
            _validate_kpoint_shift(self.shift, "KPointSelection.shift"),
        )

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class PseudopotentialSelection:
    """Concrete pseudopotential selected for one element.

    ``filename`` is None when no matching pseudopotential was found.
    Cutoff values are in Rydberg and come from SSSP recommended cutoffs.

    Attributes:
        element: element symbol this selection is for.
        filename: pseudopotential filename, or None if no match
            was found.
        filepath: full path to the pseudopotential file, or None.
        ecutwfc_ry: wavefunction cutoff in Rydberg, or None if
            unavailable.
        ecutrho_ry: charge-density cutoff in Rydberg, or None if
            unavailable.
        provenance: how this selection was resolved.
        warnings: warnings about missing or incomplete data.
    """

    element: str
    filename: str | None
    filepath: str | None
    ecutwfc_ry: float | None
    ecutrho_ry: float | None
    provenance: Provenance
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate any available pseudopotential cutoff values."""
        if self.ecutwfc_ry is not None:
            _validate_finite_positive(
                self.ecutwfc_ry, "PseudopotentialSelection.ecutwfc_ry"
            )
        if self.ecutrho_ry is not None:
            _validate_finite_positive(
                self.ecutrho_ry, "PseudopotentialSelection.ecutrho_ry"
            )

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class SelectionRecord:
    """Complete Select-stage output.

    Contains the Kmesh-stage grid, pseudopotential selections, and any
    accumulated warnings from the selection process.

    Attributes:
        k_points: resolved k-point grid and shift.
        pseudopotentials: one selection per element.
        warnings: warnings from pseudo selection (e.g. missing
            pseudos, incomplete cutoffs).
    """

    k_points: KPointSelection
    pseudopotentials: tuple[PseudopotentialSelection, ...]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class GeneratedFile:
    """Generated text file content for a target DFT code.

    ``path`` is non-empty, relative to the bundle root directory, and cannot
    contain ``..`` traversal components.

    Attributes:
        path: relative file path within the bundle (e.g.
            ``inputs/qe.in``).
        content: full text content of the generated file.
        role: file role (e.g. ``input``, ``output``). Currently
            always ``input``.
    """

    path: str
    content: str
    role: str = "input"

    def __post_init__(self) -> None:
        """Validate the bundle-relative generated path."""
        _validate_generated_path(self.path, "GeneratedFile.path")

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class BundleRecord:
    """Terminal Bundle-stage output: where files were written and the manifest.

    This is a stage record like every other: one stage produces one record.
    It is only populated in bundle mode.

    Attributes:
        path: bundle root directory path.
        manifest: bundle manifest dictionary.
    """

    path: str
    manifest: JsonDict

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class CoreResult:
    """Composed accumulator of every stage record the fixed graph produces.

    Scientific records are populated as their stages run. ``generated_files``
    is populated in generate/bundle modes. ``bundle`` is set only in bundle
    mode. ``stages`` is the execution trace, always populated. The request is
    not echoed here — the caller already has it; CLI/HTTP layers echo it
    themselves in their serialized output.

    Attributes:
        intent: what the operator asked for.
        analysis: structure facts from the Analyze stage.
        advice: provenance-backed recommendations from the Advise
            stage.
        selection: concrete values from the Select stage.
        generated_files: generated input files, populated by
            Generate or Bundle modes.
        warnings: aggregated warnings from analysis, Kmesh, and
            selection.
        bundle: terminal Bundle-stage record, set only in bundle
            mode.
        stages: execution record for each completed stage.
    """

    intent: CalculationIntent
    analysis: StructureAnalysisRecord
    advice: ParameterAdvice
    selection: SelectionRecord
    generated_files: tuple[GeneratedFile, ...] = ()
    warnings: tuple[str, ...] = ()
    bundle: BundleRecord | None = None
    stages: tuple[StageRecord, ...] = ()

    def __post_init__(self) -> None:
        """Reject duplicate generated paths at their containing boundary."""
        seen_paths: set[str] = set()
        for generated_file in self.generated_files:
            normalized_path = _validate_generated_path(
                generated_file.path, "CoreResult.generated_files[].path"
            )
            if normalized_path in seen_paths:
                raise ValueError(
                    "CoreResult.generated_files contains duplicate path "
                    f"{generated_file.path!r}"
                )
            seen_paths.add(normalized_path)

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class CoreJobRequest:
    """Request for running the fixed Core stage graph.

    One request model shared by Python API, CLI, and future HTTP
    wrappers. ``mode`` controls how far the pipeline runs.

    Attributes:
        structure: structure input — a pymatgen Structure or a
            path to a structure file.
        intent: what to calculate.
        hints: optional operator overrides.
        mode: pipeline mode: ``recommend``, ``generate``, or
            ``bundle``.
        pseudo_metadata: pseudopotential metadata for selection.
        output_dir: output directory path, required when mode is
            ``bundle``.
    """

    structure: StructureInput
    intent: CalculationIntent = field(default_factory=CalculationIntent)
    hints: CalculationHints = field(default_factory=CalculationHints)
    mode: JobMode = "recommend"
    pseudo_metadata: tuple[PseudoMetadata, ...] = ()
    output_dir: str | None = None

    def __post_init__(self) -> None:
        """Validate request invariants at construction."""
        if self.mode not in {"recommend", "generate", "bundle"}:
            raise ValueError(f"Unsupported Core job mode: {self.mode}")

        if self.mode == "bundle" and self.output_dir is None:
            raise ValueError("output_dir is required for bundle mode")

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class StageRecord:
    """Observable execution record for one fixed Core pipeline stage.

    Used in ``CoreResult.stages`` to report which stages ran and
    what warnings they produced.

    Attributes:
        name: which stage this record is for.
        status: execution status. Currently always ``completed``.
        warnings: warnings produced during this stage.
    """

    name: StageName
    status: StageStatus = "completed"
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


AnalyzeStage = Callable[[Structure], StructureAnalysisRecord]
"""Analyze-stage backend signature."""

AdviseStage = Callable[
    [StructureAnalysisRecord, CalculationIntent, CalculationHints],
    ParameterAdvice,
]
"""Advise-stage backend signature."""

KMeshAdvisor = Callable[[Structure, CalculationHints, KPointAdvice], KPointSelection]
"""Kmesh-stage backend signature."""

SelectStage = Callable[
    [Structure, ParameterAdvice, KPointSelection, Sequence[PseudoMetadata]],
    SelectionRecord,
]
"""Select-stage backend signature."""

GenerateStage = Callable[
    [Structure, CalculationIntent, ParameterAdvice, SelectionRecord],
    tuple[GeneratedFile, ...],
]
"""Generate-stage backend signature."""

BundleStage = Callable[[CoreResult, str | Path], BundleRecord]
"""Bundle-stage backend signature."""


def _numpy_scalar_to_python(value: np.generic) -> Any:
    """Convert NumPy scalars, including extended precision values."""
    converted = value.item()
    if not isinstance(converted, np.generic):
        return converted
    if np.issubdtype(value.dtype, np.bool_):
        return bool(value)
    if np.issubdtype(value.dtype, np.integer):
        return int(value)
    if np.issubdtype(value.dtype, np.floating):
        return float(value)
    raise TypeError(f"Unsupported NumPy scalar for JSON serialization: {value.dtype}")


def to_jsonable(value: Any) -> Any:
    """Convert supported pipeline values into JSON-safe Python objects.

    Raises:
        TypeError: If a value or dictionary key has no supported JSON mapping.
        ValueError: If a floating-point value is NaN or infinite.
    """
    if isinstance(value, Enum):
        return to_jsonable(value.value)

    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: to_jsonable(getattr(value, field.name))
            for field in fields(value)
        }

    if isinstance(value, tuple | list):
        return [to_jsonable(item) for item in value]

    if isinstance(value, dict):
        converted: dict[str, Any] = {}
        for key, item in value.items():
            json_key = _to_json_key(key)
            if json_key in converted:
                raise ValueError(
                    f"JSON dictionary keys stringify to the same key: {json_key!r}"
                )
            converted[json_key] = to_jsonable(item)
        return converted

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, Structure):
        return to_jsonable(value.as_dict())

    if isinstance(value, np.ndarray):
        return to_jsonable(value.tolist())

    if isinstance(value, np.generic):
        return to_jsonable(_numpy_scalar_to_python(value))

    if value is None or isinstance(value, str | bool | int):
        return value

    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"JSON numbers must be finite; got {value!r}")
        return value

    raise TypeError(f"Unsupported value for JSON serialization: {type(value).__name__}")


def _to_json_key(value: Any) -> str:
    """Return a string key for supported JSON scalar key values."""
    if isinstance(value, Enum):
        return _to_json_key(value.value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return _to_json_key(_numpy_scalar_to_python(value))
    if value is None or isinstance(value, str | bool | int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"JSON dictionary keys must be finite; got {value!r}")
        return str(value)
    raise TypeError(
        f"Unsupported dictionary key for JSON serialization: {type(value).__name__}"
    )
