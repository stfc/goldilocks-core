"""checks: the one place in the whole system allowed to refuse a request.

New in v2 (v2 epic 6, #6); no v1 precedent. Per
goldilocks-core-design.md's own summary (line 4007): "``check_all`` is
the sole gateway for cross-parameter constraints, and also the boundary
between ``advise`` and ``generate``." For the phonon tasks that gateway
is ``check_all`` followed by ``with_phonon_findings``, which adds their
own rules to its report (rules 9-17 below). Every advisor in this codebase
degrades field-by-field (``Resolved``/``Unavailable``/``Blocked``)
instead of refusing a request, and only a fault (such as a worker process
that dies) raises; a runnable input is only refused here, by returning a
non-empty ``CheckReport.blocking`` for a future ``generate()`` to read
-- not by raising an exception. **By convention, any other ``raise`` in
generation/advisor code found after this epic should be treated as
suspicious** (the issue's own acceptance criterion), since this module
is now where that decision belongs.

**Two independent mechanisms, not one:**

1. ``collect_blocked`` -- cross-parameter constraints are not the only
   way to end up unable to generate a runnable input: any upstream
   advisor that itself resolved to ``Blocked`` should also end up in
   ``report.blocking``, with its root cause surfaced (the design doc's
   own "blocking is derivable... the rejection reason follows the
   ``blocked_by`` chain back to the root cause, no separate
   error-message system needed", goldilocks-core-design.md:3261-3263).
   This mechanism is generic: it takes any ``FieldState`` from any
   advisor, not just the ones this epic happens to build.

2. A named cross-parameter rule -- ``occupations='fixed'`` together with
   a collinear spin-polarized run (``MagneticConfigFacts.spin_mode``
   ``collinear``, nspin=2) requires an *integer* ``tot_magnetization``
   *that shares parity with the electron count* (nelup=(nelec+tot)/2,
   neldw=(nelec-tot)/2, #70: both need to be whole numbers, which an
   integer ``tot_magnetization`` alone does not guarantee -- QE's own
   requirement once occupation numbers are no longer automatically
   split by smearing). pw.x stops on fixed occupations without one only
   with lsda (QE 7.3 ``PW/src/input.f90:764-781``); a noncollinear
   (spin-orbit) run has lsda off and takes no ``tot_magnetization`` at
   all (``input.f90:761-762``), so it needs none (#146). This is scoped
   to the ``scf`` step only: an ``nscf`` step reads the charge/spin
   density a prior ``scf`` step already converged and does not re-derive
   this constraint (goldilocks-core-design.md:3417, "per-step
   constraint").
   The moment checked is the occupations decision's
   (``OccupationsDecision.tot_magnetization``), the one the writer
   renders (#138). ``advisors/occupations.py`` picks fixed for a
   collinear run only with a moment that passes, so this rule fires only
   for an explicit ``occupations='fixed'``, which that advisor flags with
   a warning; only *this* module blocks.

3. Its sibling rule, found empirically 2026-09-16 against real QE 7.3
   source (``PW/src/iweights.f90``'s ``iweights_only``): ``occupations
   ='fixed'`` together with a *non*-spin-polarized run (spin mode
   ``none``, or a spin-orbit run without moments) requires an *even*
   ``electron_count`` -- with ``nspin=1``
   (``degspin=2``), fixed occupations fill ``NINT(nelec)/degspin``
   doubly-occupied bands, which can only reconstruct an even ``nelec``
   exactly. An odd ``nelec`` here silently truncates to the nearest even
   count (QE only ever prints an ``infomsg`` -- "the system is metallic,
   specify occupations" -- never an error), converging on a wrong total
   charge with nothing obviously wrong in the output. A noncollinear run
   fills single-electron spinor bands (``degspin=1``,
   ``iweights.f90:105-107``), so its count is never truncated, but one
   without moments keeps time reversal (``domag`` false), so every band
   has a Kramers partner degenerate with it at the time-reversal-invariant
   k-points, and at every k with inversion: an odd count half-fills a
   degenerate pair, a metallic state fixed occupations cannot describe,
   and the rule applies to it too. Only a spin-polarized noncollinear run,
   which breaks time reversal, is exempt (#146). Same
   ``plan.SCF_LIKE_PURPOSES`` scoping as
   rule 2, same reasoning; like rule 2 it is reachable only from an
   explicit ``occupations='fixed'``, since the advisor's default for an odd
   count is smearing (#138).

4. ``nbnd`` must hold every electron of each spin channel (#131): pw.x
   stops in setup below ``NINT(nelec/2)`` ("too few bands"), below
   ``NINT(nelup)`` or ``NINT(neldw)`` ("too few spin up/dw bands") and, for
   a noncollinear run, below ``NINT(nelec)`` (QE 7.3
   ``PW/src/setup.f90:349-356``), with nelup/neldw from the occupations
   decision's ``tot_magnetization`` (``advisors/nbnd.py``'s
   ``band_floors``). The default never falls below these, so this refuses
   a human ``nbnd`` or a human or llm ``extra_bands``: ``nbnd=2`` on 8
   electrons, or 96 bands for LiFePO4 with ``tot_magnetization=16``, whose
   spin-up channel holds 104 electrons, used to pass and stop pw.x after
   the job had queued. pw.x checks only runs with their own SCF loop
   (``lscf``, ``setup.f90:349-358``), but an nscf step needs every occupied
   band too, to place the Fermi level, and a bands step to plot them, so
   this applies to every purpose; the message says pw.x stops only where it
   does. Its ``cause`` leaves the step out, so one count that a dos or band
   task's scf and later step both take, from one ``nbnd``, is one finding,
   in the scf step's words.

5. A user ``ndiag`` whose s x s diagonalization grid cannot distribute
   ``nbnd`` bands (#133), s = isqrt(min(ndiag, ntasks/npool)): pw.x
   aborts at startup when s > nbnd (QE 7.3
   ``Modules/set_para_diag.f90:54-55``), and ScaLAPACK's block layout
   leaves a process column empty for subspace sizes up to (s-1)^2, which
   ELPA rejects and QE does not detect. The subspace never shrinks below
   nbnd, so nbnd > (s-1)^2 rules out both, for every purpose and on
   every profile.

6. A vc-relax ``cell_dofree`` that masks Cartesian components of the
   lattice vectors ('a', 'b', 'c', 'x', 'y', 'z', 'xy', 'xz', 'yz', 'xyz':
   QE 7.3 ``Modules/cell_base.f90:710-830``'s
   ``iforceh(i, j)`` is Cartesian component i of lattice vector j) on a
   cell the magnetic step wrote rotated (``MagneticConfigFacts.frame``,
   ``pw_symmetry.pw_frame``, #140): its x, y and z are no longer the
   uploaded cell's, so the mask would hold other components than the ones
   asked for. Masks of whole lattice vectors ('fixa', 'fixb', 'fixc', the
   'epitaxial' forms), 'all' and 'shape' keep their meaning; '2Dxy' and
   '2Dshape' are left to the 2D-frame rule, since they act on a and b in
   the plane they span once that plane is xy, however it got there.

7. A ``tot_magnetization`` on a collinear spin-polarized band task's bands
   step (#118). Any ``tot_magnetization`` gives pw.x two Fermi energies
   (QE 7.3 ``PW/src/input.f90:758``), which the scf writes to its save and
   the bands step reads from it whatever its own input says
   (``PW/src/setup.f90:178-201``); bands.x then stops with 'The bands code
   with constrained magnetization has not been tested'
   (``PP/src/bands.f90:114-116``), after both pw.x steps have run. The band
   task's scf derives no compensated moment (``BAND_SCF_PROTOCOL``,
   ``service/_step_protocol.py``), so this refuses a requested one, checked
   on the bands step's occupations, which carry the scf's moment. A
   noncollinear run takes no ``tot_magnetization``.

8. A band path with more k-point/spin pairs than pw.x holds, on the bands
   step that runs every point of it: npk = 40000 (QE 7.3
   ``Modules/parameters.f90:16``), counted after a collinear run doubles the
   list (``PW/src/set_kup_and_kdw.f90:35``, ``setup.f90:640``). The default
   ``k_path_distance`` never comes near it; only a distance near its lower
   bound on a cell with lattice vectors shorter than about 1.4 Angstrom can.

**The phonon tasks' rules** (#215). ``with_phonon_findings`` takes the
``check_all`` report of a phonon task's first step, the scf, relax or
vc-relax whose save ph.x reads, and adds the ``Blocked`` records of the
phonon steps and rules 9-17. Unless a rule names a task, it applies to all
three and reads the first step's occupations, moment, boundary and Hubbard
settings and its is_metal fact. Where a phonon rule and a ``check_all`` rule
share a root cause, only the phonon finding is kept (rules 11, 16 and 17),
since the other's advice does not help a phonon run.

9. A Hubbard U written with projectors other than atomic: ph.x computes
   phonons with a Hubbard U (DFPT+U) only on atomic ones (QE 7.3
   ``PHonon/PH/phq_readin.f90:766-767``). A task cannot switch them on its
   own, since a structure relaxed with one projector type is not at
   equilibrium with the other, so ``hubbard_projectors=atomic`` is the
   remedy, and so is no U.

10. Spin-orbit coupling with a Hubbard U, with or without magnetic moments:
    ph.x's DFPT+U arrays and projections hold one spinor component (QE 7.3
    ``PHonon/PH/allocate_phq.f90:166-167``, ``dnsq_scf.f90:130``). QE 7.5
    stops on a magnetic noncollinear run (``phq_readin.f90:777-778``);
    without moments, and in 7.3 with them, ph.x would run and give wrong
    phonons.

11. A written cell with vacuum along a, b and c, a molecule or cluster in a
    box, whatever ``isolation``: ph.x implements no nonperiodic boundary
    (``PHonon/PH/phonon.f90:36-41``). Under 'isolated', QE 7.3 restores only
    the 2D flag from the save (``PW/src/pw_restart_new.f90:1341-1345``), so
    the box gets the phonons of a periodic array of copies, and 7.5 applies
    Martyna-Tuckerman to the response Hartree potential only; under any
    other isolation ph.x computes such an array by design, whose phonons
    include the interactions between the copies, while a molecule has no
    phonon dispersion. A molecule's modes need a Gamma-only calculation
    (ph.x at Gamma, then dynmat.x with ``asr='zero-dim'``), which these
    tasks do not do, so there is no remedy. This replaces
    ``boundary.isolated_forbids_vc_relax`` and, for a 2D ``cell_dofree``,
    ``relax.two_d_cell_dofree_needs_xy_frame`` in vc-relax-phonon, whose
    advice on a box, the relax task, does not help a phonon run, and
    ``boundary.slab_unsuited_to_2d_truncation`` under 'slab', whose remedy,
    isolation=periodic, is refused here too. On a cell without that vacuum
    the vacuum rule refuses 'isolated' already, offering isolation=periodic.

12. A ``tot_magnetization`` on a collinear run with smearing or tetrahedra:
    the moment gives the scf two Fermi energies (QE 7.3
    ``PW/src/input.f90:758``), which ph.x refuses unless the occupations are
    fixed (``phq_readin.f90:856-858``). Fixed occupations are offered only
    for an integer moment of the electron count's parity, which rule 2
    needs. Where rule 2 refuses a requested moment on fixed occupations (not
    an integer, or not of that parity), its remedy, smearing, would keep the
    moment, so in a phonon task it unsets the moment too, unless rule 17
    replaces that finding.

13. A ``q_grid`` the q record refuses as breaking symmetry
    (``advisors/q_sampling.py``): more than one division along a vacuum axis,
    a mesh an operation pw.x keeps does not map onto itself, on which ph.x
    stops, or unequal counts on two axes an operation mixes, which the phonon
    k-mesh raised against it can break. A mesh built from a spacing that is
    not symmetric is a ``Blocked`` q record instead: no q setting fixes it.

14. A q-mesh beyond q2r.x's limits: it reads at most 1024 dynamical
    matrices, one per irreducible q-point, and 1024 divisions along each
    axis (``PHonon/PH/do_q2r.f90:135-139``). The q record refuses a mesh
    with more irreducible q-points, and a mesh built from a spacing with more
    divisions or more than 49152 points, which always has more; a ``q_grid``
    is held within the divisions and the points at input.

15. vc-relax-phonon on a fragile cell (``advisors/fft_grid.py``): ph.x stops
    on a dense FFT grid an operation pw.x keeps does not map onto itself
    (``PHonon/PH/phq_setup.f90:211-212``), which pw.x's own grid can be on a
    fragile cell, and a vc-relax's final scf rebuilds pw.x's own grid for the
    relaxed cell, dropping the nr1-nr3 the scf and relax first steps write
    for ph.x (``PW/src/run_pwscf.f90:404-405``). No setting keeps them
    through that scf, so there is no remedy: the message names relax-phonon,
    which keeps the cell and writes the grid, and the vc-relax task followed
    by the phonon task on the relaxed structure. ``cell_dofree``, the setting
    of the variable-cell relaxation, is the field the finding concerns. No
    value of it lifts the refusal, but every finding except
    ``advice.blocked`` names a setting, the control the Workbench shows it
    at.

16. ``fix_bottom_layers`` in relax-phonon or vc-relax-phonon: pinned atoms
    keep their forces, and DFPT takes second derivatives at an equilibrium,
    where every force is zero. This replaces the slab rules of
    ``fix_bottom_layers`` (``relax.fix_bottom_layers_needs_slab``,
    ``relax.fix_bottom_layers_exceeds_layers``), whose remedy, unsetting it,
    is the same.

17. A first step on smearing or ``tetrahedra_opt``, or on fixed occupations
    it cannot take, whose composition is not all-metallic
    (``analysis.is_metal.all_metallic``), unless the user set
    ``is_metal=metal``: the material may be an insulator, which ph.x treats
    as a metal on smearing or tetrahedra. It computes the dielectric constant
    and the Born effective charges, from which q2r.x and matdyn.x build a
    polar insulator's LO-TO splitting, only with fixed occupations (QE 7.3
    ``PHonon/PH/prepare_q.f90:141-160``), and at q = 0 it shifts the Fermi
    energy by the induced charge divided by the density of states at the
    Fermi energy (``PHonon/PH/solve_linter.f90:228``, ``:430-437``;
    ``LR_Modules/efermi_shift.f90:98-99``), which with smearing is nearly
    zero when the Fermi energy lies in a gap, so the response can diverge at
    Gamma. The classifier's threshold is set to miss few metals, for the
    k-point sampling a missed metal would undersample, so it calls many
    insulators metals, and the heuristic never says non_metal (#164): a
    classified or undecided is_metal is no answer here, and nor is the
    user's non_metal on a run it leaves on smearing. So the run passes on
    fixed occupations or as a confirmed metal. Besides ``is_metal=metal`` the
    finding offers what puts an insulator on fixed occupations by the
    occupations rule (``advisors/occupations.py``'s
    ``fixed_occupations_run``): ``is_metal=non_metal``, or
    ``occupations=fixed`` where the request sets the occupations, which
    is_metal does not change. A collinear spin-polarized run takes them only
    with an integer ``tot_magnetization`` of the electron count's parity, the
    request's or the 0 of a compensated ordering: without one the message
    names ``tot_magnetization``, and adds ``is_magnetic=non_magnetic`` for a
    material without moments where that answer gives fixed occupations -- the
    spin polarization follows the is_magnetic fact, no Hubbard U acts on an
    odd d or f count, which keeps a run spin-polarized whatever is_magnetic
    says (``advisors/magnetic_config.py``'s ``unpolarized_if_non_magnetic``),
    and the count without spin polarization is even. Without spin
    polarization an odd electron count leaves a band half filled, as in a
    metal, and a magnetic insulator with it needs spin polarization and, on a
    collinear run, its moment, which the message names. A requested
    ``occupations=fixed`` the run cannot take for these reasons is refused
    here too, in place of rules 2 and 3, whose remedy, smearing, needs a
    confirmed metal on such a composition: the metal's remedy is then
    ``is_metal=metal`` with ``occupations=smearing``, and with a requested
    moment unset, which rule 12 refuses on smearing. An occurrence names only
    the settings its message asks for.

Other inputs ph.x refuses or cannot handle need no rule, since no request
reaches them: a hybrid or meta-GGA functional (every table's functional is
LDA, PBE or PBEsol, and pw.x takes the functional from the
pseudopotentials), TS or MBD dispersion (D3(BJ) is the only method),
Bloechl tetrahedra (``tetrahedra_opt`` is the only tetrahedron method) and
PAW in a noncollinear magnetic run (every fully relativistic table is
norm-conserving). Tests guard each.

**Findings, not prose (#151).** Every refusal is a ``Finding``: a code
from ``FINDING_CATALOGUE``, the setting keys it concerns (``fields``, as
``capabilities()`` names them), a user-facing ``message`` and its
``remedies``, each a complete override patch that resolves it (a ``None``
value clears that override). A catalogue entry fixes a code's fields and
remedies; each rule fills in the message of its occurrence, and drops a
remedy that would not hold for it (cell_dofree=all for a cell with vacuum,
which it would relax too) or that another task needs (rule 2's smearing with
the moment unset, a phonon task's), and rule 17 a field its message does not
ask for. A value only the user can choose (a
``tot_magnetization``) is named in the message, never guessed in a remedy.
A ``Blocked`` chain reaches the gate as ``advice.blocked`` with its root
cause and no remedy: a refusal that needs one must be a named rule here.
``CheckReport`` keeps one finding per root cause, however many fields or
steps share it.

**Everything else in the design doc's "constraint check table"** is
not a rule here. Memory overflow is a warning, not a block
(``job.memory_exceeds_node`` in ``advisors/job_resources.py``), like a
node count above the partition's ceiling: the memory figure is an
estimate. A disordered structure never gets here: advice refuses it
first (``inputs.structure.require_ordered``, #224). The tri-tier
override-conflict rules are left as a gap. This module's job is to
establish *that* single gate exists and works for what is checkable
today, not to enumerate every rule up front.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Literal

from pymatgen.core import Structure

from goldilocks_core.advisors.boundary import BoundaryFacts
from goldilocks_core.advisors.electron_count import ElectronCountDecision
from goldilocks_core.advisors.fft_grid import FftGridDecision
from goldilocks_core.advisors.hubbard_u import HubbardUDecision
from goldilocks_core.advisors.job_resources import JobDecision
from goldilocks_core.advisors.magnetic_config import (
    MagneticConfigFacts,
    unpolarized_if_non_magnetic,
)
from goldilocks_core.advisors.nbnd import NbndDecision, band_floors
from goldilocks_core.advisors.occupations import (
    OccupationsDecision,
    fixed_occupations_run,
    whole_spin_channels,
)
from goldilocks_core.advisors.parallelisation import (
    ParallelisationDecision,
    diag_grid_side,
)
from goldilocks_core.advisors.q_sampling import QSamplingDecision
from goldilocks_core.advisors.relax import RelaxOptions, VcRelaxOptions, wire_period
from goldilocks_core.advisors.vdw_method import VdwFacts
from goldilocks_core.analysis.geometry import (
    LatticeAxis,
    ab_in_xy_plane,
    slab_layers,
    two_d_truncation_obstacles,
    vacuum_axes,
)
from goldilocks_core.analysis.is_metal import Metallicity, all_metallic
from goldilocks_core.functionals import D3BJ_FUNCTIONALS, has_d3bj_parameters
from goldilocks_core.plan import SCF_LIKE_PURPOSES
from goldilocks_core.resolution import Blocked, FieldState

_TWO_D_CELL_DOFREE = frozenset({"2Dxy", "2Dshape"})
"""``cell_dofree`` values that move only the x and y components of a and b."""
_CARTESIAN_CELL_DOFREE = frozenset(
    {"a", "b", "c", "x", "y", "z", "xy", "xz", "yz", "xyz"}
)
"""``cell_dofree`` values that hold or free single Cartesian components of
the lattice vectors (rule 6 of the module docstring)."""


@dataclass(frozen=True, slots=True)
class Finding:
    """One reason the gate refuses a request (module docstring). ``code`` is
    a stable ``FINDING_CATALOGUE`` key a caller may match on; ``fields`` are
    the ``capabilities()`` setting keys it concerns; ``message`` is the text
    a user reads, with the occurrence's values filled in; ``summary`` states
    the decision it asks for in at most 200 characters, about four lines of
    the Workbench's Bundle card, which shows ``message`` on request (#223);
    each of
    ``remedies`` is a complete override patch that resolves it, a ``None``
    value clearing that override. ``cause`` states the occurrence's root
    cause where ``message`` words it for one step of a task (rule 4), so
    that ``CheckReport`` keeps it once; it is neither compared nor
    published."""

    code: str
    message: str
    summary: str
    fields: tuple[str, ...] = ()
    remedies: tuple[dict[str, object], ...] = ()
    cause: str | None = field(default=None, compare=False)

    def to_document(self) -> dict[str, object]:
        """The JSON every transport returns for this finding."""
        return {
            "code": self.code,
            "fields": list(self.fields),
            "message": self.message,
            "remedies": [dict(remedy) for remedy in self.remedies],
            "summary": self.summary,
        }


_SMEARING = {"occupations": "smearing"}
_UNPINNED = {"tot_magnetization": None}
_UNPINNED_SMEARING = {**_SMEARING, **_UNPINNED}
"""Smearing without the requested moment, which ph.x refuses there (rule 12
of the module docstring)."""
_PERIODIC = {"isolation": "periodic"}
_PW_X_MAX_KPOINTS = 40000
"""pw.x's npk, the most k-points it holds (rule 8 of the module docstring)."""
_MOMENT_FIELDS = ("occupations", "tot_magnetization")

