"""n_irr_k: the k-points pw.x runs, for one already-chosen mesh.

New in v2 (v2 epic 6, #6). Third of five per-step advisors
(``occupations -> k_sampling -> n_irr_k -> nbnd -> convergence``,
goldilocks-core-design.md:3239-3248, :3385). The one place core reduces
a k-mesh by symmetry: the mesh ``advisors/k_sampling.py`` picked, on the
simulated cell as written (``MagneticCell``). The ladder
(``kmesh.build_gamma_kmesh_entries``) carries no reduced counts;
reducing every rung of it cost seconds per ``advise()`` (#155).

**Counted as pw.x counts (#140).** pw.x does not use the crystal's space
group: it tests 32 fixed Cartesian rotations against the lattice as
written, keeps those that map every atom onto one of its own species, and
in a supercell allows them no fractional translation
(``pw_symmetry.pw_rotations``). The count is the mesh reduced by what pw.x
keeps (``pw_symmetry.irreducible_kpoint_count``), so npool, memory and the
load-imbalance notice describe the k-points pw.x runs. spglib's full space
group on a cell in pymatgen's frame counted 47 k-points of diamond Si's
10x10x10 mesh while pw.x ran 282; the magnetic step now writes the cell in
the frame where pw.x keeps the most of the point group
(``pw_symmetry.pw_frame``), and the count follows the cell whatever frame
it is in.

**Counted on the cell's species.** A spin-polarized cell holds one species
per element and starting-magnetization class
(``advisors/species_split.py``), each carried as ``Species.spin``, the
types pw.x is given (#170). A cell whose sublattices start with opposite
moments therefore reduces less than its bare elements would.

**Noncollinear moments (#172).** A spin-polarized run with spin-orbit
coupling is the one case where pw.x reduces by magnetic symmetry
(``magnetic_sym = noncolin .AND. domag``, QE 7.3
``PW/src/setup.f90:484-485``): it keeps the operations that map every
moment onto its image's moment, alone or combined with time reversal
(``symm_base.f90``'s ``sgam_at_mag``), lets a time-reversed operation act
on k as -R, and drops the plain k -> -k pairing. Its moments are each
site's starting-magnetization class (``Species.spin``) times the cell's
moment direction (``MagneticCell.moment_axis``); only their types, signs
and direction matter, so the count needs no pseudopotential. B2 FeCo with
moments along [001] keeps 16 of 48 operations, 126 k-points of a 10^3
mesh against the structural 56, as pw.x 7.5 ran it. Every other run
counts on the structure alone.

**Not guarded**: core uses this number to size memory and choose
``npool``, and the irreducible count and the full mesh size are both
ordinary integers, so a caller could not tell a fallback from a real
answer (a cubic cell reduces by up to 48x) -- a silently wrong value
there is far more dangerous than a raised error.

**pw.x's symmetry flags.** ``nosym``, ``noinv``, ``no_t_rev`` and
``force_symmorphic`` would change the count, but no setting writes them to
the input, so pw.x runs with its defaults, which this count follows. A
``nosym`` setting that changed this count but never the input was removed
(#225); add one back together with the decision that writes it. There is
no override: the count is a fact of the written mesh and cell.
"""

from __future__ import annotations

from goldilocks_core.advisors.k_sampling import KSamplingDecision
from goldilocks_core.advisors.magnetic_config import MagneticCell
from goldilocks_core.pw_symmetry import irreducible_kpoint_count, pw_rotations
from goldilocks_core.resolution import (
    Blocked,
    FieldState,
    Provenance,
    Resolved,
    blocked_by,
)


def n_irr_k(
    cell: MagneticCell,
    k_sampling: FieldState[KSamplingDecision],
) -> FieldState[int]:
    """The k-points pw.x runs of ``k_sampling``'s mesh on the simulated
    ``cell`` as written: by its magnetic symmetry when it has a moment
    direction (a spin-polarized spin-orbit run), otherwise by its
    structural symmetry, each as pw.x finds it (module docstring)."""
    if isinstance(k_sampling, Blocked):
        return Blocked(by=k_sampling)
    if not k_sampling.ok:
        return Blocked(by=blocked_by(k_sampling))

    rotations = pw_rotations(cell.structure, cell.moment_axis)
    count = irreducible_kpoint_count(
        rotations, k_sampling.value.mesh, k_sampling.value.shift
    )
    return Resolved(count, Provenance(source="heuristic"))
