"""Typed contracts for the staged Core recommendation pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Literal

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
"""Where a trained model is loaded from. Only ``local`` is currently supported."""

ModelType = Literal["random_forest", "cgcnn", "xgboost"]
"""ML model architecture. Only ``random_forest`` is currently supported."""

KPointGrid = tuple[int, int, int]
"""Uniform k-point mesh as (nk1, nk2, nk3)."""

KPointShift = tuple[int, int, int]
"""Monkhorst-Pack grid shift as (s1, s2, s3) with values 0 or 1."""

StageName = Literal["load", "analyze", "advise", "select", "generate", "bundle"]
"""Name of a stage in the fixed Core pipeline graph."""

JobMode = Literal["recommend", "generate", "bundle"]
"""How far the fixed Core pipeline runs.

- ``recommend``: Load → Analyze → Advise → Select.
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
        source: where the model is loaded from (e.g. ``local``).
        location: file path or URI for the model artifact.
        revision: optional revision or commit hash.
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
            that maps to this mesh.
        k_line_density_interval: k-line-density range, or None if
            mesh is invalid for a scalar density.
        k_pra: k-points-per-reciprocal-atom for this mesh.
        n_reduced_kpoints: number of symmetry-reduced k-points.
    """

    k_index: int
    mesh: KPointGrid
    k_distance_interval: tuple[float, float]
    k_line_density_interval: tuple[float, float] | None
    k_pra: float
    n_reduced_kpoints: int


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
            non-negative.
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
        dimensionality: structure dimensionality. Currently
            always ``unknown``.
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
    """

    k_points: KPointAdvice
    smearing: SmearingAdvice
    magnetism: MagnetismAdvice
    spin_orbit: SpinOrbitAdvice
    pseudopotentials: PseudopotentialAdvice
    convergence: ConvergenceAdvice

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class KPointSelection:
    """Concrete k-point grid selected from advice.

    Produced by the Select stage from ``KPointAdvice``.

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
    """Complete Select-stage output.

    Contains concrete grids, pseudopotential selections, and any
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

    ``path`` is relative to the bundle root directory.

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


@dataclass(frozen=True, slots=True)
class CoreRecommendation:
    """Structured output from the staged Core pipeline.

    Contains the full provenance chain: intent, analysis, advice,
    selection, and any generated files. ``warnings`` aggregates
    warnings from analysis and selection stages.

    Attributes:
        intent: what the operator asked for.
        analysis: structure facts from the Analyze stage.
        advice: provenance-backed recommendations from the Advise
            stage.
        selection: concrete values from the Select stage.
        generated_files: generated input files, populated by
            Generate or Bundle modes.
        warnings: aggregated warnings from analysis and
            selection.
    """

    intent: CalculationIntent
    analysis: StructureAnalysisRecord
    advice: ParameterAdvice
    selection: SelectionRecord
    generated_files: tuple[GeneratedFile, ...] = ()
    warnings: tuple[str, ...] = ()

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

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class StageRecord:
    """Observable execution record for one fixed Core pipeline stage.

    Used in ``CoreJobResult.stages`` to report which stages ran and
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


@dataclass(frozen=True, slots=True)
class CoreJobResult:
    """Result from running a Core job request through the fixed stage graph.

    Contains the recommendation, stage execution records, and optional
    bundle output. This is the shared result model for Python, CLI, and
    future HTTP wrappers.

    Attributes:
        request: the original job request.
        recommendation: structured recommendation output.
        stages: execution record for each completed stage.
        generated_files: generated input files, populated in
            generate/bundle modes.
        bundle_path: output directory path, set in bundle mode.
        manifest: bundle manifest dictionary, set in bundle mode.
        warnings: aggregated warnings from analysis and
            selection.
    """

    request: CoreJobRequest
    recommendation: CoreRecommendation
    stages: tuple[StageRecord, ...]
    generated_files: tuple[GeneratedFile, ...] = ()
    bundle_path: str | None = None
    manifest: JsonDict | None = None
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


def to_jsonable(value: Any) -> Any:
    """Convert staged pipeline values into JSON-safe Python objects.

    Type conversions:

    - dataclass → dict of field names to converted values
    - tuple, list → list of converted items
    - dict → dict with string keys and converted values
    - Path → str
    - pymatgen Structure → dict (via ``Structure.as_dict()``)
    - numpy ndarray → list
    - numpy scalar → Python scalar
    - None, str, int, float, bool → passed through unchanged
    """
    if is_dataclass(value):
        if not hasattr(value, "__dataclass_fields__"):
            return asdict(value)
        return {
            field.name: to_jsonable(getattr(value, field.name))
            for field in fields(value)
        }

    if isinstance(value, tuple | list):
        return [to_jsonable(item) for item in value]

    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, Structure):
        return value.as_dict()

    if isinstance(value, np.ndarray):
        return value.tolist()

    if isinstance(value, np.generic):
        return value.item()

    return value
