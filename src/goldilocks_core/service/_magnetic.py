"""The simulated cell and the pseudopotentials chosen for it, each decided
once (#128).

These decisions depend on one another in a fixed order:

1. the functional, the Hubbard decision, which reads it, and
   ``magnetic_cell`` -- spin polarization, which reads the Hubbard
   decision (a U on an odd d or f count needs a spin-polarized run,
   #147), spin-orbit coupling, and the requested magnetic ordering applied
   to the structure,
   which is the calculation's only enumlib call, split into one species per
   element and starting-magnetization class (#170) -- ending with
   ``framed_cell``, which writes that cell in the frame where pw.x keeps
   the most of its point group: idealized, and turned or shifted when that
   is what it takes (``pw_symmetry.pw_frame``, #140);
2. pseudopotential table selection, which reads the functional and the
   cell's spin-orbit switch (the relativistic requirement), and the same
   selection with spin-orbit coupling on (``soc_pseudo_table``), whose
   verdict decides whether the spin-orbit notice suggests SOC (#181);
3. ``magnetic_config``, the starting moments on the cell, scaled by the
   selected pseudopotentials' z_valence.

``symmetry_eff`` is the cell's own symmetry, counted on those species,
and ``geometry_eff`` the uploaded structure's geometry with the written
cell's own vacuum and frame (``_cell_geometry``), which the boundary
advisor's dipole notice and 'slab' offer describe (#144) and vc-relax's
``cell_dofree`` is decided from (#140). Every later decision -- the
electron count, bands, k-points, convergence, resources, the gate and the
writer -- reads the same cell object (``MagneticCell.structure``), and the
input structure stops here: no count can describe a cell other than the
one written. The magnetic decision used to run twice, once before table
selection and once after, enumerating each time (#184).
"""

from __future__ import annotations

from dataclasses import dataclass

from pymatgen.core import Structure

from goldilocks_core.advisors.functional import functional
from goldilocks_core.advisors.hubbard_u import HubbardUDecision, hubbard_u
from goldilocks_core.advisors.magnetic_config import (
    MagneticCell,
    MagneticConfigFacts,
    framed_cell,
    magnetic_cell,
    magnetic_config,
)
from goldilocks_core.analysis.geometry import GeometryFacts, with_vacuum_of
from goldilocks_core.analysis.symmetry import SymmetryFacts, symmetry
from goldilocks_core.assets.pseudopotentials.registry import PseudoTable
from goldilocks_core.assets.store import AssetStore
from goldilocks_core.resolution import Blocked, FieldState, Resolved, blocked_by
from goldilocks_core.service._analysis import AnalysisFacts
from goldilocks_core.service._pseudo import (
    PseudoAdvice,
    resolve_pseudopotentials,
    soc_pseudo_table,
)
from goldilocks_core.service._system_overrides import SystemOverrides


@dataclass(frozen=True, slots=True)
class MagneticAdvice:
    """The decisions above, in order; ``system_advice`` copies them onto
    ``SystemAdvice``. ``geometry_eff`` is the uploaded structure's geometry
    with the written cell's vacuum facts (``_cell_geometry``), which the
    boundary advisor and vc-relax's ``cell_dofree`` read and the advice
    publishes as its ``geometry_eff`` record (#144, #210)."""

    functional: FieldState[str]
    hubbard: FieldState[HubbardUDecision]
    cell: FieldState[MagneticCell]
    symmetry_eff: FieldState[SymmetryFacts]
    geometry_eff: FieldState[GeometryFacts]
    pseudo: PseudoAdvice
    magnetic: FieldState[MagneticConfigFacts]


def magnetic_advice(
    structure: Structure,
    analysis: AnalysisFacts,
    overrides: SystemOverrides,
    *,
    store: AssetStore | None,
    fetch_missing: bool,
) -> MagneticAdvice:
    """The functional, the Hubbard decision, the simulated cell, its
    symmetry, the pseudopotentials and the starting moments for
    ``structure``. The Hubbard decision is keyed by element, so it reads
    ``structure`` and holds for the cell."""
    functional_state = functional(overrides.functional, overrides.functional_llm)
    hubbard = hubbard_u(
        structure,
        analysis.needs_correlation,
        functional_state.value,
        overrides.hubbard,
        overrides.hubbard_llm,
    )
    cell = magnetic_cell(
        structure,
        analysis.is_magnetic,
        overrides.magnetic,
        overrides.magnetic_llm,
        hubbard=hubbard,
    )
    if cell.ok:
        cell = Resolved(framed_cell(cell.value), cell.provenance)
        elements = set(analysis.composition.value.elements)
        pseudo = resolve_pseudopotentials(
            elements=elements,
            functional=functional_state.value,
            spin_orbit_enabled=cell.value.spin_orbit_enabled,
            table_id=overrides.pseudo_table_id,
            store=store,
            fetch_missing=fetch_missing,
        )
        soc_table = soc_pseudo_table(elements, functional_state.value)
        symmetry_eff = symmetry(cell.value.structure)
        geometry_eff = _cell_geometry(analysis.geometry, cell)
    else:
        cause = Blocked(by=blocked_by(cell))
        pseudo = PseudoAdvice(
            table=cause, metadata=cause, relativistic=cause, installed=None
        )
        symmetry_eff = geometry_eff = soc_table = cause
    return MagneticAdvice(
        functional=functional_state,
        hubbard=hubbard,
        cell=cell,
        symmetry_eff=symmetry_eff,
        geometry_eff=geometry_eff,
        pseudo=pseudo,
        magnetic=_seeded(cell, pseudo, soc_table, analysis),
    )


def _cell_geometry(
    geometry: FieldState[GeometryFacts], cell: FieldState[MagneticCell]
) -> FieldState[GeometryFacts]:
    """``geometry`` with the vacuum facts of the written ``cell``
    (``analysis.geometry.with_vacuum_of``): its vacuum axes and widths, and
    whether a slab lies in the xy frame, which ``framed_cell`` puts every
    slab with its vacuum along c in (#140). An unresolved ``geometry`` or
    ``cell`` leaves ``geometry`` as it is."""
    if not (geometry.ok and cell.ok):
        return geometry
    return Resolved(
        with_vacuum_of(geometry.value, cell.value.structure), geometry.provenance
    )


def _seeded(
    cell: FieldState[MagneticCell],
    pseudo: PseudoAdvice,
    soc_table: FieldState[PseudoTable],
    analysis: AnalysisFacts,
) -> FieldState[MagneticConfigFacts]:
    """``magnetic_config`` on the selected table's z_valence. A table that
    is not installed yet (``Unavailable``, a normal preview) leaves the
    flat default fractions; a selection that failed outright (``Blocked``:
    no compatible table exists, e.g. spin-orbit coupling on a lanthanide
    that only SSSP covers) blocks the decision instead of serving
    uncalibrated seeds as if they were good. ``soc_table``, the selection
    spin-orbit coupling would make, decides the spin-orbit notice (#181)."""
    if isinstance(pseudo.metadata, Blocked):
        return Blocked(by=pseudo.metadata)
    z_valences = (
        {
            item.element: item.z_valence
            for item in pseudo.metadata.value
            if item.element is not None and item.z_valence is not None
        }
        if pseudo.metadata.ok
        else None
    )
    return magnetic_config(cell, analysis.needs_soc, soc_table, z_valences)
