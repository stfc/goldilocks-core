"""electron_count: nelec, from the simulated cell's composition and the
selected pseudopotentials' z_valence.

New in v2 (v2 epic 7, #7). No advisor computed this before --
`advisors/nbnd.py` (v2 epic 6, #6) already documented `nelec` as "a
required, plain input... no advisor computes this yet", naming
`advisors/pseudo_selection.py`'s eventual materialize step as the
missing piece. This is that piece: `nelec = sum(z_valence[element] *
count[element] for element in cell)`, summed over the cell's actual
composition (not just the set of distinct elements), matching how a real
UPF pseudopotential reports its own valence electron count per atom --
``PseudoMetadata.z_valence``, already parsed from UPF headers or provider
sidecars (v2 epic 3, #4).

**Counted on the cell the writer renders** (``MagneticCell.structure``,
#128): an applied antiferromagnetic ordering can write a different cell
from the uploaded one, and an electron count of the uploaded cell then
reached pw.x as a charge (``tot_charge = 24`` on NiO's 4-atom AFM-II cell).

**The charge is decided here, once.** QE's input takes a charge, not an
electron count (``&SYSTEM`` has ``tot_charge`` and no ``nelec``, #34), so a
human ``nelec`` becomes ``tot_charge`` = the cell's neutral count minus
``nelec``; the heuristic count is neutral. The writer renders
``tot_charge`` verbatim and never compares two counts itself. A human
``nelec`` counts the uploaded cell's electrons, so it is refused once the
ordering wrote a cell of another size.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from pydantic import Field

from goldilocks_core.advisors.magnetic_config import MagneticCell
from goldilocks_core.assets.pseudopotentials.upf import PseudoMetadata
from goldilocks_core.inputs.overrides import HumanInput
from goldilocks_core.resolution import (
    Blocked,
    FieldState,
    Provenance,
    Resolved,
    blocked_by,
)


@dataclass(frozen=True, slots=True)
class ElectronCountDecision:
    """``nelec`` electrons in the simulated cell, and its net charge
    ``tot_charge`` (the neutral count minus ``nelec``): 0.0 unless a
    ``nelec`` was requested."""

    nelec: float
    tot_charge: float


class ElectronCountHumanInput(HumanInput):
    nelec: float | None = Field(default=None, gt=0)


def electron_count(
    cell: FieldState[MagneticCell],
    pseudos: FieldState[tuple[PseudoMetadata, ...]],
    human: ElectronCountHumanInput | None = None,
) -> FieldState[ElectronCountDecision]:
    """The cell's electron count and charge (module docstring). ``Blocked``
    when the cell or the pseudopotentials are not resolved, when an element
    has no z_valence, or when a human ``nelec`` meets an ordering that
    changed the cell's size."""
    human = human or ElectronCountHumanInput()

    if not cell.ok:
        return Blocked(by=blocked_by(cell))
    if human.nelec is not None:
        resized = _resized_cell_reason(cell.value)
        if resized is not None:
            return Blocked(by=resized)
    if not pseudos.ok:
        return Blocked(by=blocked_by(pseudos))

    z_valence_by_element = {
        metadata.element: metadata.z_valence for metadata in pseudos.value
    }
    counts = cell.value.structure.composition.get_el_amt_dict()
    missing = sorted(
        element for element in counts if z_valence_by_element.get(element) is None
    )
    if missing:
        return Blocked(by=f"no z_valence for {', '.join(missing)}")

    neutral = sum(
        z_valence_by_element[element] * count for element, count in counts.items()
    )
    if human.nelec is not None:
        return Resolved(
            ElectronCountDecision(nelec=human.nelec, tot_charge=neutral - human.nelec),
            Provenance(source="human"),
        )
    return Resolved(
        ElectronCountDecision(nelec=neutral, tot_charge=0.0),
        Provenance(source="heuristic"),
    )


def _resized_cell_reason(cell: MagneticCell) -> str | None:
    """Why a human ``nelec`` cannot apply to ``cell``: its volume differs
    from the uploaded cell's (``cell_in_input_basis`` has a determinant
    other than +-1), so the two hold different numbers of atoms."""
    volume_ratio = abs(float(np.linalg.det(cell.cell_in_input_basis)))
    if math.isclose(volume_ratio, 1.0, rel_tol=1e-6):
        return None
    written = len(cell.structure)
    uploaded = round(written / volume_ratio)
    return (
        f"nelec refers to the uploaded {uploaded}-atom cell, but "
        f"magnetic_ordering={cell.ordering.applied!r} wrote a {written}-atom "
        "cell; drop nelec or magnetic_ordering"
    )
