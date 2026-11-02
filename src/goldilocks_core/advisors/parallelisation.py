"""parallelisation: npool/ndiag, from a job's ntasks and the step's
k-point/spin pairs -- the other half of the false-circularity fix
`advisors/job_resources.py` describes: a pure function of `ntasks`, the
pair count and the user's overrides that never reads a job, so
`job_resources` evaluates it for each candidate `ntasks` before
settling on one.

New in v2 (v2 epic 7, #7); no v1 precedent.

**Pools share k-point/spin pairs, not k-points (#168).** A collinear
nspin=2 run lists every k-point once per spin (QE 7.3
`PW/src/setup.f90:617` calls `set_kup_and_kdw`, which doubles nkstot,
`set_kup_and_kdw.f90:42`), so its pools share N = 2 x n_irr_k pairs;
nspin=1 and noncollinear (spin-orbit) runs share N = n_irr_k.
`kpoint_spin_pairs` derives N from the spin layout the writer renders
(`qe_spin_layout`). `divide_et_impera` gives every pool N // npool pairs
and the first N mod npool pools one more
(`PW/src/divide_et_impera.f90:49-56`), so the run lasts ceil(N/npool)
rounds and npool pools offer ceil(N/npool) x npool pair slots.

**Constraints and the default.** `npool` must divide `ntasks`: QE
refuses any other layout, and `checks.py` blocks it. A pool beyond the
Nth has nothing to do. `best_npool` takes the largest divisor of
`ntasks` that is at most N and keeps the pair slots within 25% of N
(`_POOL_SLOT_TOLERANCE`), trading k-point parallelism against idle
slots; it does not search for the actually-fastest layout, which is
named as needing ml (goldilocks-core-design.md:1396-1407).

**`ndiag` is left to pw.x unless the user sets it (#133).** Without
`-ndiag`, pw.x (QE >= 7.1) picks the largest square np^2 with
np <= nint(nbnd/100) that fits the processes per pool, so 1 below 150
bands (QE 7.3 `PW/src/setup.f90:827-832`). `diag_grid_side` gives the
grid side for either case, so `checks.py`'s gate and the memory
estimate (`advisors/size.py`, #148) use one derivation. A user `ndiag`
runs on an s x s grid and can stop pw.x: it aborts at startup
when s > nbnd (`Modules/set_para_diag.f90:54-55`), and ScaLAPACK's
block layout leaves a process column without rows of an n x n subspace
matrix for some n <= (s-1)^2 (`LAXlib/la_helper.f90:468-481`), which
ELPA rejects and QE does not detect (`LAXlib/zhpev_drv.f90:1513`).
`checks.py`'s `_ndiag_grid_must_distribute_bands` refuses such a value;
this module only carries it. Without ScaLAPACK, LAXlib still honours
`-ndiag` with its own distributed solver
(`Modules/set_para_diag.f90:79-83`).

`-nband`/`-nb` (band groups, useful for hybrid functionals) and
`-ntg`/`-nt` (task groups, FFT parallelization for very large process
counts) are real, separate QE parallelization layers this module does
not model at all -- no advisor in this codebase needs them yet
(hybrid-functional support, and job sizes large enough for FFT-plane
-count to bind, are both out of scope today).

**`nimage` is always `None` here.** It only applies to NEB/phonon tasks
(`neb.x`'s images, `ph.x`'s irreps/q-points), and this codebase has no
NEB/phonon per-step advisor yet to decide how many images/q-points
there even are -- a documented gap, not a default of 1 masquerading as
a decision.

No `llm` override: `npool`/`ndiag` are technical MPI-layout tuning
knobs, not a scientific judgement call.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import NamedTuple

from pydantic import Field

from goldilocks_core.advisors.magnetic_config import MagneticConfigFacts
from goldilocks_core.inputs.overrides import HumanInput
from goldilocks_core.resolution import FieldState, Provenance, Resolved, Warning

WARNING_CATALOGUE = (
    Warning(
        code="parallelisation.npool_does_not_divide_ntasks",
        level="warning",
        category="parallelisation",
        message="npool does not divide ntasks; QE will refuse this layout.",
    ),
    Warning(
        code="parallelisation.npool_exceeds_kpoints",
        level="warning",
        category="parallelisation",
        message=(
            "npool exceeds the number of k-point/spin pairs pw.x distributes; "
            "the extra pools will have no k-point to work on."
        ),
    ),
    Warning(
        code="parallelisation.npool_load_imbalance",
        level="info",
        category="parallelisation",
        message=(
            "npool does not divide the number of k-point/spin pairs evenly; "
            "the first pools handle one more pair than the rest."
        ),
    ),
    Warning(
        code="parallelisation.ndiag_not_a_square_integer",
        level="info",
        category="parallelisation",
        message=(
            "ndiag is not a square integer; pw.x runs the largest square "
            "grid that fits and never rejects the value."
        ),
    ),
)
"""Every warning code this module can emit -- ``capabilities.py``'s
``warnings[]`` catalogue aggregates one of these tuples per advisor. The
real, per-occurrence messages (naming the actual npool/ntasks/pair
figures) are built at their call sites below; these are the generic
descriptions of each code, for a caller that has not seen it fire."""

_POOL_SLOT_TOLERANCE = 1.25
"""``best_npool`` keeps the ceil(N/npool) x npool pair slots of its pools
within this factor of the N k-point/spin pairs, so at most a fifth of
the slots sit idle. One SCARF timing backs it: MnSi B20's 48 pairs on
64 tasks ran in 39.9 s on 16 pools and 63.5 s on 32 (different node
generations); a factor of 4/3 or more would pick 32 pools there."""


@dataclass(frozen=True, slots=True)
class ParallelisationDecision:
    npool: int
    ndiag: int | None
    kpoint_spin_pairs: int
    """The k-point/spin pairs pw.x splits over the pools."""
    nimage: int | None = None
    warnings: tuple[Warning, ...] = ()


class ParallelisationHumanInput(HumanInput):
    """``npool``/``ndiag`` must be positive (#35, v2 epic 9, #9): before
    this, ``npool=0`` reached ``job.ntasks % npool`` as a raw
    ``ZeroDivisionError`` and a negative ``ndiag`` reached ``math.isqrt``.
    The layout itself is refused in ``checks.py``, not here: an ``npool``
    that does not divide ``ntasks`` (``_npool_must_divide_ntasks``) and
    an ``ndiag`` whose grid cannot distribute ``nbnd`` bands
    (``_ndiag_grid_must_distribute_bands``, #133). A non-square ``ndiag``
    only gets an info note: pw.x runs the largest square grid that fits."""

    npool: int | None = Field(default=None, gt=0)
    ndiag: int | None = Field(default=None, gt=0)


class SpinLayout(NamedTuple):
    """pw.x's density components (``nspin``), spinor components
    (``npol``) and magnetization components (``nspin_mag``)."""

    nspin: int
    npol: int
    nspin_mag: int


def qe_spin_layout(magnetic: MagneticConfigFacts) -> SpinLayout:
    """The spin layout of the pw.x run the writer renders for
    ``magnetic.spin_mode`` (``_magnetic_keywords`` in
    ``generation/quantum_espresso/scf.py``): ``noncollinear`` renders
    ``noncolin``, which pw.x runs with nspin=4 and two-component spinors,
    magnetic or not (QE 7.3 ``PW/src/input.f90:718``), and with four
    magnetization components only when it renders a starting
    magnetization, which a spin-polarised result always has
    (``input.f90:1589``, ``set_spin_vars.f90:29-41``); ``collinear``
    renders nspin=2; ``none`` runs nspin=1."""
    if magnetic.spin_mode == "noncollinear":
        return SpinLayout(4, 2, 4 if magnetic.spin_polarized else 1)
    if magnetic.spin_mode == "collinear":
        return SpinLayout(2, 1, 2)
    return SpinLayout(1, 1, 1)


def kpoint_spin_pairs(n_irr_k: int, magnetic: MagneticConfigFacts) -> int:
    """The k-point/spin pairs pw.x distributes over pools: 2 x
    ``n_irr_k`` for collinear nspin=2, otherwise ``n_irr_k`` (see the
    module docstring)."""
    return 2 * n_irr_k if qe_spin_layout(magnetic).nspin == 2 else n_irr_k


def parallelisation(
    ntasks: int,
    n_kpoint_spin: int,
    human: ParallelisationHumanInput | None = None,
) -> FieldState[ParallelisationDecision]:
    """``npool`` for ``ntasks`` processes and ``n_kpoint_spin``
    k-point/spin pairs (``kpoint_spin_pairs``) unless ``human`` sets it;
    ``ndiag`` only from ``human`` (``None`` leaves it to pw.x)."""
    human = human or ParallelisationHumanInput()

    if human.npool is not None:
        npool = human.npool
        warnings = _human_npool_warnings(npool, ntasks, n_kpoint_spin)
        source = "human"
    else:
        npool = best_npool(ntasks, n_kpoint_spin)
        warnings = _load_imbalance_notes(npool, n_kpoint_spin)
        source = "heuristic"

    if human.ndiag is not None:
        source = "human"
        warnings.extend(_ndiag_notes(human.ndiag, ntasks // npool))

    decision = ParallelisationDecision(
        npool=npool,
        ndiag=human.ndiag,
        kpoint_spin_pairs=n_kpoint_spin,
        warnings=tuple(warnings),
    )
    return Resolved(decision, Provenance(source=source))


def best_npool(ntasks: int, n_kpoint_spin: int) -> int:
    """The largest divisor of ``ntasks`` that is at most
    ``n_kpoint_spin`` (N) and whose ceil(N/npool) x npool pair slots stay
    within ``_POOL_SLOT_TOLERANCE`` x N. npool=1 always qualifies."""
    return max(
        npool
        for npool in range(1, min(ntasks, n_kpoint_spin) + 1)
        if ntasks % npool == 0
        and math.ceil(n_kpoint_spin / npool) * npool
        <= _POOL_SLOT_TOLERANCE * n_kpoint_spin
    )


def _human_npool_warnings(npool: int, ntasks: int, n_kpoint_spin: int) -> list[Warning]:
    warnings: list[Warning] = []
    if ntasks % npool != 0:
        warnings.append(
            Warning(
                code="parallelisation.npool_does_not_divide_ntasks",
                level="warning",
                category="parallelisation",
                message=(
                    f"npool={npool} does not divide ntasks={ntasks}; QE will "
                    "refuse this layout."
                ),
            )
        )
    if npool > n_kpoint_spin:
        warnings.append(
            Warning(
                code="parallelisation.npool_exceeds_kpoints",
                level="warning",
                category="parallelisation",
                message=(
                    f"npool={npool} exceeds the {n_kpoint_spin} k-point/spin "
                    f"pairs pw.x distributes; {npool - n_kpoint_spin} pool(s) "
                    "will have no k-point to work on."
                ),
            )
        )
    return warnings


def _load_imbalance_notes(npool: int, n_kpoint_spin: int) -> list[Warning]:
    """A note when the first N mod npool pools take one pair more than
    the rest (``PW/src/divide_et_impera.f90:49-56``)."""
    if n_kpoint_spin % npool == 0:
        return []
    return [
        Warning(
            code="parallelisation.npool_load_imbalance",
            level="info",
            category="parallelisation",
            message=(
                f"npool={npool} does not divide the {n_kpoint_spin} "
                "k-point/spin pairs evenly; the first "
                f"{n_kpoint_spin % npool} pool(s) handle one more pair than "
                "the rest."
            ),
        )
    ]


def diag_grid_side(ndiag: int | None, procs_per_pool: int, nbnd: int) -> int:
    """Side s of the s x s linear-algebra grid pw.x builds for ``nbnd``
    bands. With ``-ndiag``: isqrt(min(ndiag, processes per pool)), at
    least 1 (QE 7.3 ``LAXlib/la_helper.f90:125`` and ``:171-176``,
    ``GRID2D_DIMS`` 'S' in ``LAXlib/distools.f90:84``). pw.x takes the
    processes of a band group; without ``-nband`` that is the whole
    pool. Without it (``None``), pw.x's own choice: the largest
    np <= nint(nbnd/100) with np^2 <= processes per pool, at least 1
    (``PW/src/setup.f90:827-832``). Fortran's nint rounds halves away
    from zero, so nbnd=250 gives np=3."""
    if ndiag is None:
        largest = (nbnd + 50) // 100  # nint(nbnd/100.) for nbnd >= 0
        side = next(
            (np for np in range(largest, 0, -1) if np * np <= procs_per_pool), 1
        )
        ndiag = side * side
    return _grid_side(ndiag, procs_per_pool)


def _grid_side(ndiag: int, procs_per_pool: int) -> int:
    return max(1, math.isqrt(min(ndiag, procs_per_pool)))


def _ndiag_notes(ndiag: int, procs_per_pool: int) -> list[Warning]:
    root = math.isqrt(ndiag)
    if root * root == ndiag:
        return []
    side = _grid_side(ndiag, procs_per_pool)
    return [
        Warning(
            code="parallelisation.ndiag_not_a_square_integer",
            level="info",
            category="parallelisation",
            message=(
                f"ndiag={ndiag} is not a square integer; pw.x runs a "
                f"{side}x{side} grid ({side * side} processes) and never "
                "rejects the value."
            ),
        )
    ]
