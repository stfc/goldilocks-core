"""Phase 2 of the v2 orchestrator (v2 epic 8, #8): system-level advisors.

Mirrors ``system_settings.SystemSettings``'s own field list one layer
up the pipeline: ``SystemAdvice`` holds the same decisions, plus the
simulated cell and its symmetry
(``pseudo`` composes the two pseudopotential-related ones -- see
``_pseudo.PseudoAdvice``'s own docstring on why), still as
``FieldState`` (pre-``checks.check_all``), not yet unwrapped to plain
values. See ``service/__init__.py`` for the phase boundaries this split
follows.

**The simulated cell comes first (#128).** ``service/_magnetic.py``
decides the functional, the Hubbard decision (spin polarization reads it,
#147), the simulated cell (``cell``: spin polarization, spin-orbit
coupling and the applied magnetic ordering), its symmetry
(``symmetry_eff``), the pseudopotentials and the starting moments, once
each and in that order. ``electron_count`` counts that cell, and
``boundary`` reads its vacuum (``geometry_eff``, #144), which is
published beside ``geometry``, the uploaded structure's, as ``symmetry_eff``
is beside ``symmetry``, and which vc-relax's ``cell_dofree`` reads too
(#210);
``cutoffs`` and ``vdw`` read the uploaded structure's facts. ``hubbard``
reads the input structure too: its decision is keyed by element, so it is
the same for the cell.

**``symmetry_eff`` (v2 epic 9, #9)**: ``AnalysisFacts.symmetry`` (phase 1)
is computed from the plain input ``structure``, before magnetism is
decided at all. Once the cell exists (the input's sites unless an
antiferromagnetic ordering was applied, split into the species pw.x is
given, #170), symmetry needs recomputing against *that* cell --
goldilocks-core-design.md:3116-3126's "symmetry must be recomputed once
after species-splitting, not reused from phase 1".
``n_irr_k``/``k_sampling`` (``_step_kpoints.py``) read ``cell`` directly
rather than this field's own value; ``symmetry_eff`` exists as its own
named, independently-checkable fact (not only an internal step of
computing something else), matching how the design doc's own SOC-on-Ce/AFM
acceptance scenarios name it.
"""

from __future__ import annotations

from dataclasses import dataclass

from pymatgen.core import Structure

from goldilocks_core.advisors.boundary import BoundaryFacts, boundary
from goldilocks_core.advisors.cutoffs import CutoffsDecision, cutoffs
from goldilocks_core.advisors.electron_count import (
    ElectronCountDecision,
    electron_count,
)
from goldilocks_core.advisors.hubbard_u import HubbardUDecision
from goldilocks_core.advisors.magnetic_config import MagneticCell, MagneticConfigFacts
from goldilocks_core.advisors.vdw_method import VdwFacts, vdw_method
from goldilocks_core.analysis.geometry import GeometryFacts
from goldilocks_core.analysis.symmetry import SymmetryFacts
from goldilocks_core.assets.store import AssetStore
from goldilocks_core.resolution import FieldState
from goldilocks_core.service._analysis import AnalysisFacts
from goldilocks_core.service._magnetic import magnetic_advice
from goldilocks_core.service._pseudo import PseudoAdvice
from goldilocks_core.service._system_overrides import SystemOverrides


@dataclass(frozen=True, slots=True)
class SystemAdvice:
    """``cell`` is the simulated cell every later count and the writer
    read. ``magnetic`` copies its facts and adds the starting moments, so
    ``cell`` has no record or field state of its own."""

    functional: FieldState[str]
    cell: FieldState[MagneticCell]
    pseudo: PseudoAdvice
    magnetic: FieldState[MagneticConfigFacts]
    symmetry_eff: FieldState[SymmetryFacts]
    geometry_eff: FieldState[GeometryFacts]
    cutoffs: FieldState[CutoffsDecision]
    electron_count: FieldState[ElectronCountDecision]
    vdw: FieldState[VdwFacts]
    boundary: FieldState[BoundaryFacts]
    hubbard: FieldState[HubbardUDecision]

    def field_states(self) -> tuple[FieldState[object], ...]:
        """Everything except ``functional``/``magnetic``/``electron_count``/
        ``vdw``/``boundary`` -- ``checks.check_all`` folds all five in itself;
        see its own docstring on why a caller must not repeat them here.
        ``cell`` is folded in through ``magnetic``, which is blocked whenever
        it is."""
        return (
            self.pseudo.table,
            self.pseudo.metadata,
            self.pseudo.relativistic,
            self.symmetry_eff,
            self.cutoffs,
            self.hubbard,
        )

    def records(self) -> dict[str, FieldState[object]]:
        return {
            "functional": self.functional,
            "pseudo_table": self.pseudo.table,
            "pseudopotentials": self.pseudo.metadata,
            "relativistic": self.pseudo.relativistic,
            "magnetic": self.magnetic,
            "symmetry_eff": self.symmetry_eff,
            "geometry_eff": self.geometry_eff,
            "cutoffs": self.cutoffs,
            "electron_count": self.electron_count,
            "vdw": self.vdw,
            "boundary": self.boundary,
            "hubbard": self.hubbard,
        }


def system_advice(
    structure: Structure,
    analysis: AnalysisFacts,
    overrides: SystemOverrides,
    *,
    store: AssetStore | None,
    fetch_missing: bool,
) -> SystemAdvice:
    selection = magnetic_advice(
        structure, analysis, overrides, store=store, fetch_missing=fetch_missing
    )
    functional_value = selection.functional.value
    pseudo = selection.pseudo
    return SystemAdvice(
        functional=selection.functional,
        cell=selection.cell,
        pseudo=pseudo,
        magnetic=selection.magnetic,
        symmetry_eff=selection.symmetry_eff,
        geometry_eff=selection.geometry_eff,
        cutoffs=cutoffs(pseudo.metadata, pseudo.table, overrides.cutoffs),
        electron_count=electron_count(
            selection.cell, pseudo.metadata, overrides.electron_count
        ),
        vdw=vdw_method(
            analysis.geometry, functional_value, overrides.vdw, overrides.vdw_llm
        ),
        boundary=boundary(
            selection.geometry_eff,
            analysis.symmetry,
            overrides.boundary,
            overrides.boundary_llm,
        ),
        hubbard=selection.hubbard,
    )