_BLOCKED = Finding(
    code="advice.blocked",
    message=(
        "A decision the input needs could not be made; the message gives the "
        "root cause."
    ),
    summary=(
        "A decision the input files need could not be made; the details name its "
        "root cause."
    ),
)
_MISSING_TOT_MAGNETIZATION = Finding(
    code="occupations.fixed_needs_tot_magnetization",
    message=(
        "occupations=fixed on a collinear spin-polarized run needs an integer "
        "tot_magnetization of the electron count's parity, and none was set or "
        "derived. Set occupations=smearing, or set tot_magnetization."
    ),
    summary=(
        "Fixed occupations on this spin-polarized run need an integer "
        "tot_magnetization: set one, or switch occupations to smearing."
    ),
    fields=_MOMENT_FIELDS,
    remedies=(_SMEARING,),
)
_NON_INTEGER_TOT_MAGNETIZATION = Finding(
    code="occupations.fixed_needs_integer_tot_magnetization",
    message=(
        "occupations=fixed on a collinear spin-polarized run needs an integer "
        "tot_magnetization."
    ),
    summary=(
        "Fixed occupations on this spin-polarized run need an integer "
        "tot_magnetization: set an integer, or switch occupations to smearing."
    ),
    fields=_MOMENT_FIELDS,
    remedies=(_SMEARING, _UNPINNED_SMEARING),
)
"""Smearing keeps the requested moment, and in a phonon task, where ph.x
refuses a moment on smearing, it is unset too (rule 12 of the module
docstring)."""
_TOT_MAGNETIZATION_PARITY = Finding(
    code="occupations.fixed_tot_magnetization_parity",
    message=(
        "occupations=fixed needs tot_magnetization to share parity with the "
        "electron count."
    ),
    summary=(
        "Fixed occupations need tot_magnetization to share the electron count's "
        "parity: change it, or switch occupations to smearing."
    ),
    fields=_MOMENT_FIELDS,
    remedies=(_SMEARING, _UNPINNED_SMEARING),
)
"""The remedies of ``_NON_INTEGER_TOT_MAGNETIZATION``, for the same reason."""
_ODD_ELECTRON_COUNT = Finding(
    code="occupations.fixed_needs_even_electron_count",
    message=(
        "occupations=fixed without spin polarization needs an even electron count."
    ),
    summary=(
        "Fixed occupations without spin polarization need an even electron count: "
        "turn spin polarization on, or switch occupations to smearing."
    ),
    fields=("occupations", "spin_polarized"),
    remedies=(_SMEARING, {"spin_polarized": True, **_SMEARING}),
)
_TOO_FEW_BANDS = Finding(
    code="nbnd.too_few_bands",
    message="nbnd is below the bands the electrons of each spin channel fill.",
    summary=(
        "nbnd is too small to hold the electrons of each spin channel: raise nbnd "
        "or extra_bands."
    ),
    fields=("nbnd", "extra_bands"),
    remedies=({"nbnd": None, "extra_bands": None},),
)
_BANDS_X_TOT_MAGNETIZATION = Finding(
    code="occupations.bands_x_refuses_tot_magnetization",
    message=(
        "A band task cannot pin tot_magnetization on a collinear spin-polarized "
        "run: bands.x stops on the two Fermi energies it gives."
    ),
    summary=(
        "A band task cannot pin tot_magnetization on this spin-polarized run, "
        "since bands.x stops on the two Fermi energies it gives: unset "
        "tot_magnetization."
    ),
    fields=_MOMENT_FIELDS,
    remedies=({**_SMEARING, "tot_magnetization": None},),
)
"""Both keys: clearing the moment alone would leave an explicit
occupations=fixed with no moment to pin."""
_TOO_MANY_KPOINTS = Finding(
    code="k_path.too_many_kpoints",
    message="The band path holds more k-points than pw.x accepts.",
    summary=(
        "The band path holds more k-points than pw.x accepts: raise k_path_distance."
    ),
    fields=("k_path_distance",),
    remedies=({"k_path_distance": None},),
)
_NPOOL = Finding(
    code="parallelisation.npool_does_not_divide_ntasks",
    message="npool must divide ntasks.",
    summary=(
        "npool must divide the job's task count: choose a divisor, or leave npool "
        "automatic."
    ),
    fields=("npool", "ntasks"),
    remedies=({"npool": None},),
)
_NDIAG = Finding(
    code="parallelisation.ndiag_grid_too_large",
    message="ndiag gives a diagonalization grid too large for nbnd.",
    summary=(
        "ndiag gives a diagonalization grid too large for nbnd: lower ndiag, or "
        "leave it automatic."
    ),
    fields=("ndiag", "nbnd"),
    remedies=({"ndiag": None},),
)
_VC_RELAX_ION_DYNAMICS = Finding(
    code="relax.vc_relax_needs_bfgs",
    message="vc-relax is generated only with ion_dynamics=bfgs.",
    summary=(
        "vc-relax is generated only with ion_dynamics=bfgs: set ion_dynamics to bfgs."
    ),
    fields=("ion_dynamics",),
    remedies=({"ion_dynamics": "bfgs"},),
)
_ISOLATED_WITHOUT_VACUUM = Finding(
    code="boundary.isolated_needs_vacuum",
    message=(
        "isolation=isolated needs vacuum along a, b and c of the cell to be written."
    ),
    summary=(
        "isolation=isolated needs vacuum along a, b and c of the written cell: "
        "choose another isolation, or upload the structure in a box."
    ),
    fields=("isolation",),
    remedies=(_PERIODIC,),
)
_SLAB_UNSUITED = Finding(
    code="boundary.slab_unsuited_to_2d_truncation",
    message=(
        "isolation=slab needs a cell that suits Quantum ESPRESSO's 2D Coulomb "
        "truncation."
    ),
    summary=(
        "isolation=slab needs a cell that suits Quantum ESPRESSO's 2D Coulomb "
        "truncation, which this one does not: choose another isolation."
    ),
    fields=("isolation",),
    remedies=(_PERIODIC,),
)
_ISOLATED_VC_RELAX = Finding(
    code="boundary.isolated_forbids_vc_relax",
    message=(
        "vc-relax cannot relax the cell with isolation=isolated "
        "(Martyna-Tuckerman): pw.x computes no stress for an isolated system, so "
        "the input cell would be reported as converged. Use the relax task for a "
        "molecule or cluster in a box, or set isolation=periodic for a periodic "
        "structure."
    ),
    summary=(
        "vc-relax cannot relax the cell of an isolated system, since pw.x "
        "computes no stress for it: use the relax task, or isolation=periodic for "
        "a periodic structure."
    ),
    fields=("isolation",),
)
"""No remedy: only a cell with vacuum along a, b and c may be isolated (the
vacuum rule refuses any other, offering isolation=periodic), and for such a
molecule or cluster the fix is the relax task, which no override expresses.
isolation=periodic would pass, but vc-relax would then move the vacuum
box."""
_SLAB_VC_RELAX_CELL_DOFREE = Finding(
    code="relax.slab_vc_relax_needs_2d_cell_dofree",
    message="vc-relax with isolation=slab needs a 2D cell_dofree.",
    summary=(
        "vc-relax of a slab needs a 2D cell_dofree, which keeps the vacuum fixed: "
        "set a 2D cell_dofree, or choose another isolation."
    ),
    fields=("cell_dofree", "isolation"),
    remedies=({"cell_dofree": "2Dxy"}, {**_PERIODIC, "cell_dofree": None}),
)
"""The periodic remedy also clears cell_dofree, so that the slab's default
'2Dxy' holds c, which is the vacuum, fixed: an explicit 'all' kept under
isolation=periodic would pass, but relax the vacuum. Both remedies hold only
on a slab with its vacuum along c in the xy frame, so the rule leaves any
other cell to the boundary rule's isolation=periodic."""
_TWO_D_CELL_DOFREE_FRAME = Finding(
    code="relax.two_d_cell_dofree_needs_xy_frame",
    message="A 2D cell_dofree needs a and b in the Cartesian xy plane.",
    summary=(
        "A 2D cell_dofree needs a and b in the Cartesian xy plane, which this "
        "written cell does not have: choose another cell_dofree."
    ),
    fields=("cell_dofree",),
    remedies=({"cell_dofree": "all"},),
)
"""The remedy holds for a cell without vacuum only: with vacuum, 'all'
would relax the vacuum too, so the rule offers none there and names what
holds the vacuum fixed instead."""
_CARTESIAN_CELL_DOFREE_ROTATED = Finding(
    code="relax.cartesian_cell_dofree_on_rotated_cell",
    message=(
        "A cell_dofree that masks Cartesian components needs the cell written "
        "unrotated."
    ),
    summary=(
        "This cell_dofree masks Cartesian components, which needs the cell "
        "written unrotated: choose a cell_dofree without Cartesian masks."
    ),
    fields=("cell_dofree",),
    remedies=({"cell_dofree": None},),
)
_DISPERSION_FUNCTIONAL = Finding(
    code="vdw.use_vdw_without_d3bj_parameters",
    message="use_vdw=true needs a functional with D3(BJ) parameters.",
    summary=(
        "use_vdw=true needs a functional with D3(BJ) parameters: choose such a "
        "functional, or turn use_vdw off."
    ),
    fields=("use_vdw", "functional"),
    remedies=({"use_vdw": False},),
)
_FIX_BOTTOM_LAYERS_WITHOUT_SLAB = Finding(
    code="relax.fix_bottom_layers_needs_slab",
    message="fix_bottom_layers needs a slab.",
    summary=(
        "fix_bottom_layers needs a slab, which this structure is not: unset "
        "fix_bottom_layers."
    ),
    fields=("fix_bottom_layers",),
    remedies=({"fix_bottom_layers": None},),
)
_FIX_BOTTOM_LAYERS_EXCEEDS = Finding(
    code="relax.fix_bottom_layers_exceeds_layers",
    message="fix_bottom_layers exceeds the atomic layers of the slab.",
    summary=(
        "fix_bottom_layers asks for more layers than the slab has: lower "
        "fix_bottom_layers."
    ),
    fields=("fix_bottom_layers",),
    remedies=({"fix_bottom_layers": None},),
)
_NO_U = {"hubbard_needs_correlation": False}
_PHONON_HUBBARD_PROJECTORS = Finding(
    code="phonon.hubbard_projectors_unsupported",
    message=(
        "The phonon tasks need hubbard_projectors=atomic with a Hubbard U: ph.x "
        "computes phonons with a Hubbard U only for atomic projectors."
    ),
    summary=(
        "ph.x computes phonons with a Hubbard U only for atomic projectors: set "
        "hubbard_projectors to atomic, or run without the U."
    ),
    fields=("hubbard_projectors", "hubbard_needs_correlation"),
    remedies=({"hubbard_projectors": "atomic"}, _NO_U),
)
_PHONON_NONCOLLINEAR_HUBBARD = Finding(
    code="phonon.noncollinear_hubbard_unsupported",
    message=(
        "The phonon tasks cannot combine spin_orbit_coupling with a Hubbard U: "
        "ph.x computes phonons with a Hubbard U for collinear spins only."
    ),
    summary=(
        "ph.x computes phonons with a Hubbard U for collinear spins only: turn "
        "spin-orbit coupling off, or run without the U."
    ),
    fields=("spin_orbit_coupling", "hubbard_needs_correlation"),
    remedies=({"spin_orbit_coupling": False}, _NO_U),
)
_MOLECULAR_VIBRATIONS = (
    "A molecule's vibrations need a Gamma-only calculation, ph.x at Gamma and "
    "then dynmat.x with asr='zero-dim', which the phonon tasks do not do."
)
_PHONON_ISOLATED = Finding(
    code="phonon.isolated_boundary_unsupported",
    message=(
        "isolation=isolated writes Martyna-Tuckerman, which ph.x does not "
        "implement: Quantum ESPRESSO 7.3's ph.x drops it, treating the molecule or "
        "cluster in the box as a periodic array of copies, and 7.5's applies it "
        f"only in part. {_MOLECULAR_VIBRATIONS}"
    ),
    summary=(
        "The phonon tasks cannot treat an isolated molecule or cluster: ph.x does "
        "not implement its boundary. A molecule's vibrations need a Gamma-only "
        "calculation."
    ),
    fields=("isolation",),
)
"""A molecule or cluster in a box, with the message of isolation=isolated;
under any other isolation the rule words its own. No remedy: no isolation
or other setting gives ph.x a molecule's vibrations (rule 11 of the module
docstring)."""
_PHONON_PINNED_MOMENT = Finding(
    code="phonon.pinned_moment_with_smearing",
    message=(
        "The phonon tasks cannot pin tot_magnetization on smearing or tetrahedra: "
        "ph.x refuses the two Fermi energies it gives there."
    ),
    summary=(
        "ph.x refuses a pinned tot_magnetization on smearing or tetrahedra: unset "
        "tot_magnetization, or use fixed occupations."
    ),
    fields=_MOMENT_FIELDS,
    remedies=(_UNPINNED, {"occupations": "fixed"}),
)
"""occupations=fixed only for a moment fixed occupations run with (rule 12
of the module docstring)."""
_PHONON_Q_GRID_SYMMETRY = Finding(
    code="phonon.q_grid_breaks_symmetry",
    message=(
        "q_grid must be a mesh every symmetry operation maps onto itself, with "
        "one division along each vacuum axis and equal counts on the axes an "
        "operation mixes."
    ),
    summary=(
        "q_grid must be a mesh every symmetry operation maps onto itself: change "
        "q_grid, or set q_distance instead."
    ),
    fields=("q_grid",),
    remedies=({"q_grid": None},),
)
_PHONON_TOO_MANY_Q_POINTS = Finding(
    code="phonon.too_many_q_points",
    message=(
        "The q-mesh is beyond q2r.x's limits: at most 1024 divisions along each "
        "axis and 1024 irreducible q-points."
    ),
    summary=(
        "The q-mesh exceeds q2r.x's limits, 1024 divisions per axis and 1024 "
        "irreducible q-points: use a coarser q_grid or a larger q_distance."
    ),
    fields=("q_grid", "q_distance"),
    remedies=({"q_grid": None, "q_distance": None},),
)
_PHONON_VC_RELAX_FFT_GRID = Finding(
    code="phonon.vc_relax_fft_grid_unsupported",
    message=(
        "vc-relax-phonon cannot run on a cell whose FFT grid, rebuilt by the "
        "vc-relax for the relaxed cell, ph.x can refuse; use relax-phonon."
    ),
    summary=(
        "vc-relax-phonon cannot run on this cell: the vc-relax rebuilds an FFT "
        "grid that ph.x can refuse. Use the relax-phonon task."
    ),
    fields=("cell_dofree",),
)
"""No remedy: no setting keeps a written grid through a vc-relax's final scf
(rule 15 of the module docstring)."""
_PHONON_FIX_BOTTOM_LAYERS = Finding(
    code="phonon.fix_bottom_layers_unsupported",
    message="The phonon tasks cannot pin atoms with fix_bottom_layers.",
    summary=(
        "The phonon tasks cannot pin atoms with fix_bottom_layers: unset "
        "fix_bottom_layers."
    ),
    fields=("fix_bottom_layers",),
    remedies=({"fix_bottom_layers": None},),
)
_NON_METAL = {"is_metal": "non_metal"}
_FIXED = {"occupations": "fixed"}
_NON_MAGNETIC = {"is_magnetic": "non_magnetic"}
_METAL = {"is_metal": "metal"}
_METAL_ON_SMEARING = {**_SMEARING, **_METAL}
_UNPINNED_METAL_ON_SMEARING = {**_UNPINNED_SMEARING, **_METAL}
_PHONON_METALLICITY_UNCONFIRMED = Finding(
    code="phonon.metallicity_unconfirmed",
    message=(
        "The phonon tasks run a composition that is not all-metallic on smearing "
        "or tetrahedra, which ph.x treats as a metal, only as a confirmed metal: an "
        "insulator gets no LO-TO splitting there, and its response can diverge at "
        "Gamma. For a metal set is_metal=metal; put an insulator on fixed "
        "occupations."
    ),
    summary=(
        "Confirm whether this structure is a metal: its composition is not "
        "all-metallic, and an insulator run on smearing or tetrahedra, as ph.x "
        "runs a metal, loses its LO-TO splitting."
    ),
    fields=(
        "is_metal",
        "occupations",
        "is_magnetic",
        "spin_polarized",
        "tot_magnetization",
    ),
    remedies=(
        _NON_METAL,
        {**_NON_METAL, **_NON_MAGNETIC},
        _FIXED,
        {**_FIXED, **_NON_MAGNETIC},
        _METAL,
        _METAL_ON_SMEARING,
        _UNPINNED_METAL_ON_SMEARING,
    ),
)
"""Only the user can say whether the material is an insulator, and an
occurrence offers the patches that put one on fixed occupations for it, with
the patch that confirms a metal: is_metal=metal, with smearing in place of a
requested occupations=fixed the run cannot take, and the requested moment
unset there. It names only the settings its message asks for (rule 17 of the
module docstring)."""
_PH_X_TREATS_SMEARING_AS_METAL = (
    "ph.x treats a run on smearing or tetrahedra as a metal: it computes the "
    "dielectric constant and the Born effective charges, which give a polar "
    "insulator its LO-TO splitting, only with fixed occupations, and at q = 0 it "
    "shifts the Fermi energy by the induced charge divided by the density of "
    "states at the Fermi energy, which with smearing is nearly zero when the Fermi "
    "energy lies in a gap, so an insulator's response can diverge at Gamma."
)
_CLASSIFIER_CALLS_INSULATORS_METALS = (
    "The metallicity classifier is tuned to miss few metals, which k-point sampling "
    "needs, so it calls many insulators metals, and composition alone cannot tell "
    "them apart."
)
_FIXED_NEEDS_MOMENT = (
    "fixed occupations on a collinear spin-polarized run need an integer "
    "tot_magnetization of the electron count's parity"
)
_ODD_WITHOUT_SPIN = (
    "without spin polarization fixed occupations cannot fill its odd electron "
    "count, which leaves a band half filled, as in a metal"
)

