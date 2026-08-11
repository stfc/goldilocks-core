"""Dataclass records for the staged Core recommendation pipeline."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from pymatgen.core import Structure

from goldilocks_core.contracts.serial import to_jsonable
from goldilocks_core.contracts.types import (
    CalcTask,
    CodeName,
    Dimensionality,
    ElectronicCharacter,
    JobMode,
    JsonDict,
    KPointGrid,
    KPointShift,
    ModelSource,
    ModelType,
    ProvenanceSource,
    StructureInput,
    VdwMethod,
)
from goldilocks_core.contracts.validate import (
    _validate_finite_positive,
    _validate_kpoint_grid,
    _validate_optional_boolean,
    _validate_optional_nonempty_str,
    _validate_positive_integer,
    _validate_relativistic_mode,
    _validate_smearing,
    _validate_vdw_method,
)
from goldilocks_core.functionals import normalize_functional_label


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

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class KMeshEntry:
    """One indexed k-mesh entry produced from a structure scan.

    Used by the ML k-mesh advisor to map a predicted k-index to a
    concrete mesh.

    Attributes:
        k_index: 1-based index into the ordered k-mesh table.
        mesh: uniform k-point grid for this entry.
    """

    k_index: int
    mesh: KPointGrid


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
        confidence: optional confidence score in [0, 1].
        details: optional structured, JSON-safe decision metadata. Model-backed
            decisions use this for reproducible inference configuration.
        warnings: caveats the caller should be aware of.
    """

    source: ProvenanceSource
    reason: str
    data_source: str | None = None
    confidence: float | None = None
    details: JsonDict | None = None
    warnings: tuple[str, ...] = ()

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
        pseudo_mode: pseudopotential family preference
            (e.g. ``efficiency``, ``precision``).
    """

    code: CodeName = "quantum_espresso"
    task: CalcTask = "scf_single_point"
    functional: str = "PBEsol"
    pseudo_mode: str = "efficiency"

    def __post_init__(self) -> None:
        """Require named targets and normalize the functional."""
        for field_name in ("code", "task", "pseudo_mode"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"CalculationIntent.{field_name} must be a non-empty string; "
                    f"got {value!r}"
                )

        functional = normalize_functional_label(self.functional)
        if functional is None:
            raise ValueError(
                "CalculationIntent.functional must be a non-empty string; "
                f"got {self.functional!r}"
            )
        object.__setattr__(self, "functional", functional)

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class KmeshHints:
    """Kmesh-stage operator overrides for k-point selection.

    A narrow view over a ``CalculationHints`` slice, owned by the Kmesh stage.
    Constructed from a validated ``CalculationHints``; not validated itself
    (trusted internal record).
    """

    k_grid: KPointGrid | None = None
    k_spacing: float | None = None


@dataclass(frozen=True, slots=True)
class SmearingHints:
    """Smearing-stage operator overrides."""

    smearing_type: str | None = None
    smearing_width_ry: float | None = None


@dataclass(frozen=True, slots=True)
class SpinHints:
    """Spin-stage operator overrides shared by magnetism and SOC advice."""

    spin_polarized: bool | None = None
    spin_orbit_coupling: bool | None = None


@dataclass(frozen=True, slots=True)
class PseudoHints:
    """Pseudopotential-stage operator overrides."""

    pseudo_mode: str | None = None
    pseudo_type: str | None = None
    relativistic_mode: str | None = None


@dataclass(frozen=True, slots=True)
class ConvergenceHints:
    """Convergence-stage operator overrides."""

    conv_thr: float | None = None
    mixing_beta: float | None = None
    electron_maxstep: int | None = None


@dataclass(frozen=True, slots=True)
class VdwHints:
    """Van der Waals-stage operator overrides."""

    use_vdw: bool | None = None
    vdw_method: str | None = None


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
        use_vdw: force dispersion correction on (``True``), force it off
            (``False``), or let Core decide (``None``).
        vdw_method: preferred dispersion method. Valid without ``use_vdw``
            so analysis can decide whether to apply it, but incompatible with
            ``use_vdw=False``.
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
        if self.use_vdw is False and self.vdw_method is not None:
            raise ValueError(
                "CalculationHints.vdw_method must be None when use_vdw is False"
            )
        _validate_optional_nonempty_str(
            self.pseudo_mode, "CalculationHints.pseudo_mode"
        )
        _validate_optional_nonempty_str(
            self.pseudo_type, "CalculationHints.pseudo_type"
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
            pseudo_mode=self.pseudo_mode,
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
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class SymmetryUnavailable:
    """Typed marker that symmetry facts could not be determined.

    Stored in ``StructureAnalysisRecord`` symmetry fields when spglib cannot
    analyze a structure (e.g. disordered sites). Carries a ``reason`` so the
    manifest records why the field is unavailable instead of a bare null.
    Symmetry is reporting-only; a recommendation stays complete with one of
    these in place of a crystal-system/space-group value.

    Attributes:
        reason: why symmetry analysis was unavailable.
    """

    reason: str


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
        space_group_symbol: Hermann-Mauguin symbol, or
            ``SymmetryUnavailable`` when spglib cannot analyze, or None.
        space_group_number: International space group number
            (1–230), or ``SymmetryUnavailable``, or None.
        crystal_system: crystal system name (e.g. ``cubic``), or
            ``SymmetryUnavailable``, or None.
        dimensionality: structure dimensionality from a bonded-cluster
            analysis (``3d``, ``2d``, ``1d``, ``molecule``), or
            ``unknown`` when detection fails.
        low_dimensional: connectivity-derived low-dimensional heuristic:
            True when bonded dimensionality is below 3D. This is not a
            measured cell-vacuum quantity.
        electronic_character: electronic-character classification from the
            runtime model or structure-only fallback.
        electronic_character_source: origin of the classification, such as
            ``model`` or ``heuristic``.
        electronic_character_confidence: optional confidence score in [0, 1].
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
    space_group_symbol: str | int | SymmetryUnavailable | None = None
    space_group_number: str | int | SymmetryUnavailable | None = None
    crystal_system: str | int | SymmetryUnavailable | None = None
    dimensionality: Dimensionality = "unknown"
    low_dimensional: bool = False
    electronic_character: ElectronicCharacter = "unknown"
    electronic_character_source: str = "heuristic"
    electronic_character_confidence: float | None = None
    analysis_warnings: tuple[str, ...] = ()

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

    def __post_init__(self) -> None:
        """Normalize the functional at the advice-record boundary."""
        functional = normalize_functional_label(self.functional)
        if functional is None:
            raise ValueError(
                "PseudopotentialAdvice.functional must be a non-empty string; "
                f"got {self.functional!r}"
            )
        object.__setattr__(self, "functional", functional)

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

    Contains one advice record per recommendation category. Each record
    carries its own ``Provenance`` explaining why that value was chosen.

    Attributes:
        smearing: occupation smearing settings.
        magnetism: spin-polarization setting.
        spin_orbit: SOC relevance and setting.
        pseudopotentials: pseudo family and treatment intent.
        convergence: SCF convergence parameters.
        vdw: VdwAdvice.
    """

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
    """Concrete k-point grid selected from hints or a model.

    Produced by the Kmesh stage from operator k-point hints or, when no
    hint is set, a model backend.

    Attributes:
        grid: uniform k-point grid (nk1, nk2, nk3).
        shift: Monkhorst-Pack shift (s1, s2, s3), currently
            always (0, 0, 0).
        mesh_type: mesh type label (e.g. ``monkhorst-pack``).
        provenance: how this grid was derived.
    """

    grid: KPointGrid
    shift: KPointShift
    mesh_type: str
    provenance: Provenance

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

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class SelectionRecord:
    """Complete Select-stage pseudopotential output.

    Attributes:
        pseudopotentials: one selection per element.
        warnings: warnings from pseudo selection (e.g. missing
            pseudos, incomplete cutoffs).
    """

    pseudopotentials: tuple[PseudopotentialSelection, ...]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class GeneratedFile:
    """Generated text file content for a target DFT code.

    Bundle writers interpret ``path`` relative to their output directory and
    must reject paths that escape it.

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

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


type GeneratedFiles = tuple[GeneratedFile, ...]
"""Immutable collection produced by the Generate stage."""


RECORD_TYPE_IDS: dict[type, str] = {
    Structure: "structure",
    StructureAnalysisRecord: "analysis",
    ParameterAdvice: "advice",
    KPointSelection: "k_points",
    SelectionRecord: "selection",
    GeneratedFiles: "generated_files",
}
"""Authoritative stable transport id for each graph record type.

