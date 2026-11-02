"""symmetry: space group and crystal system, via spglib.

Ported as content from v1's ``legacy_analysis.py:223-235``
(``_analyze_symmetry``) -- the ``SpacegroupAnalyzer`` classification itself
is reused unchanged. What changes is the failure handling: v1's
``analyze_structure`` caught ``SymmetryAnalysisError`` and downgraded every
field to ``None`` plus a warning string. That is exactly the ``Unavailable``
case, now named as one -- not an escape hatch peculiar to this one field
while an equivalent failure in ``geometry.py`` aborted the entire call
(goldilocks-core-design.md:299-310).

No ``human``/``llm`` override here: nothing in the evidence for this epic
(stfc/goldilocks-core#133/#175/#177) asks for one, and space group is
directly computed from geometry, not a judgement call.

``reversible_axes`` names the lattice vectors whose plane normal (the normal
to the other two vectors) some point operation of the space group maps to
its negative. A structure has no dipole along such a normal, since the
dipole is invariant under every operation (#160). Inversion, a mirror
normal to it, a C2 axis perpendicular to it and an S4 or S6 axis along it
all reverse it. An operation with fractional rotation matrix W maps the
plane normal of Miller index h to that of h W^-1, so the normal of lattice
vector i is reversed by some operation exactly when row i of some W is
minus the unit row e_i (the group holds W^-1 whenever it holds W): an
integer test, free of Cartesian tolerances.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from pymatgen.core import Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from goldilocks_core.analysis.geometry import LATTICE_AXES, LatticeAxis
from goldilocks_core.resolution import FieldState, Provenance, Resolved, Unavailable

SYMPREC = 0.01
"""Angstrom: the tolerance core searches a crystal's symmetry with --
``SpacegroupAnalyzer``'s default -- for the space group here (and so
``symmetry_eff``), the axes ``kmesh.py`` meshes alike and the positions
in the compensated-ordering test of ``advisors/magnetic_config.py``,
which compares the starting magnetizations to rounding instead. The
k-point count of ``advisors/n_irr_k.py`` is pw.x's, with pw.x's own
tolerances, and the cell is idealized at ``pw_symmetry.FRAME_TOLERANCE``
before it is written (#140)."""


@dataclass(frozen=True, slots=True)
class SymmetryFacts:
    """``reversible_axes``: the lattice vectors, in a, b, c order, whose
    plane normal some point operation maps to its negative (see the module
    docstring)."""

    space_group_symbol: str
    space_group_number: int
    crystal_system: str
    reversible_axes: tuple[LatticeAxis, ...]


def symmetry(structure: Structure) -> FieldState[SymmetryFacts]:
    try:
        analyzer = SpacegroupAnalyzer(structure, symprec=SYMPREC)
        facts = SymmetryFacts(
            space_group_symbol=analyzer.get_space_group_symbol(),
            space_group_number=analyzer.get_space_group_number(),
            crystal_system=analyzer.get_crystal_system(),
            reversible_axes=_reversible_axes(analyzer),
        )
    except (TypeError, ValueError) as error:
        return Unavailable(reason=f"symmetry analysis failed: {error}")
    return Resolved(facts, Provenance(source="heuristic"))


def _reversible_axes(analyzer: SpacegroupAnalyzer) -> tuple[LatticeAxis, ...]:
    rotations = [
        np.rint(operation.rotation_matrix).astype(int)
        for operation in analyzer.get_symmetry_operations()
    ]
    reversed_normal = -np.eye(3, dtype=int)
    return tuple(
        axis
        for index, axis in enumerate(LATTICE_AXES)
        if any(
            np.array_equal(rotation[index], reversed_normal[index])
            for rotation in rotations
        )
    )