FINDING_CATALOGUE = (
    _BLOCKED,
    _MISSING_TOT_MAGNETIZATION,
    _NON_INTEGER_TOT_MAGNETIZATION,
    _TOT_MAGNETIZATION_PARITY,
    _ODD_ELECTRON_COUNT,
    _TOO_FEW_BANDS,
    _BANDS_X_TOT_MAGNETIZATION,
    _TOO_MANY_KPOINTS,
    _VC_RELAX_ION_DYNAMICS,
    _ISOLATED_WITHOUT_VACUUM,
    _SLAB_UNSUITED,
    _ISOLATED_VC_RELAX,
    _SLAB_VC_RELAX_CELL_DOFREE,
    _TWO_D_CELL_DOFREE_FRAME,
    _CARTESIAN_CELL_DOFREE_ROTATED,
    _DISPERSION_FUNCTIONAL,
    _FIX_BOTTOM_LAYERS_WITHOUT_SLAB,
    _FIX_BOTTOM_LAYERS_EXCEEDS,
    _NPOOL,
    _NDIAG,
    _PHONON_HUBBARD_PROJECTORS,
    _PHONON_NONCOLLINEAR_HUBBARD,
    _PHONON_ISOLATED,
    _PHONON_PINNED_MOMENT,
    _PHONON_Q_GRID_SYMMETRY,
    _PHONON_TOO_MANY_Q_POINTS,
    _PHONON_VC_RELAX_FFT_GRID,
    _PHONON_FIX_BOTTOM_LAYERS,
    _PHONON_METALLICITY_UNCONFIRMED,
)
"""Every finding the gate can return, with its code's fields and remedies
and a generic message; a rule returns its entry with the occurrence's
message, less any remedy that would not hold for it (module docstring)."""

