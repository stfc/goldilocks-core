"""boundary: how to handle a structure's electrostatic boundary conditions
in a periodic-cell code, from geometry's vacuum fact.

New in v2 (v2 epic 5, #5): a molecule placed in a periodic box picks up a
spurious image-interaction energy offset from its own periodic replicas
(pitfall A8, goldilocks-core-design.md:4463), and a polar slab a spurious
field across its vacuum (pitfall A9). This module reads
``GeometryFacts.vacuum_axes`` and ``GeometryFacts.slab``, never the bond
rank (``dimensionality``/``low_dimensional``), which cannot tell a molecular
crystal from a molecule in a box or a bulk layered crystal from a slab
(#126, #160) and now drives only ``advisors/vdw_method.py``'s dispersion
default.

The decision is a code-neutral isolation category, not a Quantum ESPRESSO
keyword (#161): 'periodic' (no truncation), 'slab' (the Coulomb interaction
truncated along the slab normal) or 'isolated' (truncated along all three
lattice vectors). The Quantum ESPRESSO writer maps 'slab' to
``assume_isolated='2D'`` and 'isolated' to 'martyna-tuckerman', and writes
nothing for 'periodic'.

The heuristic decides from ``GeometryFacts.vacuum_axes``, not from the bond
rank. 'isolated' needs vacuum along all three lattice vectors: QE documents
Martyna-Tuckerman for "a molecule or a cluster in a 3D supercell" (QE 7.3
PW/Doc/INPUT_PW.def:1593-1594), while CO2 dry ice ranks 'molecule' but
fills its cell, and Martyna-Tuckerman would replace its periodic Hartree,
local-potential and Ewald terms with those of an isolated cluster (#126).
The method is exact only when the density fits in half the cell along every
axis (Martyna and Tuckerman, J. Chem. Phys. 110, 2810 (1999)), which a gap
wider than `analysis.geometry.VACUUM_GAP_ANGSTROM` does not guarantee.
pw.x computes no stress under it (QE 7.3 PW/src/input.f90:1361-1365), so
generation omits `tstress` and `checks.check_all` refuses a vc-relax.
Every other cell is 'periodic'. That includes wires, because pw.x has no 1D
truncation.

'slab' is QE's 2D Coulomb truncation (Sohier, Calandra and Mauri, Phys. Rev.
B 96, 075448 (2017)), which computes energies, forces and in-plane stresses
in a two-dimensional framework (QE 7.3 PW/Doc/INPUT_PW.def:1655-1678). It
comes only from a human or llm value: the heuristic keeps a slab 'periodic',
which is accurate for a neutral, symmetric monolayer with ~20 A of vacuum,
and no pw.x comparison of '2D' against periodic boundaries exists for the
bundled monolayers. ``checks.check_all`` refuses 'slab' and 'isolated', from
any source, on a written cell without the vacuum and frame they need.

A slab carries a dipole along its normal only when no point operation of
its space group reverses that normal (``SymmetryFacts.reversible_axes``):
inversion, a mirror in the sheet, an in-plane C2 axis or an S4/S6 axis along
the normal cancels it. In a periodic cell, a polar slab's images add a
spurious field across the vacuum (pitfall A9). The heuristic then attaches
``boundary.dipole_correction_suggested`` with the keywords of QE's dipole
correction, but does not set them: under ``tefield`` pw.x uses no symmetry
and computes no stress (QE 7.3 PW/src/input.f90:659-663 and :690-694). QE
allows the correction only in a slab, with the discontinuity in the empty
space (PW/Doc/INPUT_PW.def:407-416), so ``edir`` is the vacuum axis and the
sawtooth's drop is centred in the vacuum. A cell without exactly one vacuum
axis gets no notice, whatever its bond rank: bulk graphite, 2H-MoS2 and
Bi2Se3 rank '2d' but have no vacuum (#160). Without a resolved point group
the slab may be symmetric, so there is no notice either.

The service passes the vacuum facts of the cell the input is written for
(``geometry_eff``, which the advice publishes as a record, #210), so
``edir``, ``emaxpos`` and
the 'slab' offer describe that cell, the one ``checks.check_all`` tests
'slab' on. ``symmetry`` is the uploaded structure's: an antiferromagnetic
ordering writes the same atoms in another cell with the vacuum vector at
its own index (#144), so whether an operation reverses the slab normal is
unchanged. The written cell's species, split by spin, would hide the
operations that map every spin onto an opposite one, which leave the charge
density, and so its dipole, unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from goldilocks_core.analysis.geometry import LATTICE_AXES, GeometryFacts, SlabGeometry
from goldilocks_core.analysis.symmetry import SymmetryFacts
from goldilocks_core.inputs.overrides import HumanInput, LlmInput
from goldilocks_core.resolution import (
    Blocked,
    FieldState,
    Provenance,
    Resolved,
    Warning,
    blocked_by,
)

Isolation = Literal["periodic", "slab", "isolated"]
"""How the electrostatics treat the cell's periodic images: kept
('periodic'), cut along the slab normal ('slab') or cut along all three
lattice vectors ('isolated')."""

_EOPREG = 0.1
"""QE's default width of the sawtooth's drop, as a fraction of the cell along
``edir`` (QE 7.3 PW/Doc/INPUT_PW.def:1446-1452)."""

DIPOLE_CORRECTION_SUGGESTED = Warning(
    code="boundary.dipole_correction_suggested",
    level="info",
    category="boundary",
    message=(
        "Polar slab in a periodic cell: no symmetry operation reverses the "
        "normal of its vacuum axis, so it can carry a dipole along that normal, "
        "and its periodic images add a spurious field across the vacuum. "
        "Consider Quantum ESPRESSO's dipole correction, not set automatically "
        "here: tefield = .true., dipfield = .true., edir along the vacuum axis, "
        "emaxpos and eopreg placing the sawtooth's drop inside the vacuum, and "
        "eamp = 0."
    ),
)
"""Catalogue entry; ``_dipole_notice`` names the slab's values."""


