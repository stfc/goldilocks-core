"""Phase 1 of the v2 orchestrator (v2 epic 8, #8): structure-only facts.

Split out of a single ``service.py`` to satisfy this project's own
import-surface ceiling (``scripts/check_complexity.py``, default 12
origins/24 symbols per module) -- an orchestrator that calls every
analysis/advisor function in the codebase cannot live in one file
without exceeding it by a wide margin. See ``service/__init__.py`` for
the phase boundaries this split follows.
"""

from __future__ import annotations

from dataclasses import dataclass

from pymatgen.core import Structure

from goldilocks_core.analysis.composition import CompositionFacts, composition
from goldilocks_core.analysis.geometry import GeometryFacts, geometry
from goldilocks_core.analysis.is_magnetic import (
    IsMagneticHumanInput,
    IsMagneticLlmInput,
    Magnetism,
    is_magnetic,
)
from goldilocks_core.analysis.is_metal import (
    IsMetalHumanInput,
    IsMetalLlmInput,
    Metallicity,
    is_metal,
)
from goldilocks_core.analysis.needs_correlation import (
    NeedsCorrelationHumanInput,
    needs_correlation,
)
from goldilocks_core.analysis.needs_soc import needs_soc
from goldilocks_core.analysis.symmetry import SymmetryFacts, symmetry
from goldilocks_core.resolution import FieldState


@dataclass(frozen=True, slots=True)
class AnalysisOverrides:
    is_metal: IsMetalHumanInput | None = None
    is_metal_llm: IsMetalLlmInput | None = None
    is_magnetic: IsMagneticHumanInput | None = None
    is_magnetic_llm: IsMagneticLlmInput | None = None
    needs_correlation: NeedsCorrelationHumanInput | None = None


@dataclass(frozen=True, slots=True)
class AnalysisFacts:
    composition: FieldState[CompositionFacts]
    geometry: FieldState[GeometryFacts]
    symmetry: FieldState[SymmetryFacts]
    is_metal: FieldState[Metallicity]
    is_magnetic: FieldState[Magnetism]
    needs_soc: FieldState[bool]
    needs_correlation: FieldState[bool]

    def field_states(self) -> tuple[FieldState[object], ...]:
        return (
            self.composition,
            self.geometry,
            self.symmetry,
            self.is_metal,
            self.is_magnetic,
            self.needs_soc,
            self.needs_correlation,
        )

    def records(self) -> dict[str, FieldState[object]]:
        return {
            "composition": self.composition,
            "geometry": self.geometry,
            "symmetry": self.symmetry,
            "is_metal": self.is_metal,
            "is_magnetic": self.is_magnetic,
            "needs_soc": self.needs_soc,
            "needs_correlation": self.needs_correlation,
        }


def analyze(structure: Structure, overrides: AnalysisOverrides) -> AnalysisFacts:
    composition_state = composition(structure)
    return AnalysisFacts(
        composition=composition_state,
        geometry=geometry(structure),
        symmetry=symmetry(structure),
        is_metal=is_metal(structure, overrides.is_metal, overrides.is_metal_llm),
        is_magnetic=is_magnetic(
            structure, overrides.is_magnetic, overrides.is_magnetic_llm
        ),
        needs_soc=needs_soc(composition_state),
        needs_correlation=needs_correlation(
            composition_state, overrides.needs_correlation
        ),
    )