_REPLACED_BY_PHONON = {
    _PHONON_ISOLATED.code: (
        _ISOLATED_VC_RELAX.code,
        _TWO_D_CELL_DOFREE_FRAME.code,
        _SLAB_UNSUITED.code,
    ),
    _PHONON_FIX_BOTTOM_LAYERS.code: (
        _FIX_BOTTOM_LAYERS_WITHOUT_SLAB.code,
        _FIX_BOTTOM_LAYERS_EXCEEDS.code,
    ),
    _PHONON_METALLICITY_UNCONFIRMED.code: (
        _MISSING_TOT_MAGNETIZATION.code,
        _NON_INTEGER_TOT_MAGNETIZATION.code,
        _TOT_MAGNETIZATION_PARITY.code,
        _ODD_ELECTRON_COUNT.code,
    ),
}
"""The ``check_all`` findings a phonon finding replaces, for the same root
cause (rules 11, 16 and 17 of the module docstring)."""
_KEEPING_THE_MOMENT = frozenset(
    {_NON_INTEGER_TOT_MAGNETIZATION.code, _TOT_MAGNETIZATION_PARITY.code}
)
"""The ``check_all`` findings of a requested moment fixed occupations cannot
take, whose smearing remedy keeps it (rule 12 of the module docstring)."""


@dataclass(frozen=True, slots=True)
class CheckReport:
    """The gate's verdict: ``blocking`` holds one finding per root cause, in
    first-seen order. Findings with the same code and cause -- the
    ``cause`` a finding states, else its message -- are kept once: many
    blocked fields can share one upstream cause, and one band count that
    two pw.x steps of a task take falls below the same floors in each."""

    blocking: tuple[Finding, ...] = ()

    def __post_init__(self) -> None:
        unique: dict[tuple[str, str], Finding] = {}
        for finding in self.blocking:
            cause = finding.message if finding.cause is None else finding.cause
            unique.setdefault((finding.code, cause), finding)
        object.__setattr__(self, "blocking", tuple(unique.values()))

    @property
    def ok(self) -> bool:
        return not self.blocking


def collect_blocked(*field_states: FieldState[object]) -> tuple[Finding, ...]:
    """An ``advice.blocked`` finding naming each ``Blocked`` field state's
    root cause, in the order given.

    ``Unavailable`` and ``Resolved`` states are not blocking on their
    own -- an advisor that could not tell, or a caller that never
    supplied a given field at all, is not the same as an upstream
    failure. Only genuine ``Blocked`` propagation reaches here.
    """
    return tuple(
        replace(_BLOCKED, message=state.root_cause())
        for state in field_states
        if isinstance(state, Blocked)
    )


def check_all(
    *field_states: FieldState[object],
    occupations: FieldState[OccupationsDecision] | None = None,
    magnetic: FieldState[MagneticConfigFacts] | None = None,
    electron_count: FieldState[ElectronCountDecision] | None = None,
    relax: FieldState[RelaxOptions | VcRelaxOptions] | None = None,
    boundary: FieldState[BoundaryFacts] | None = None,
    vdw: FieldState[VdwFacts] | None = None,
    functional: FieldState[str] | None = None,
    job: FieldState[JobDecision] | None = None,
    parallel: FieldState[ParallelisationDecision] | None = None,
    nbnd: FieldState[NbndDecision] | None = None,
    purpose: str = "scf",
) -> CheckReport:
    """The single hard-fail gate.

    ``field_states`` is every ``FieldState`` a caller has assembled so
    far (from any advisor) -- any that are ``Blocked`` land in
    ``report.blocking`` via ``collect_blocked``. ``occupations``/
    ``magnetic``/``electron_count``/``relax``/``boundary``/``vdw``/
    ``functional``/``job``/``parallel``/``nbnd``/``purpose``
    additionally opt into the named cross-parameter rules this module
    implements; passing them here also folds them into the generic
    ``Blocked`` scan, so a caller does not need to repeat them in
    ``field_states`` as well.

    Each rule returns its finding or ``None``; a new rule is one more
    entry in ``rule_findings`` and one in ``FINDING_CATALOGUE``.
    """
    optional = tuple(
        s
        for s in (
            occupations,
            magnetic,
            electron_count,
            relax,
            boundary,
            vdw,
            functional,
            job,
            parallel,
            nbnd,
        )
        if s is not None
    )
    rule_findings = (
        _fixed_occupations_needs_integer_moment(
            occupations, magnetic, electron_count, purpose
        ),
        _fixed_occupations_needs_even_electron_count(
            occupations, magnetic, electron_count, purpose
        ),
        _nbnd_holds_every_electron(
            nbnd, occupations, magnetic, electron_count, purpose
        ),
        _bands_x_refuses_tot_magnetization(occupations, magnetic, purpose),
        _band_path_within_pw_x_k_points(parallel, purpose),
        _vc_relax_requires_bfgs_ion_dynamics(relax, purpose),
        _isolation_matches_written_cell(boundary, magnetic),
        _vc_relax_forbids_isolated_boundary(boundary, purpose),
        _slab_vc_relax_needs_2d_cell_dofree(boundary, relax, magnetic),
        _two_d_cell_dofree_needs_xy_frame(relax, magnetic),
        _cartesian_cell_dofree_needs_unrotated_cell(relax, magnetic),
        _dispersion_needs_parameterised_functional(vdw, functional),
        _fix_bottom_layers_requires_slab(relax, magnetic),
        _npool_must_divide_ntasks(job, parallel),
        _ndiag_grid_must_distribute_bands(job, parallel, nbnd),
    )
    return CheckReport(
        blocking=(
            *collect_blocked(*field_states, *optional),
            *(finding for finding in rule_findings if finding is not None),
        )
    )


