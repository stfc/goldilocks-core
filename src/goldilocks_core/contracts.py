"""Typed contracts for the staged Core recommendation pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields, is_dataclass
from pathlib import Path
from typing import Any, Literal

from goldilocks_core.shared.types import AccuracyLevel, CalcTask, CodeName

ProvenanceSource = Literal[
    "analysis",
    "user_hint",
    "default",
    "model",
    "lookup",
    "fallback",
]


JsonDict = dict[str, Any]
KPointGrid = tuple[int, int, int]
KPointShift = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class Provenance:
    """Reason and source for a scientific recommendation or selection."""

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
    """Operator intent for a Core recommendation."""

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
    """Optional operator overrides for values Core can otherwise decide."""

    k_spacing: float | None = None
    k_grid: KPointGrid | None = None
    smearing_type: str | None = None
    smearing_width_ry: float | None = None
    spin_polarized: bool | None = None
    spin_orbit_coupling: bool | None = None
    pseudo_mode: str | None = None
    pseudo_type: str | None = None
    relativistic_mode: str | None = None

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class StructureAnalysisRecord:
    """Facts reported by the Analyse stage without parameter decisions."""

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

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class KPointAdviceRecord:
    """Advised reciprocal-space sampling intent."""

    spacing: float | None
    explicit_grid: KPointGrid | None
    mesh_type: str
    provenance: Provenance

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class SmearingAdvice:
    """Advised occupation smearing settings."""

    smearing_type: str | None
    width_ry: float | None
    provenance: Provenance

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class MagnetismAdvice:
    """Advised spin-polarization setting."""

    spin_polarized: bool
    magnetic_elements: tuple[str, ...]
    provenance: Provenance

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class SpinOrbitAdvice:
    """Advised spin-orbit setting and SOC relevance facts."""

    enabled: bool
    consider: bool
    heavy_elements: tuple[str, ...]
    provenance: Provenance

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class PseudopotentialAdvice:
    """Advised pseudopotential family and treatment intent."""

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
    """Advised convergence defaults for the calculation."""

    conv_thr: float
    provenance: Provenance

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class ParameterAdvice:
    """Complete Advise-stage output."""

    k_points: KPointAdviceRecord
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
    """Concrete k-point grid selected from advice."""

    grid: KPointGrid
    shift: KPointShift
    mesh_type: str
    provenance: Provenance

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class PseudopotentialSelection:
    """Concrete pseudopotential selected for one element."""

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
    """Complete Select-stage output."""

    k_points: KPointSelection
    pseudopotentials: tuple[PseudopotentialSelection, ...]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class GeneratedFile:
    """Generated text file content for a target DFT code."""

    path: str
    content: str

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


@dataclass(frozen=True, slots=True)
class CoreRecommendation:
    """Structured output from the staged Core pipeline."""

    intent: CalculationIntent
    analysis: StructureAnalysisRecord
    advice: ParameterAdvice
    selection: SelectionRecord
    generated_files: tuple[GeneratedFile, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def grid(self) -> KPointGrid:
        """Compatibility alias for the selected k-point grid."""
        return self.selection.k_points.grid

    @property
    def shift(self) -> KPointShift:
        """Compatibility alias for the selected k-point shift."""
        return self.selection.k_points.shift

    @property
    def contains_heavy_elements(self) -> bool:
        """Compatibility alias for heavy-element structure analysis."""
        return self.analysis.contains_heavy_elements

    @property
    def contains_transition_metals(self) -> bool:
        """Compatibility alias for transition-metal structure analysis."""
        return self.analysis.contains_transition_metals

    @property
    def contains_lanthanides(self) -> bool:
        """Compatibility alias for lanthanide structure analysis."""
        return self.analysis.contains_lanthanides

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary with compatibility aliases."""
        data = to_jsonable(self)
        data["grid"] = to_jsonable(self.grid)
        data["shift"] = to_jsonable(self.shift)
        data["contains_heavy_elements"] = self.contains_heavy_elements
        data["contains_transition_metals"] = self.contains_transition_metals
        data["contains_lanthanides"] = self.contains_lanthanides
        return data


def to_jsonable(value: Any) -> Any:
    """Convert staged pipeline values into JSON-safe Python objects."""
    if is_dataclass(value):
        if not hasattr(value, "__dataclass_fields__"):
            return asdict(value)
        return {field.name: to_jsonable(getattr(value, field.name)) for field in fields(value)}

    if isinstance(value, tuple | list):
        return [to_jsonable(item) for item in value]

    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}

    if isinstance(value, Path):
        return str(value)

    return value