WARNING_CATALOGUE = (DIPOLE_CORRECTION_SUGGESTED,)
"""Every warning code this module can emit -- ``capabilities.py``'s
``warnings[]`` catalogue aggregates one of these tuples per advisor."""


@dataclass(frozen=True, slots=True)
class BoundaryFacts:
    isolation: Isolation
    warnings: tuple[Warning, ...] = ()


class BoundaryHumanInput(HumanInput):
    isolation: Isolation | None = None


class BoundaryLlmInput(LlmInput):
    isolation: Isolation | None = None


def boundary(
    geometry: FieldState[GeometryFacts],
    symmetry: FieldState[SymmetryFacts],
    human: BoundaryHumanInput | None = None,
    llm: BoundaryLlmInput | None = None,
) -> FieldState[BoundaryFacts]:
    """``human``/``llm`` (#36, v2 epic 9, #9): before this, ``boundary``
    was the only geometry-derived system decision with no override path
    at all -- unlike its sibling ``vdw_method`` (built in the same
    epic, reading the same ``GeometryFacts``), it had no escape hatch
    past a ``Blocked``/``Unavailable`` geometry, so a disordered/partial
    -occupancy structure (dimensionality classification does not
    support these) unconditionally blocked the whole run via this one
    field alone, even when every other setting the run needed was
    supplied. Matches ``vdw_method``'s own precedence: an explicit
    override wins outright, checked before ``geometry.ok``.

    ``symmetry``, of the structure whose cell ``geometry`` describes (the
    module docstring), decides only the heuristic's dipole notice (#160);
    unresolved, it adds none and blocks nothing."""
    human = human or BoundaryHumanInput()
    llm = llm or BoundaryLlmInput()

    if human.isolation is not None:
        return Resolved(BoundaryFacts(human.isolation), Provenance(source="human"))
    ml_value: Isolation | None = None  # no ml model wired yet; epic 11's job
    if ml_value is not None:
        return Resolved(BoundaryFacts(ml_value), Provenance(source="ml"))
    if llm.isolation is not None:
        return Resolved(BoundaryFacts(llm.isolation), Provenance(source="llm"))

    if not geometry.ok:
        return Blocked(by=blocked_by(geometry))
    return _heuristic(geometry.value, symmetry)


def _heuristic(
    facts: GeometryFacts, symmetry: FieldState[SymmetryFacts]
) -> FieldState[BoundaryFacts]:
    if len(facts.vacuum_axes) == 3:
        return Resolved(
            BoundaryFacts("isolated"),
            Provenance(
                source="heuristic",
                source_note=(
                    "vacuum along all three lattice vectors: an isolated system "
                    "needs a Coulomb cutoff to avoid spurious interaction with "
                    "its own periodic images."
                ),
            ),
        )
    return Resolved(
        BoundaryFacts("periodic", warnings=_dipole_warnings(facts.slab, symmetry)),
        Provenance(source="heuristic"),
    )


def _dipole_warnings(
    slab: SlabGeometry | None, symmetry: FieldState[SymmetryFacts]
) -> tuple[Warning, ...]:
    """The dipole notice for a slab whose vacuum axis no point operation
    reverses; nothing for any other cell, or without a resolved point
    group."""
    if slab is None or not symmetry.ok:
        return ()
    if slab.vacuum_axis in symmetry.value.reversible_axes:
        return ()
    return (_dipole_notice(slab),)


def _dipole_notice(slab: SlabGeometry) -> Warning:
    """``DIPOLE_CORRECTION_SUGGESTED`` with ``slab``'s keywords. The sawtooth
    decreases from ``emaxpos`` to ``emaxpos + eopreg`` (QE 7.3
    PW/src/extfield.f90:67-89), over ``_EOPREG`` or half the vacuum if that is
    narrower, centred on the vacuum. QE's 2D Coulomb truncation is named as the
    alternative only when ``slab.fits_2d_truncation``, the test
    ``checks.check_all`` applies to isolation='slab' on the written cell."""
    eopreg = min(_EOPREG, slab.vacuum_fraction / 2)
    emaxpos = (slab.vacuum_center - eopreg / 2) % 1.0
    alternative = (
        " Alternatively set isolation='slab', Quantum ESPRESSO's 2D Coulomb "
        "truncation, which removes the interaction between the images."
        if slab.fits_2d_truncation
        else ""
    )
    message = (
        "Polar slab in a periodic cell: no symmetry operation reverses the normal "
        f"of its vacuum axis {slab.vacuum_axis}, so it can carry a dipole along "
        "that normal, and its periodic images add a spurious field across the "
        "vacuum. Consider Quantum ESPRESSO's dipole correction, not set "
        "automatically here: tefield = .true., dipfield = .true., "
        f"edir = {LATTICE_AXES.index(slab.vacuum_axis) + 1}, "
        f"emaxpos = {_fraction(emaxpos)}, eopreg = {_fraction(eopreg)}, eamp = 0, "
        "which places the sawtooth's drop in the middle of the vacuum; pw.x then "
        f"uses no symmetry and computes no stress.{alternative}"
    )
    return DIPOLE_CORRECTION_SUGGESTED.model_copy(update={"message": message})


def _fraction(value: float) -> str:
    """A fractional coordinate to 0.0001, without trailing zeros."""
    return f"{round(value, 4):g}"