def with_phonon_findings(
    report: CheckReport,
    *field_states: FieldState[object],
    purpose: Literal["scf", "relax", "vc-relax"],
    occupations: FieldState[OccupationsDecision] | None = None,
    is_metal: FieldState[Metallicity] | None = None,
    electron_count: FieldState[ElectronCountDecision] | None = None,
    magnetic: FieldState[MagneticConfigFacts] | None = None,
    boundary: FieldState[BoundaryFacts] | None = None,
    relax: FieldState[RelaxOptions | VcRelaxOptions] | None = None,
    hubbard: FieldState[HubbardUDecision] | None = None,
    q_sampling: FieldState[QSamplingDecision] | None = None,
    fft_grid: FieldState[FftGridDecision] | None = None,
) -> CheckReport:
    """The gate of a phonon task: ``report``, the ``check_all`` report of its
    first step (``purpose``, the scf, relax or vc-relax ph.x reads), with the
    phonon tasks' rules added (rules 9-17 of the module docstring).

    ``field_states`` are the phonon steps' records; any that are ``Blocked``
    land in the report through ``collect_blocked``. The named states opt
    into the rules and are folded into that scan too, as ``check_all`` folds
    its own: the first step's ``occupations``, its ``is_metal`` fact,
    ``electron_count``, ``magnetic`` (the written cell and its spin),
    ``boundary``, ``relax`` (``None`` for an scf) and ``hubbard``, the ph
    step's ``q_sampling`` and the first step's ``fft_grid``. A finding of
    ``report`` that a phonon finding replaces, for the same root cause, is
    dropped (``_REPLACED_BY_PHONON``), and one whose smearing remedy would
    keep a requested moment unsets it (``_unpinned_with_smearing``)."""
    optional = tuple(
        state
        for state in (
            occupations,
            is_metal,
            electron_count,
            magnetic,
            boundary,
            relax,
            hubbard,
            q_sampling,
            fft_grid,
        )
        if state is not None
    )
    rule_findings = (
        _phonon_needs_atomic_hubbard_projectors(hubbard),
        _phonon_refuses_noncollinear_hubbard(hubbard, magnetic),
        _phonon_refuses_a_molecule_in_a_box(boundary, magnetic),
        _phonon_refuses_two_fermi_energies(occupations, magnetic, electron_count),
        _phonon_q_mesh_within_ph_x_and_q2r_x(q_sampling),
        _vc_relax_phonon_refuses_fragile_cell(fft_grid, purpose),
        _phonon_refuses_fix_bottom_layers(relax),
        _phonon_needs_confirmed_metallicity(
            occupations, is_metal, electron_count, magnetic, hubbard
        ),
    )
    found = tuple(finding for finding in rule_findings if finding is not None)
    replaced = {
        code for finding in found for code in _REPLACED_BY_PHONON.get(finding.code, ())
    }
    return CheckReport(
        blocking=(
            *(
                _unpinned_with_smearing(finding)
                for finding in report.blocking
                if finding.code not in replaced
            ),
            *collect_blocked(*field_states, *optional),
            *found,
        )
    )


def _unpinned_with_smearing(finding: Finding) -> Finding:
    """``finding`` of a phonon task's first step, with rule 12 of this
    module's docstring applied to its remedy: a requested moment that fixed
    occupations cannot take is unset with the smearing that replaces them,
    since ph.x refuses a moment on smearing. Any other finding is returned
    as it is."""
    if finding.code not in _KEEPING_THE_MOMENT:
        return finding
    return replace(
        finding,
        message=(
            f"{finding.message} A phonon task also needs tot_magnetization unset "
            "with occupations=smearing: ph.x refuses the two Fermi energies a "
            "pinned moment gives there."
        ),
        remedies=(_UNPINNED_SMEARING,),
    )


def _fixed_occupations_needs_integer_moment(
    occupations: FieldState[OccupationsDecision] | None,
    magnetic: FieldState[MagneticConfigFacts] | None,
    electron_count: FieldState[ElectronCountDecision] | None,
    purpose: str,
) -> Finding | None:
    if purpose not in SCF_LIKE_PURPOSES or occupations is None or magnetic is None:
        return None
    if not (occupations.ok and magnetic.ok):
        return None  # already surfaced via collect_blocked, or genuinely unknown
    if (
        occupations.value.occupations != "fixed"
        or magnetic.value.spin_mode != "collinear"
    ):
        return None
    tot = occupations.value.tot_magnetization
    if tot is None:
        return _MISSING_TOT_MAGNETIZATION
    if tot != int(tot):
        return replace(
            _NON_INTEGER_TOT_MAGNETIZATION,
            message=(
                "occupations=fixed on a collinear spin-polarized run needs an "
                f"integer tot_magnetization, not {tot:.10g}. Set "
                "occupations=smearing, or an integer tot_magnetization of the "
                "electron count's parity."
            ),
            remedies=(_SMEARING,),
        )
    # nelup = (nelec + tot) / 2, neldw = (nelec - tot) / 2 (#70): both need
    # to be integers, which needs tot_magnetization and nelec to share
    # parity -- an integer tot_magnetization alone is not sufficient (e.g.
    # nelec=3, tot=2 gives nelup=2.5/neldw=0.5).
    if (
        electron_count is not None
        and electron_count.ok
        and not whole_spin_channels(electron_count.value.nelec, tot)
    ):
        return replace(
            _TOT_MAGNETIZATION_PARITY,
            message=(
                "occupations=fixed fills (nelec + tot_magnetization)/2 spin-up "
                "and (nelec - tot_magnetization)/2 spin-down electrons, which "
                "must both be whole numbers, so tot_magnetization must share "
                f"parity with the electron count; tot_magnetization={tot:.10g} "
                f"and nelec={electron_count.value.nelec:.10g} do not. Set "
                "occupations=smearing, or a tot_magnetization of the electron "
                "count's parity."
            ),
            remedies=(_SMEARING,),
        )
    return None


def _fixed_occupations_needs_even_electron_count(
    occupations: FieldState[OccupationsDecision] | None,
    magnetic: FieldState[MagneticConfigFacts] | None,
    electron_count: FieldState[ElectronCountDecision] | None,
    purpose: str,
) -> Finding | None:
    """Sibling of ``_fixed_occupations_needs_integer_moment`` above, for
    runs without spin polarization, spin-orbit or not: found empirically
    2026-09-16, verified against real QE 7.3 source
    (``PW/src/iweights.f90``) -- see this module's own docstring, rule 3."""
    if (
        purpose not in SCF_LIKE_PURPOSES
        or occupations is None
        or magnetic is None
        or electron_count is None
    ):
        return None
    if not (occupations.ok and magnetic.ok and electron_count.ok):
        return None  # already surfaced via collect_blocked, or genuinely unknown
    if occupations.value.occupations != "fixed" or magnetic.value.spin_polarized:
        return None
    nelec = electron_count.value.nelec
    if not whole_spin_channels(nelec, 0.0):
        return replace(
            _ODD_ELECTRON_COUNT,
            message=(
                "occupations=fixed without spin polarization needs an even "
                f"electron count, but nelec={nelec:.10g} is odd, which leaves one "
                "band half filled. Set occupations=smearing, or "
                "spin_polarized=true with occupations=smearing for an unpaired "
                "electron."
            ),
        )
    return None


def _nbnd_holds_every_electron(
    nbnd: FieldState[NbndDecision] | None,
    occupations: FieldState[OccupationsDecision] | None,
    magnetic: FieldState[MagneticConfigFacts] | None,
    electron_count: FieldState[ElectronCountDecision] | None,
    purpose: str,
) -> Finding | None:
    """Rule 4 of this module's docstring: the first of pw.x's band floors
    ``nbnd`` falls below, with the fewest bands that pass them all, worded
    for a step of ``purpose``: pw.x itself stops only in a run with its own
    SCF loop. The finding's ``cause`` is the same for every purpose."""
    if (
        nbnd is None
        or occupations is None
        or magnetic is None
        or electron_count is None
    ):
        return None
    if not (nbnd.ok and occupations.ok and magnetic.ok and electron_count.ok):
        return None  # already surfaced via collect_blocked, or genuinely unknown
    bands = nbnd.value.nbnd
    floors = band_floors(electron_count.value.nelec, occupations.value, magnetic)
    short = [floor for floor in floors if bands < floor.bands]
    if not short:
        return None
    floor = short[0]
    least = max(each.bands for each in floors)
    cannot_hold = f"nbnd={bands} cannot hold {floor.electrons:.10g} {floor.held}"
    if purpose in SCF_LIKE_PURPOSES:
        consequence = f"{cannot_hold}: pw.x stops in setup with '{floor.error}'."
    else:
        consequence = (
            f"{cannot_hold}, so this {purpose} step would leave occupied bands "
            "out; pw.x checks the band count only in a run with its own SCF loop."
        )
    return replace(
        _TOO_FEW_BANDS,
        message=(
            f"{consequence} Unset nbnd and extra_bands for the default, or set "
            f"nbnd to at least {least}."
        ),
        cause=f"{cannot_hold}; at least {least} bands hold them all",
    )


def _bands_x_refuses_tot_magnetization(
    occupations: FieldState[OccupationsDecision] | None,
    magnetic: FieldState[MagneticConfigFacts] | None,
    purpose: str,
) -> Finding | None:
    """Rule 7 of this module's docstring."""
    if purpose != "bands" or occupations is None or magnetic is None:
        return None
    if not (occupations.ok and magnetic.ok):
        return None  # already surfaced via collect_blocked, or genuinely unknown
    tot = occupations.value.tot_magnetization
    if magnetic.value.spin_mode != "collinear" or tot is None:
        return None
    return replace(
        _BANDS_X_TOT_MAGNETIZATION,
        message=(
            f"A band task cannot pin tot_magnetization={tot:.10g} on a collinear "
            "spin-polarized run: it gives the scf two Fermi energies, which the "
            "bands step inherits and bands.x stops on ('The bands code with "
            "constrained magnetization has not been tested') once both pw.x "
            "steps have run. Set occupations=smearing and unset "
            "tot_magnetization."
        ),
    )


def _band_path_within_pw_x_k_points(
    parallel: FieldState[ParallelisationDecision] | None, purpose: str
) -> Finding | None:
    """Rule 8 of this module's docstring: the bands step's k-point/spin
    pairs are every point of its path, per spin channel of a collinear
    run."""
    if purpose != "bands" or parallel is None or not parallel.ok:
        return None
    pairs = parallel.value.kpoint_spin_pairs
    if pairs <= _PW_X_MAX_KPOINTS:
        return None
    return replace(
        _TOO_MANY_KPOINTS,
        message=(
            f"The band path gives the bands step {pairs} k-point/spin pairs, more "
            f"than the {_PW_X_MAX_KPOINTS} pw.x accepts: it stops in setup with "
            "'too many k points'. Unset k_path_distance for the default, or set a "
            "larger one."
        ),
    )