These ids are backend-owned and never derived from Python class names, so the
wire format survives renames and never leaks implementation types. They are
used consistently for task descriptions, selectable query outputs, query
resolution, and record-set serialization.
"""


def record_type_id(record_type: type) -> str:
    """Return the stable transport id for a graph record type."""
    try:
        return RECORD_TYPE_IDS[record_type]
    except KeyError as error:
        raise ValueError(
            f"No stable transport record id for record type {record_type.__name__}"
        ) from error


@dataclass(frozen=True, slots=True)
class BundleRecord:
    """Bundle publication output: where files were written and the manifest.

    It is populated when generate publishes files to an output directory.

    Attributes:
        path: bundle root directory path.
        manifest: bundle manifest dictionary.
    """

    path: str
    manifest: JsonDict

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


class CoreRecords(Mapping[type, Any]):
    """Requested DAG records keyed by their record types.

    Only explicitly requested record types are present.
    """

    __slots__ = ("_records",)

    def __init__(self, records: Mapping[type, Any] | None = None) -> None:
        self._records = dict(records or {})

    def __getitem__(self, record_type: type) -> Any:
        return self._records[record_type]

    def __iter__(self) -> Iterator[type]:
        return iter(self._records)

    def __len__(self) -> int:
        return len(self._records)

    def to_dict(self) -> JsonDict:
        """Return records as a JSON-serializable dictionary keyed by stable ids."""
        return to_jsonable(
            {
                record_type_id(record_type): record
                for record_type, record in self._records.items()
            }
        )


@dataclass(frozen=True, slots=True)
class CoreResult:
    """Records produced by a recommendation or generation workflow.

    Scientific records are populated as their stages run. ``k_points`` is the
    Kmesh-stage output alongside the Select-stage pseudopotentials.
    ``generated_files`` is populated in generate mode. ``bundle`` is set only
    when generate is given an output directory. The request is not echoed here
    — the caller already has it; CLI/HTTP layers echo it themselves.

    Attributes:
        intent: what the operator asked for.
        analysis: structure facts from the Analyze stage.
        advice: provenance-backed recommendations from the Advise
            stage.
        k_points: concrete grid and shift from the Kmesh stage.
        selection: concrete pseudopotentials from the Select stage.
        generated_files: generated input files, populated by Generate mode.
        warnings: aggregated warnings from analysis, Kmesh, and
            selection.
        bundle: output bundle record, set only when generate writes files.
    """

    intent: CalculationIntent
    analysis: StructureAnalysisRecord
    advice: ParameterAdvice
    k_points: KPointSelection
    selection: SelectionRecord
    generated_files: GeneratedFiles = ()
    warnings: tuple[str, ...] = ()
    bundle: BundleRecord | None = None

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class PresetRequest:
    """Operator request for a named-preset Core run (recommend/generate).

    Passed to :func:`run_core_job` (or a dispatcher's ``recommend``/``generate``).
    ``mode`` selects the preset; ``output_dir`` is meaningful only with
    ``generate``.

    Attributes:
        structure: structure input — a pymatgen Structure or a path to a
            structure file.
        intent: what to calculate.
        hints: optional operator overrides.
        mode: preset mode: ``recommend`` or ``generate``.
        pseudo_metadata: pseudopotential metadata for selection.
        output_dir: optional output directory, meaningful only with
            ``generate``. The generate entrypoint handles publishing there.
        kmesh_model: optional local k-index model spec; when set, the SCF path
            uses it for k-point selection instead of the default QRF model.
    """

    structure: StructureInput
    intent: CalculationIntent = field(default_factory=CalculationIntent)
    hints: CalculationHints = field(default_factory=CalculationHints)
    mode: JobMode = "recommend"
    pseudo_metadata: tuple[PseudoMetadata, ...] = ()
    output_dir: str | None = None
    kmesh_model: ModelSpec | None = None

    def __post_init__(self) -> None:
        """Validate the preset mode at construction."""
        if self.mode not in {"recommend", "generate"}:
            raise ValueError(f"Unsupported Core job mode: {self.mode}")

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return {
            "structure": to_jsonable(self.structure),
            "intent": to_jsonable(self.intent),
            "hints": to_jsonable(self.hints),
            "mode": self.mode,
            "pseudo_metadata": to_jsonable(self.pseudo_metadata),
            "output_dir": self.output_dir,
            "kmesh_model": to_jsonable(self.kmesh_model),
        }


@dataclass(frozen=True, slots=True)
class QueryRequest:
    """Operator request for an explicit record query.

    Passed to :func:`query_records` (or a dispatcher's ``compute``). ``outputs``
    is required: it names the DAG record types to compute.

    Attributes:
        structure: structure input — a pymatgen Structure or a path to a
            structure file.
        outputs: requested DAG record types (required, non-None).
        intent: what to calculate.
        hints: optional operator overrides.
        pseudo_metadata: pseudopotential metadata for selection.
        kmesh_model: optional local k-index model spec.
    """

    structure: StructureInput
    outputs: tuple[type, ...]
    intent: CalculationIntent = field(default_factory=CalculationIntent)
    hints: CalculationHints = field(default_factory=CalculationHints)
    pseudo_metadata: tuple[PseudoMetadata, ...] = ()
    kmesh_model: ModelSpec | None = None

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary with stable record ids."""
        return {
            "structure": to_jsonable(self.structure),
            "outputs": [record_type_id(output_type) for output_type in self.outputs],
            "intent": to_jsonable(self.intent),
            "hints": to_jsonable(self.hints),
            "pseudo_metadata": to_jsonable(self.pseudo_metadata),
            "kmesh_model": to_jsonable(self.kmesh_model),
        }