def _npool_must_divide_ntasks(
    job: FieldState[JobDecision] | None,
    parallel: FieldState[ParallelisationDecision] | None,
) -> Finding | None:
    """``npool`` not dividing ``ntasks`` is a hard MPI-layout requirement
    QE itself refuses (``advisors/parallelisation.py``'s own docstring):
    a bad ``npool`` fails only once compute is already allocated and the
    job is running, worse than the same "warn, don't block" pattern used
    for e.g. ``nodes``/``walltime_h`` exceeding a partition's ceiling
    (which fail at SLURM *submission*, before any compute is consumed).
    ``parallelisation()``'s own heuristic default (``best_npool``)
    always returns a value that divides ``ntasks`` by construction, so
    this can only ever fire for a human override."""
    if job is None or parallel is None or not job.ok or not parallel.ok:
        return None
    if job.value.ntasks % parallel.value.npool != 0:
        return replace(
            _NPOOL,
            message=(
                f"npool={parallel.value.npool} does not divide "
                f"ntasks={job.value.ntasks}, and pw.x refuses that layout. Unset "
                "npool for the default, or set npool to a divisor of ntasks."
            ),
        )
    return None


def _ndiag_grid_must_distribute_bands(
    job: FieldState[JobDecision] | None,
    parallel: FieldState[ParallelisationDecision] | None,
    nbnd: FieldState[NbndDecision] | None,
) -> Finding | None:
    """Rule 5 of this module's docstring. ``parallelisation()`` never
    sets ``ndiag`` itself, so this only fires for a human override; like
    a bad ``npool``, such a layout fails only after queueing, or hangs a
    node until the walltime runs out."""
    if job is None or parallel is None or nbnd is None:
        return None
    if not (job.ok and parallel.ok and nbnd.ok) or parallel.value.ndiag is None:
        return None  # already surfaced via collect_blocked, or left to pw.x
    ndiag = parallel.value.ndiag
    bands = nbnd.value.nbnd
    side = diag_grid_side(ndiag, job.value.ntasks // parallel.value.npool, bands)
    if bands > (side - 1) ** 2:
        return None
    return replace(
        _NDIAG,
        message=(
            f"ndiag={ndiag} gives a {side}x{side} diagonalization grid, which "
            f"cannot distribute nbnd={bands} bands (it needs nbnd > "
            f"{(side - 1) ** 2}); pw.x would abort at startup or fail in the "
            "parallel eigensolver. Unset ndiag so pw.x chooses it from nbnd, "
            f"or use ndiag <= {(math.isqrt(bands - 1) + 1) ** 2}."
        ),
    )


def _vc_relax_requires_bfgs_ion_dynamics(
    relax: FieldState[RelaxOptions | VcRelaxOptions] | None,
    purpose: str,
) -> Finding | None:
    """QE couples ``cell_dynamics`` to ``ion_dynamics`` for vc-relax
    (``advisors/relax.py``'s own docstring, audit finding B5): this
    codebase's ``VcRelaxOptions.cell_dynamics`` is a derived property
    that always mirrors ``ion_dynamics``, which only produces a valid QE
    keyword when ``ion_dynamics == 'bfgs'`` (the only vc-relax
    ``cell_dynamics`` value this codebase's generation layer renders).
    ``ion_dynamics`` in {'damp', 'fire'} is real, QE-documented syntax
    for a plain ``relax`` -- only vc-relax is restricted here."""
    if purpose != "vc-relax" or relax is None or not relax.ok:
        return None
    if relax.value.ion_dynamics != "bfgs":
        return replace(
            _VC_RELAX_ION_DYNAMICS,
            message=(
                "vc-relax is generated only with ion_dynamics=bfgs, not "
                f"{relax.value.ion_dynamics}: Quantum ESPRESSO pairs cell_dynamics "
                "with ion_dynamics in a vc-relax, and only the bfgs pair is "
                "written. Set ion_dynamics=bfgs."
            ),
        )
    return None


def _isolation_matches_written_cell(
    boundary: FieldState[BoundaryFacts] | None,
    magnetic: FieldState[MagneticConfigFacts] | None,
) -> Finding | None:
    """'isolated' and 'slab' truncate the Coulomb interaction, which is right
    only for the vacuum each assumes (#161). Checked on the cell the writer
    renders, whatever the source of ``isolation``."""
    if boundary is None or magnetic is None or not (boundary.ok and magnetic.ok):
        return None
    cell = magnetic.value.cell
    if boundary.value.isolation == "isolated":
        return _isolated_needs_vacuum_along_every_axis(cell)
    if boundary.value.isolation == "slab":
        return _slab_needs_room_for_the_2d_truncation(cell)
    return None


def _isolated_needs_vacuum_along_every_axis(cell: Structure) -> Finding | None:
    """Martyna-Tuckerman treats the system as a molecule or cluster in a 3D
    supercell (QE 7.3 PW/Doc/INPUT_PW.def:1593-1594); pw.x has no 1D
    truncation for a wire."""
    axes = vacuum_axes(cell)
    if len(axes) == 3:
        return None
    found = f"vacuum only along {_listed(axes)}" if axes else "no vacuum"
    return replace(
        _ISOLATED_WITHOUT_VACUUM,
        message=(
            "isolation=isolated writes Martyna-Tuckerman (assume_isolated="
            "'martyna-tuckerman'), which treats the system as a molecule or "
            "cluster in a box and needs vacuum along a, b and c, but the cell to "
            f"be written has {found}. Set isolation=periodic."
        ),
    )


def _slab_needs_room_for_the_2d_truncation(cell: Structure) -> Finding | None:
    """QE's 2D Coulomb truncation cuts the interaction between charges more
    than half the cell height apart along z (QE 7.3
    PW/src/Coul_cut_2D.f90:77-81). It assumes a and b in the xy plane
    (Coul_cut_2D.f90:72-74, which only prints a warning) and c along z: its
    cutoff factor 1 - exp(-G_xy c/2) cos(G_z c/2) (Sohier et al., Phys. Rev.
    B 96, 075448 (2017), Eq. 24) is the Fourier transform of the truncated
    interaction only when every G_z is a multiple of 2 pi / c, so that the
    transform's sin(G_z c/2) term vanishes. It stops when the half height is
    below the pseudopotentials' radial cutoff, and truncates part of the
    slab's own interaction when the vacuum is too narrow;
    ``analysis.geometry.two_d_truncation_obstacles`` holds both bounds, and
    the boundary advisor offers 'slab' only where it finds nothing."""
    found = _xy_frame_obstacles(cell, allowed_vacuum=(("c",),))
    if not found:
        found = list(two_d_truncation_obstacles(cell))
    if not found:
        return None
    return replace(
        _SLAB_UNSUITED,
        message=(
            "isolation=slab writes Quantum ESPRESSO's 2D Coulomb truncation "
            "(assume_isolated='2D'), which needs vacuum along c only, a and b in "
            "the Cartesian xy plane, c along z, and room along z for the "
            "pseudopotentials and the slab, but the cell to be written has "
            f"{' and '.join(found)}. Set isolation=periodic."
        ),
    )


def _vc_relax_forbids_isolated_boundary(
    boundary: FieldState[BoundaryFacts] | None, purpose: str
) -> Finding | None:
    """Under Martyna-Tuckerman, from any source, pw.x clears ``tstress``
    (QE 7.3 PW/src/input.f90:1361-1365) even though vc-relax had switched
    it on (input.f90:646): BFGS then sees a zero cell gradient and reports
    the input cell as converged, exiting 0 (#126)."""
    if purpose != "vc-relax" or boundary is None or not boundary.ok:
        return None
    if boundary.value.isolation != "isolated":
        return None
    return _ISOLATED_VC_RELAX


def _slab_vc_relax_needs_2d_cell_dofree(
    boundary: FieldState[BoundaryFacts] | None,
    relax: FieldState[RelaxOptions | VcRelaxOptions] | None,
    magnetic: FieldState[MagneticConfigFacts] | None,
) -> Finding | None:
    """Under QE's 2D Coulomb truncation only in-plane stresses make sense, and
    QE asks a vc-relax to use cell_dofree='2Dxy' (QE 7.3
    PW/Doc/INPUT_PW.def:1677-1678); pw.x itself does not check it. Any value
    in ``_TWO_D_CELL_DOFREE`` holds c and the z components of a and b.
    Checked only on a written cell that is a slab with its vacuum along c in
    the xy frame, whose default is '2Dxy': there '2Dxy' passes the 2D-frame
    rule and is what isolation=periodic with cell_dofree unset writes, so
    both remedies hold and neither relaxes the vacuum. The boundary rule
    refuses isolation=slab on any other cell, with isolation=periodic as its
    remedy; there '2Dxy' fails the 2D-frame rule unless a and b lie in the xy
    plane without vacuum, and an unset cell_dofree blocks a wire or a slab
    with its vacuum along a or b and gives a box 'all'."""
    if boundary is None or relax is None or magnetic is None:
        return None
    if not (boundary.ok and relax.ok and magnetic.ok):
        return None
    options = relax.value
    if boundary.value.isolation != "slab" or not isinstance(options, VcRelaxOptions):
        return None
    if options.cell_dofree in _TWO_D_CELL_DOFREE:
        return None
    if _xy_frame_obstacles(magnetic.value.cell, allowed_vacuum=(("c",),)):
        return None
    return replace(
        _SLAB_VC_RELAX_CELL_DOFREE,
        message=(
            "vc-relax with isolation=slab cannot use "
            f"cell_dofree={options.cell_dofree}: under Quantum ESPRESSO's 2D "
            "Coulomb truncation only the in-plane stress is meaningful, so c and "
            "the z components of a and b must stay fixed. Set cell_dofree=2Dxy "
            "(or 2Dshape), or isolation=periodic with cell_dofree unset."
        ),
    )


def _two_d_cell_dofree_needs_xy_frame(
    relax: FieldState[RelaxOptions | VcRelaxOptions] | None,
    magnetic: FieldState[MagneticConfigFacts] | None,
) -> Finding | None:
    """QE's 2D cell constraints move only the x and y components of a and b
    and hold c fixed, in Cartesian axes (QE 7.3 Modules/cell_base.f90:742-749
    and :803-808), and BFGS judges convergence on the masked stress. With a
    or b out of the xy plane they distort any cell, bulk included: SCARF
    shrank a and b of rhombohedral Bi2Se3 under '2Dxy' while c stayed fixed.
    With vacuum along a or b they free a vacuum vector and freeze one in the
    sheet (#132). Checked on the cell the writer renders, whatever the
    source of ``cell_dofree``. 'all' is the remedy only for a cell without
    vacuum: with vacuum it would relax the vacuum too, which is why the relax
    advisor gives a wire or a slab outside the xy frame no default."""
    if relax is None or magnetic is None or not (relax.ok and magnetic.ok):
        return None
    options = relax.value
    if not isinstance(options, VcRelaxOptions):
        return None
    if options.cell_dofree not in _TWO_D_CELL_DOFREE:
        return None
    cell = magnetic.value.cell
    found = _xy_frame_obstacles(cell, allowed_vacuum=((), ("c",)))
    if not found:
        return None
    message = (
        f"cell_dofree={options.cell_dofree} moves only the x and y components "
        "of a and b and holds c fixed, so it needs a and b in the Cartesian xy "
        "plane and any vacuum along c, but the cell to be written has "
        f"{' and '.join(found)}."
    )
    axes = vacuum_axes(cell)
    if not axes:
        return replace(
            _TWO_D_CELL_DOFREE_FRAME,
            message=f"{message} Set cell_dofree=all, or reorient the cell.",
        )
    return replace(
        _TWO_D_CELL_DOFREE_FRAME,
        message=f"{message} {_holding_the_vacuum(axes)}",
        remedies=(),
    )


def _holding_the_vacuum(axes: tuple[LatticeAxis, ...]) -> str:
    """What holds the vacuum along ``axes`` fixed in a vc-relax, for a
    2D cell constraint refused on that cell: no orientation suits a wire or
    a box, whose two or three vacuum vectors cannot all lie along c."""
    if len(axes) == 3:
        return (
            "Use the relax task for a molecule or cluster in a box: every "
            "lattice vector is a vacuum vector, so a vc-relax would relax the "
            "vacuum."
        )
    if len(axes) == 2:
        period, constraint = wire_period(axes)
        return (
            "Set a cell_dofree that holds the vacuum fixed: "
            f"cell_dofree={constraint} holds {' and '.join(axes)} fixed and "
            f"relaxes only {period}, the wire's period, while cell_dofree=all "
            "would relax the vacuum too."
        )
    return (
        "Reorient the cell, or set a cell_dofree that holds the vacuum fixed: "
        "cell_dofree=all would relax the vacuum too."
    )


def _cartesian_cell_dofree_needs_unrotated_cell(
    relax: FieldState[RelaxOptions | VcRelaxOptions] | None,
    magnetic: FieldState[MagneticConfigFacts] | None,
) -> Finding | None:
    """Rule 6 of this module's docstring, whatever the source of
    ``cell_dofree``. The remedy clears the override rather than naming
    'all': a rotated cell is a bulk crystal, whose default is 'all', or a
    slab with its vacuum along c, whose default '2Dxy' keeps the vacuum
    fixed and also passes the 2D-truncation rule under isolation='slab',
    which 'all' would not."""
    if relax is None or magnetic is None or not (relax.ok and magnetic.ok):
        return None
    options = relax.value
    frame = magnetic.value.frame
    if not isinstance(options, VcRelaxOptions) or frame is None or not frame.rotated:
        return None
    if options.cell_dofree not in _CARTESIAN_CELL_DOFREE:
        return None
    return replace(
        _CARTESIAN_CELL_DOFREE_ROTATED,
        message=(
            f"cell_dofree={options.cell_dofree} holds or frees single Cartesian "
            "components of the lattice vectors, but the cell to be written is the "
            f"uploaded one {frame.describe_rotation()} into pw.x's frame, so its "
            "x, y and z are not the uploaded cell's. Unset cell_dofree for the "
            "default, or use cell_dofree=all or shape, or fixa, fixb or fixc to "
            "fix whole lattice vectors."
        ),
    )


def _xy_frame_obstacles(
    cell: Structure, allowed_vacuum: tuple[tuple[LatticeAxis, ...], ...]
) -> list[str]:
    """What keeps ``cell`` out of the frame QE's 2D methods assume: a or b out
    of the Cartesian xy plane, and vacuum axes other than those
    ``allowed_vacuum`` lists."""
    found = []
    if not ab_in_xy_plane(cell.lattice):
        found.append("a or b out of the xy plane")
    axes = vacuum_axes(cell)
    if axes not in allowed_vacuum:
        found.append(f"vacuum along {_listed(axes)}" if axes else "no vacuum")
    return found


def _listed(names: tuple[str, ...]) -> str:
    """``names`` as an English list: 'c', 'a and b' or 'a, b and c'."""
    *rest, last = names
    return f"{', '.join(rest)} and {last}" if rest else last


def _dispersion_needs_parameterised_functional(
    vdw: FieldState[VdwFacts] | None, functional: FieldState[str] | None
) -> Finding | None:
    """D3(BJ), the only dispersion method generated, needs damping
    parameters for the functional: pw.x passes DFT-D3 the pseudopotentials'
    short functional name (QE 7.3 PW/src/input.f90:2039-2041) and stops with
    "functional name unknown" when the table lacks it, as for LDA (#141).
    ``vdw_method`` never picks D3 for such a functional itself, so this
    refuses ``use_vdw=True`` from any source."""
    if vdw is None or functional is None or not (vdw.ok and functional.ok):
        return None
    if not vdw.value.use_vdw or has_d3bj_parameters(functional.value):
        return None
    return replace(
        _DISPERSION_FUNCTIONAL,
        message=(
            "use_vdw=true adds D3(BJ) dispersion, but Quantum ESPRESSO's DFT-D3 "
            f"has no parameters for functional {functional.value}, so pw.x would "
            "stop with 'functional name unknown'. Set use_vdw=false, or choose a "
            "functional with D3(BJ) parameters "
            f"({', '.join(sorted(D3BJ_FUNCTIONALS))})."
        ),
    )


def _fix_bottom_layers_requires_slab(
    relax: FieldState[RelaxOptions | VcRelaxOptions] | None,
    magnetic: FieldState[MagneticConfigFacts] | None,
) -> Finding | None:
    """``relax.fix_bottom_layers`` (#44) freezes a slab's bottom N atomic
    layers, which ``analysis.geometry.slab_layers`` counts up from the vacuum
    of a cell with exactly one vacuum axis. A '2d' rank is no evidence of a
    slab: bulk graphite ranks '2d' and has no vacuum (#160). Checked with the
    writer's own layers, on the cell it renders, so a passing check means the
    writer can apply the count."""
    if relax is None or magnetic is None or not (relax.ok and magnetic.ok):
        return None
    count = relax.value.fix_bottom_layers
    if count is None:
        return None
    cell = magnetic.value.cell
    layers = slab_layers(cell)
    if layers is None:
        return replace(
            _FIX_BOTTOM_LAYERS_WITHOUT_SLAB,
            message=(
                "fix_bottom_layers freezes the bottom atomic layers counted up "
                "from the vacuum, so it needs a slab: one vacuum gap, along "
                "exactly one lattice vector. The cell to be written has "
                f"{_no_single_slab(cell)}. Unset fix_bottom_layers."
            ),
        )
    if count > len(layers):
        return replace(
            _FIX_BOTTOM_LAYERS_EXCEEDS,
            message=(
                f"fix_bottom_layers={count} exceeds the {len(layers)} atomic "
                "layers of the slab to be written. Set fix_bottom_layers to at "
                f"most {len(layers)}, or unset it."
            ),
        )
    return None


def _no_single_slab(cell: Structure) -> str:
    """Why ``analysis.geometry.slab_layers`` finds no single slab in ``cell``:
    its vacuum axes, or a second vacuum gap along its one vacuum axis."""
    axes = vacuum_axes(cell)
    if len(axes) == 1:
        return f"more than one vacuum gap along {axes[0]}, so more than one slab"
    return f"vacuum along {_listed(axes)}" if axes else "no vacuum"


def _u_elements(hubbard: HubbardUDecision) -> str:
    """The elements ``hubbard`` gives a U, as an English list."""
    return _listed(tuple(entry.element for entry in hubbard.u_values))


def _phonon_needs_atomic_hubbard_projectors(
    hubbard: FieldState[HubbardUDecision] | None,
) -> Finding | None:
    """Rule 9 of this module's docstring: a decision with a U names its
    projectors, ``None`` exactly when there is no U."""
    if hubbard is None or not hubbard.ok:
        return None
    decision = hubbard.value
    if not decision.u_values or decision.projectors == "atomic":
        return None
    return replace(
        _PHONON_HUBBARD_PROJECTORS,
        message=(
            f"The Hubbard U on {_u_elements(decision)} is written with "
            f"{decision.projectors} projectors, but ph.x computes phonons with a "
            "Hubbard U only for atomic ones and stops with 'The phonon code for "
            "this Hubbard projectors type is not implemented'. Set "
            "hubbard_projectors=atomic, or hubbard_needs_correlation=false for no "
            "+U. A U value is tied to the projectors it was derived with, so the "
            "same U with atomic projectors is a different correction."
        ),
    )


def _phonon_refuses_noncollinear_hubbard(
    hubbard: FieldState[HubbardUDecision] | None,
    magnetic: FieldState[MagneticConfigFacts] | None,
) -> Finding | None:
    """Rule 10 of this module's docstring, with or without magnetic
    moments."""
    if hubbard is None or magnetic is None or not (hubbard.ok and magnetic.ok):
        return None
    if not hubbard.value.u_values or magnetic.value.spin_mode != "noncollinear":
        return None
    return replace(
        _PHONON_NONCOLLINEAR_HUBBARD,
        message=(
            "The phonon tasks cannot combine spin_orbit_coupling with the Hubbard "
            f"U on {_u_elements(hubbard.value)}: ph.x computes phonons with a "
            "Hubbard U for collinear spins only, so a noncollinear run would stop "
            "or give wrong phonons. Set spin_orbit_coupling=false, or "
            "hubbard_needs_correlation=false for no +U."
        ),
    )


def _phonon_refuses_a_molecule_in_a_box(
    boundary: FieldState[BoundaryFacts] | None,
    magnetic: FieldState[MagneticConfigFacts] | None,
) -> Finding | None:
    """Rule 11 of this module's docstring: on the written cell with vacuum
    along a, b and c, whatever its isolation, which the message names.
    'isolated' needs that vacuum (``_isolation_matches_written_cell`` refuses
    it on any other cell), and gets the catalogue message."""
    if boundary is None or magnetic is None or not (boundary.ok and magnetic.ok):
        return None
    if len(vacuum_axes(magnetic.value.cell)) != 3:
        return None
    isolation = boundary.value.isolation
    if isolation == "isolated":
        return _PHONON_ISOLATED
    return replace(
        _PHONON_ISOLATED,
        message=(
            "A molecule or cluster in a box (vacuum along a, b and c) has no "
            f"phonon dispersion, and with isolation={isolation} ph.x would "
            "compute a periodic array of copies, whose phonons include the "
            f"interactions between them. {_MOLECULAR_VIBRATIONS}"
        ),
    )


def _phonon_refuses_two_fermi_energies(
    occupations: FieldState[OccupationsDecision] | None,
    magnetic: FieldState[MagneticConfigFacts] | None,
    electron_count: FieldState[ElectronCountDecision] | None,
) -> Finding | None:
    """Rule 12 of this module's docstring: the moment the occupations
    decision pins, which the writer renders only for a collinear run
    (#138). Fixed occupations are offered only for a moment that passes
    rule 2, an integer of the electron count's parity."""
    if occupations is None or magnetic is None:
        return None
    if not (occupations.ok and magnetic.ok):
        return None  # already surfaced via collect_blocked, or genuinely unknown
    chosen = occupations.value.occupations
    tot = occupations.value.tot_magnetization
    if chosen == "fixed" or tot is None or magnetic.value.spin_mode != "collinear":
        return None
    fixed_runs = (
        tot == int(tot)
        and electron_count is not None
        and electron_count.ok
        and whole_spin_channels(electron_count.value.nelec, tot)
    )
    fixed = (
        ", or set occupations=fixed, which this integer moment of the electron "
        "count's parity allows"
        if fixed_runs
        else ""
    )
    return replace(
        _PHONON_PINNED_MOMENT,
        message=(
            f"tot_magnetization={tot:.10g} with occupations={chosen} gives the scf "
            "two Fermi energies, which ph.x refuses on smearing or tetrahedra: it "
            "stops with 'The phonon code with two fermi energies is not available "
            f"for metals'. Unset tot_magnetization{fixed}."
        ),
        remedies=_PHONON_PINNED_MOMENT.remedies if fixed_runs else (_UNPINNED,),
    )


def _phonon_q_mesh_within_ph_x_and_q2r_x(
    q_sampling: FieldState[QSamplingDecision] | None,
) -> Finding | None:
    """Rules 13 and 14 of this module's docstring: the q record's refusal,
    with its cause."""
    if q_sampling is None or not q_sampling.ok or q_sampling.value.refusal is None:
        return None
    refusal = q_sampling.value.refusal
    if refusal.kind == "breaks_symmetry":
        return replace(
            _PHONON_Q_GRID_SYMMETRY,
            message=f"{refusal.cause}. Unset q_grid for the default q-mesh.",
        )
    return replace(
        _PHONON_TOO_MANY_Q_POINTS,
        message=(
            f"The phonon run would stop in q2r.x: {refusal.cause}. Unset q_grid "
            "and q_distance for the default q-mesh, or set a coarser one."
        ),
    )


def _vc_relax_phonon_refuses_fragile_cell(
    fft_grid: FieldState[FftGridDecision] | None, purpose: str
) -> Finding | None:
    """Rule 15 of this module's docstring: on a fragile cell, whether or not
    pw.x's own grid passes on the input cell, since the vc-relax's final scf
    builds it for the relaxed one."""
    if purpose != "vc-relax" or fft_grid is None or not fft_grid.ok:
        return None
    decision = fft_grid.value
    if not decision.fragile:
        return None
    axes = _listed(
        tuple(sorted({axis for pair in decision.fragile_axes for axis in pair}))
    )
    if decision.compatible:
        refused = (
            f"the symmetry operations pw.x keeps mix lattice vectors {axes}, so a "
            "strained cell can give pw.x's own FFT grid counts on which ph.x stops "
            "with 'FFT grid incompatible with symmetry'"
        )
    else:
        grid = "x".join(str(count) for count in decision.pw_grid)
        refused = (
            f"pw.x's own FFT grid for it, {grid}, is not mapped onto itself by the "
            f"symmetry operations pw.x keeps, which mix lattice vectors {axes}, so "
            "ph.x would stop with 'FFT grid incompatible with symmetry'"
        )
    return replace(
        _PHONON_VC_RELAX_FFT_GRID,
        message=(
            f"vc-relax-phonon cannot run on this cell: {refused}. The vc-relax's "
            "final scf rebuilds that grid for the relaxed cell, so no grid written "
            "for ph.x reaches it. Use relax-phonon, which relaxes the atoms in the "
            "written cell and keeps a grid written for ph.x, or run the vc-relax "
            "task and then the phonon task on the relaxed structure."
        ),
    )


def _phonon_refuses_fix_bottom_layers(
    relax: FieldState[RelaxOptions | VcRelaxOptions] | None,
) -> Finding | None:
    """Rule 16 of this module's docstring, on any cell: the slab rules'
    findings for the same setting are dropped (``_REPLACED_BY_PHONON``)."""
    if relax is None or not relax.ok or relax.value.fix_bottom_layers is None:
        return None
    return replace(
        _PHONON_FIX_BOTTOM_LAYERS,
        message=(
            f"fix_bottom_layers={relax.value.fix_bottom_layers} pins atoms in the "
            "relaxation, so they keep leftover forces, while ph.x computes the "
            "phonons as second derivatives at an equilibrium, where every force is "
            "zero. Unset fix_bottom_layers."
        ),
    )


def _phonon_needs_confirmed_metallicity(
    occupations: FieldState[OccupationsDecision] | None,
    is_metal: FieldState[Metallicity] | None,
    electron_count: FieldState[ElectronCountDecision] | None,
    magnetic: FieldState[MagneticConfigFacts] | None,
    hubbard: FieldState[HubbardUDecision] | None,
) -> Finding | None:
    """Rule 17 of this module's docstring, on the written cell's composition,
    whoever chose the occupations: of the is_metal facts only the user's metal
    passes, and of fixed occupations only those the run takes; a requested
    occupations=fixed it cannot take is refused here in place of rules 2 and 3
    (``_REPLACED_BY_PHONON``). The finding gives why the run is not on fixed
    occupations (``_not_on_fixed``), what an insulator sets
    (``_insulator_route``) and what a metal sets (``_metal_route``), and names
    the settings the message asks for."""
    if occupations is None or is_metal is None or magnetic is None:
        return None
    if not (occupations.ok and magnetic.ok):
        return None  # already surfaced via collect_blocked, or genuinely unknown
    chosen = occupations.value.occupations
    on_fixed = chosen == "fixed" and fixed_occupations_run(magnetic, electron_count)
    if on_fixed or all_metallic(magnetic.value.cell):
        return None
    answer = is_metal.value if is_metal.ok and is_metal.source == "human" else None
    if answer == "metal":
        return None
    sources = occupations.provenance.field_sources or {}
    requested = sources.get("occupations", "heuristic") != "heuristic"
    route = _insulator_route(magnetic, electron_count, hubbard, requested=requested)
    why = _not_on_fixed(
        chosen,
        route.obstacle,
        requested=requested,
        answer=answer,
        classified_non_metal=is_metal.ok and is_metal.value == "non_metal",
    )
    metal, metal_remedy = _metal_route(chosen, magnetic)
    runs = (
        "the request sets occupations=fixed, which this run cannot take"
        if chosen == "fixed"
        else f"it runs on occupations={chosen}"
    )
    asked = {
        "is_metal",
        *route.fields,
        *metal_remedy,
        *(("occupations",) if requested else ()),
    }
    stake = "an insulator loses its LO-TO splitting"
    summary = (
        "Confirm whether this structure is a metal: the requested "
        "occupations=fixed cannot run as it stands, and a metal needs smearing "
        f"instead, where {stake}."
        if chosen == "fixed"
        else "Confirm whether this structure is a metal: its composition is not "
        f"all-metallic, and it runs on occupations={chosen}, where {stake}."
    )
    return replace(
        _PHONON_METALLICITY_UNCONFIRMED,
        summary=summary,
        message=(
            "The phonon tasks need this structure on fixed occupations, or "
            f"confirmed as a metal: {runs}, and its composition is not "
            "all-metallic, so it may be an insulator. "
            f"{_PH_X_TREATS_SMEARING_AS_METAL} {why} {route.advice}; {metal}."
        ),
        fields=tuple(
            name for name in _PHONON_METALLICITY_UNCONFIRMED.fields if name in asked
        ),
        remedies=(*route.remedies, metal_remedy),
    )


def _metal_route(
    chosen: str, magnetic: FieldState[MagneticConfigFacts]
) -> tuple[str, dict[str, object]]:
    """Rule 17's advice for a metal on ``chosen`` occupations, and its patch:
    is_metal=metal, which keeps smearing or tetrahedra; in place of a
    requested occupations=fixed the run cannot take, with smearing, and with
    the request's moment unset, which ph.x refuses on smearing (rule 12)."""
    if chosen != "fixed":
        advice = f"for a metal set is_metal=metal, which keeps occupations={chosen}"
        return advice, _METAL
    smearing = "for a metal set is_metal=metal and occupations=smearing"
    if magnetic.value.tot_magnetization is None:
        return smearing, _METAL_ON_SMEARING
    return (
        f"{smearing}, and unset tot_magnetization, which ph.x refuses on smearing",
        _UNPINNED_METAL_ON_SMEARING,
    )


@dataclass(frozen=True, slots=True)
class _InsulatorRoute:
    """How rule 17's insulator reaches fixed occupations: ``obstacle``, why
    they do not run as the run stands (``None`` where they do); ``advice``,
    what an insulator sets; ``remedies``, the complete patches among that;
    ``fields``, the settings ``advice`` names besides is_metal and the
    requested occupations."""

    obstacle: str | None
    advice: str
    remedies: tuple[dict[str, object], ...]
    fields: tuple[str, ...]


def _insulator_route(
    magnetic: FieldState[MagneticConfigFacts],
    electron_count: FieldState[ElectronCountDecision] | None,
    hubbard: FieldState[HubbardUDecision] | None,
    *,
    requested: bool,
) -> _InsulatorRoute:
    """Rule 17's route to fixed occupations for an insulator on ``magnetic``'s
    spin, by the occupations rule (``fixed_occupations_run``):
    is_metal=non_metal, or occupations=fixed where the request sets the
    occupations, which is_metal does not change. A collinear run without a
    moment fixed occupations take needs tot_magnetization as well, named, or,
    where it gives fixed occupations, is_magnetic=non_magnetic
    (``_non_magnetic_runs_fixed``); an odd electron count without spin
    polarization needs spin polarization and, on a collinear run, the moment,
    named."""
    setting = "occupations=fixed" if requested else "is_metal=non_metal"
    patch = _FIXED if requested else _NON_METAL
    if fixed_occupations_run(magnetic, electron_count):
        runs = "" if requested else ", which runs it on fixed occupations"
        return _InsulatorRoute(
            None, f"For an insulator set {setting}{runs}", (patch,), ()
        )
    if magnetic.value.spin_mode != "collinear":
        return _InsulatorRoute(
            _ODD_WITHOUT_SPIN,
            f"For a magnetic insulator set {setting} with spin_polarized=true and, "
            "on a collinear run, its integer moment as tot_magnetization, odd like "
            "the electron count",
            (),
            ("spin_polarized", "tot_magnetization"),
        )
    tot = magnetic.value.tot_magnetization
    lacking = (
        "and this run has none"
        if tot is None
        else f"which tot_magnetization={tot:.10g} is not"
    )
    obstacle = f"{_FIXED_NEEDS_MOMENT}, {lacking}"
    moment = (
        f"For a magnetic insulator set {setting} with tot_magnetization, its "
        "integer moment in Bohr magnetons per cell"
    )
    if not _non_magnetic_runs_fixed(magnetic, electron_count, hubbard):
        return _InsulatorRoute(obstacle, moment, (), ("tot_magnetization",))
    return _InsulatorRoute(
        obstacle,
        f"{moment}; for one without magnetic moments set {setting} and "
        "is_magnetic=non_magnetic",
        ({**patch, **_NON_MAGNETIC},),
        ("is_magnetic", "tot_magnetization"),
    )


def _non_magnetic_runs_fixed(
    magnetic: FieldState[MagneticConfigFacts],
    electron_count: FieldState[ElectronCountDecision] | None,
    hubbard: FieldState[HubbardUDecision] | None,
) -> bool:
    """Whether is_magnetic=non_magnetic puts a collinear run on fixed
    occupations: that answer gives it no spin polarization, as it does unless
    the request or the llm decides the spin polarization or a Hubbard U acts
    on an odd d or f count (``advisors/magnetic_config.py``'s
    ``unpolarized_if_non_magnetic``), and fixed occupations run on the
    electron count without spin polarization."""
    # Without a magnetic record the run reads as spin-unpolarized.
    unpolarized_runs = fixed_occupations_run(None, electron_count)
    return unpolarized_runs and unpolarized_if_non_magnetic(magnetic, hubbard)


def _not_on_fixed(
    chosen: str,
    obstacle: str | None,
    *,
    requested: bool,
    answer: str | None,
    classified_non_metal: bool,
) -> str:
    """Rule 17's reason that a run on ``chosen`` occupations is not on fixed
    ones it takes: the ``obstacle`` that refuses a requested occupations=fixed;
    the request's other occupations, which is_metal does not change, with the
    ``obstacle`` that would refuse occupations=fixed; otherwise, the
    classifier's threshold where is_metal=non_metal would give fixed
    occupations, and the ``obstacle`` that keeps the user's non_metal
    (``answer``), the classifier's or any other fact on ``chosen``."""
    if chosen == "fixed":
        return f"Fixed occupations are refused here: {obstacle}."
    if requested:
        why = f"The request sets occupations={chosen}, which is_metal does not change"
        if obstacle is None:
            return f"{why}."
        return (
            f"{why}, and setting occupations=fixed alone would be refused: {obstacle}."
        )
    if obstacle is None:
        return _CLASSIFIER_CALLS_INSULATORS_METALS
    if answer == "non_metal":
        return f"With is_metal=non_metal it stays on occupations={chosen}: {obstacle}."
    if classified_non_metal:
        return (
            f"It is classified as a non-metal, but it stays on occupations={chosen}: "
            f"{obstacle}."
        )
    return (
        f"{_CLASSIFIER_CALLS_INSULATORS_METALS} Setting is_metal=non_metal alone "
        f"would keep occupations={chosen}: {obstacle}."
    )
