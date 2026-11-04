"""magnetic_config: spin-polarization, starting magnetic moments, and
spin-orbit coupling, combined -- not three independent decisions that can
silently override each other.

New in v2 (v2 epic 5, #5). Fixes two real bugs found in v1's pipeline
(`advice/parameters.py`'s `_advise_magnetism`/`_advise_spin_orbit`,
`generation/qe/scf.py`'s `_spin_lines`), demonstrated here on this fresh
standalone advisor rather than by touching v1's pipeline directly --
same policy as every prior epic in this rewrite (v1 stayed untouched
until cutover, v2 epic 9, which deleted it in commit d64f46b). The two
`tests/physics/test_dft_decisions.py` tests this issue names ("A2"/
"A2b") used to `xfail` against `compute()`, v1's own pipeline
end-to-end, because v1's `advice/parameters.py` and
`generation/qe/scf.py` genuinely never changed; now that v1 is gone,
they exercise `magnetic_config()` directly instead. What this file
actually proves is in `tests/unit/test_advisors_magnetic_config.py`,
against the same physical scenarios (bulk Fe, with and without SOC).

- **A2** (stfc/goldilocks-core#177, still open upstream): v1 emits
  `nspin = 2` with every `starting_magnetization` implicitly zero, so QE
  relaxes to the non-magnetic solution while the run finishes, converges, and
  reports nothing obviously wrong. `spin_polarized=True` here always comes
  with a non-empty `starting_magnetization`.
- **A2b** (found while hardening `physics/` for v2 epic 1, #2): v1's
  `_spin_lines` checks `spin_orbit.enabled` first and returns before ever
  looking at `magnetism.spin_polarized` -- so enabling SOC on a structure
  independently advised as magnetic silently produces a non-magnetic
  noncollinear run. Here, spin-orbit coupling and magnetism are two
  independent fields on one result; enabling SOC never clears
  `starting_magnetization`, and a magnetic, SOC-enabled result also carries
  `angle1`/`angle2` (the moment direction QE's noncollinear mode needs, see
  below) -- SOC without magnetism only happens when the structure is
  genuinely non-magnetic, not because one flag silently overrode the other.

Also corrects a stricter-than-QE constraint the design doc's own audit found
elsewhere in itself (goldilocks-qe-pw-parameter-audit.md P0 finding #2):
giving both `tot_magnetization` and `starting_magnetization` does not error
in QE (`INPUT_PW`'s "do not specify both" is a recommendation, not an
enforced constraint -- verified against QE 7.3's `PW/src/input.f90`). Both
are accepted here as independent, unrelated overrides; this advisor never
treats supplying both as a blocking error.

**Spin mode (#146).** ``MagneticConfigFacts.spin_mode`` is the spin
treatment pw.x runs, derived from the two switches: ``noncollinear``
whenever spin-orbit coupling is on (``noncolin``, which pw.x runs with
nspin=4 and lsda off, magnetic or not -- QE 7.3 ``PW/src/input.f90:714-736``),
otherwise ``collinear`` for a spin-polarized run (nspin=2), otherwise
``none``. The gate, the occupations advisor, the writer and the job's spin
layout read it. ``tot_magnetization`` belongs to the collinear mode only:
pw.x stops on it without nspin=2 (``input.f90:761-762``). An explicit
``spin_polarized=false`` drops a requested one with the ignored warning,
with or without spin-orbit coupling; otherwise spin-orbit coupling refuses
it (``Blocked``), since the starting magnetization alone sets a
noncollinear run's moments. The admitted value is the human request; the
moment the input renders is the occupations decision's
(``advisors/occupations.py``), which adds 0 under fixed occupations for an
ordering ``MagneticConfigFacts.compensated`` says has no net moment (#138).

**Moment direction (#172).** A magnetic noncollinear run -- spin-orbit
coupling on a spin-polarized run -- starts every moment along one
direction, a physical choice: magnetocrystalline anisotropy, orbital
moments and band splittings depend on it. ``MagneticCell.moment_direction``
records it as a lattice direction [uvw] of the uploaded cell: a human
``moment_direction``, else [001] (source ``heuristic``), with the info
notice ``magnetic.soc_moment_direction_defaulted``. The default is a
crystal direction, so it means the same however the cell is oriented; for
a CIF read by pymatgen (c along z) it is QE's own default, +z. The
starting moments are written along it: ``magnetic_config`` converts it to
QE's ``angle1``/``angle2`` for the cell as written
(``MagneticCell.moment_axis``), and ``advisors/n_irr_k.py`` counts the
k-points with the same moments. Any other run ignores a
``moment_direction`` with the warning ``magnetic.moment_direction_ignored``.

**A Hubbard U on an odd shell (#147).** QE's Dudarev potential is
U(1/2 - n_sigma) per spin (QE 7.3 ``PW/src/v_of_rho.f90:771-869``), and a
spin-unpolarized run gives each spin half of the occupation matrix
(``PW/src/new_ns.f90:126``). An odd d or f count -- Cu2+ d9 -- then leaves
a fractional count per spin (4.5) that fills no whole orbital, so +U can
neither form the moment nor open the gap, and pw.x converges to the wrong
state without complaint. So when the Hubbard decision applies a U to an
element whose d or f count (``local_moments``' ``shell_counts``) is odd,
spin polarization is on, over a spin-unpolarized answer of the llm or of
``is_magnetic`` (whose classifier called tenorite CuO non-magnetic), with
the warning ``magnetic.spin_polarized_for_hubbard_open_shell`` naming the
elements and the answer overridden. A human ``spin_polarized`` still
wins. The rule reads the count, not "U implies nspin=2": low-spin Co3+ d6
in LiCoO2 keeps a non-magnetic answer, and so does an element whose count
``local_moments`` cannot fix (no anion, or no oxidation-state guess).
``unpolarized_if_non_magnetic`` says whether the answer
is_magnetic=non_magnetic gives a run no spin polarization by these rules,
which the phonon tasks' metallicity rule in ``checks.py`` reads (#215).

**Two steps, around pseudopotential selection (#128).** ``magnetic_cell``
decides what selection depends on, and the simulated cell: spin
polarization, spin-orbit coupling (selection reads it for the relativistic
requirement), and the magnetic ordering applied to the structure -- the
only enumlib call. ``magnetic_config`` then sets the starting moments on
that cell, scaled by the selected pseudopotentials' ``z_valence``. Each
runs once per calculation (``service/_magnetic.py``), and everything
downstream -- electron count, bands, k-points, convergence, resources and
the writer -- reads the one cell object, so no count can describe a
different cell from the one written.

**Antiferromagnetic orderings (v2 epic 9, #9)**: the cell is the input
`structure` unless a caller explicitly opts in with
`human.magnetic_ordering` `"afm"` or a listed `"afm-<n>"`. Any
`magnetic_ordering`, `"fm"` included, makes the run spin-polarized whatever
`is_magnetic` says (an explicit `spin_polarized=false` still wins, with the
warning `magnetic.ordering_ignored_spin_polarized_false`, #145, #170) --
the ordering itself is opt-in, not a new
default, for the same reason SOC stays opt-in below (real cost: this calls
out to `pymatgen.analysis.magnetism.analyzer.MagneticStructureEnumerator`,
which shells out to the external `enumlib` executables and can take
seconds, not milliseconds; it runs on a worker process in a private
directory, see `advisors/magnetic_enumeration.py`, #136). Finding which
magnetic configuration is the true ground state needs comparing several SCF
total energies -- explicitly an agent-level job in the design doc
(goldilocks-core-design.md:2076), not something this stateless, single-call
heuristic tier can or should attempt. What this tier gives instead is a
*reasonable, deterministic* compensated ordering, useful as a real starting
point for a human/agent to actually run and compare against the plain
ferromagnetic guess. Only the sublattice is seeded and compensated: the
elements `analysis/local_moments.py` says carry a local d or f moment, so
closed-shell La3+ in La2CuO4 and the induced moment of Pt in FePt never
carry the opposing spin (#143).

The candidates are numbered `afm-1`, `afm-2`, ... in one canonical order
(`_canonical_order`: smallest cell first, then most symmetric), the same
order `enumerate_magnetic_orderings` lists them in, and `"afm"` applies
`afm-1` -- which can be a different cell from the input: NiO's 2-atom
primitive cell becomes the 4-atom AFM-II cell. A listed candidate is
generated by its label on the listed structure, so a listing and a run
cannot seed or count one cell differently (#170). `OrderingRecord` states
why the applied candidate was written -- `smallest_cell` for `"afm"`,
`requested` for a label -- and names the other candidates of its size, as
does the `magnetic.afm_ordering_applied` notice (#144); ranking by mMACE
energy stays on the listing path (#87), since one ranking takes minutes.
`"afm"` degrades back to
the FM identity pass-through, with a warning naming why, whenever no site
carries a local moment (`magnetic.afm_no_open_shell_sites`), the sublattice
cannot be decided, enumlib is missing, the primitive cell has more magnetic
sites than a small ceiling, enumlib finds no ordering or runs out of time,
no compensated ordering exists at all, or every one repeats across the
vacuum (below); a label the enumeration does not produce is `Blocked` with
the same reason. Any other enumeration error propagates. See
`_afm_candidates` below.

**Vacuum (#144).** enumlib orders the whole periodic cell, so on a slab it
also offers cells that repeat the structure across the vacuum: the GdI2
monolayer's first candidate doubled c, every sheet ferromagnetic and its
only antiparallel Gd 19.94 A away across the vacuum, and others stack the
next sheet with an in-plane shift (a lattice holding c + a, not c). A
candidate is kept only if its lattice has a basis holding every vacuum
vector of the input (`analysis.geometry.vacuum_axes`: one for a slab, two
for a wire, three for a molecule in a box, whose cell then stays the
input's), and it is written in that basis: each vacuum vector at its own
index, the other vectors moved along it into the plane of the rest of the
input's vectors, the input's handedness, the sites where they were
(`_with_vacuum_vectors`). The written cell then has the input's vacuum
axes, widths and slab, so the decisions that read the vacuum of the
uploaded structure (vc-relax's `cell_dofree`, local-TF mixing) and those
that read the written cell (the k-point along the vacuum, the 'slab',
'isolated' and `fix_bottom_layers` gates, the slab writer, the dipole
notice) see one slab. A structure without vacuum keeps every candidate, so
a bulk van der Waals magnet keeps its interlayer orderings.

**Species (#170).** The cell holds one species per element and
starting-magnetization class (`advisors/species_split.py`): the class of a
site is the value a human `starting_magnetization` requests for it, else
its heuristic spin sign -- +1 for the ferromagnetic default, the enumerated
sign on an applied ordering's sublattice and 0 on its other sites. The
split happens here, before `symmetry_eff` and `n_irr_k` are counted, so
they see the species pw.x is given; the writer renders them unchanged.

**Requested seeds (#185).** A human `starting_magnetization` is keyed by
the site labels of the cell it applies to -- the input's, or an applied
ordering's sublattice labels (`Ni1`/`Ni2`/`O`), listed as
`MagneticCell.site_labels` whether or not the run is spin-polarized -- or
by an element symbol, shorthand for all of that element's sites. An
element key is refused where an applied ordering seeds that element's
sites differently, the ambiguity #46 refused every element key for; a
label beats its element. The request is merged onto the computed seeds
site by site, so a site it leaves out keeps its own seed, and
`MagneticCell.human_seeded_labels` names the species it set
(`_requested_seeds`). Whether the applied ordering is compensated
(`MagneticConfigFacts.compensated`) is decided by `magnetic_config` on the
seeds as written, to rounding, not on the species classes, which hold
requested values and spin signs on two scales (`_compensated`).

**The written frame (#140).** pw.x finds symmetry by testing fixed
Cartesian rotations against the cell as written, so `framed_cell` -- the
last part of the cell step, run by `service/_magnetic.py` -- writes the
split cell in the frame where pw.x keeps the most of its point group
(`pw_symmetry.pw_frame`): idealized, and turned rigidly or with its origin
moved when that is what it takes; a slab with its vacuum along c is always
turned so that a lies along +x, a and b in the xy plane and c above it,
which costs a sheet the in-plane axes pw.x cannot represent there.
The lattice basis stays, so `cell_in_input_basis` stays, and the moment
direction, a crystal direction, turns with the cell. `MagneticCell.frame`
records the frame; the notice `magnetic.cell_framed` names it when the
cell was turned or shifted or an atom moved by 1e-4 A or more.

SOC stays opt-in, matching v1's own policy: `needs_soc` only ever produces a
notice, never enables it automatically -- enabling SOC changes cost and
setup, which is a human's call. The notice follows the table selection
spin-orbit coupling would make (`soc_table`, from
`service._pseudo.soc_pseudo_table`), so it never recommends a setting the
selector refuses (#181): `magnetic.soc_suggested` names the fully
relativistic table that selection picks, and `magnetic.soc_unavailable`
keeps the caveat and carries the selector's refusal -- for every
lanthanide and actinide (SSSP only, and no SSSP table is fully
relativistic) and under a functional with no fully relativistic table
(LDA). Without a verdict there is no notice.

**`starting_magnetization` follows aiida-quantumespresso's own convention**
(`aiida_quantumespresso.workflows.protocols.utils.get_magnetization`, used by
`PwBaseWorkChain.get_builder_from_protocol(..., spin_type=SpinType.COLLINEAR)`;
see also the "Magnetic configurations" tutorial), not an invented flat
fraction: QE's `starting_magnetization` is defined as a species' spin
polarization -- a fraction of that species' pseudopotential valence electron
count, in [-1, 1] -- so the physically-motivated value is
``target_moment_in_bohr_magnetons / z_valence``, not one constant for every
element. `_MAGNETIC_MOMENT_TARGETS` below is aiida-quantumespresso's own
per-element table verbatim (elements with a partially-occupied d/f shell get
an aggressive maximal-moment target -- 5 or 7 Bohr magnetons -- to reliably
break spin symmetry; everything else gets 0, which maps to the flat
`DEFAULT_MAGNETIZATION_FRACTION` below). Every species gets an entry when
spin-polarized: the seed is the species' class times its element's
fraction (`_seeds`). In the ferromagnetic default every element is seeded
positive, not just the moment-bearing `magnetic_elements` -- aiida does
the same, so that no single species sits at exactly zero and re-locks the
spin symmetry the rest of the structure is trying to break. An applied
ordering breaks that symmetry with its compensated sublattice, and its
other species start at 0, as in QE's own antiferromagnetic references
(QE 7.3 `HP/examples/example02/reference/NiO.scf1.in`,
`PW/examples/example08/reference/feo_LDA.in`), so a compensated start
carries no net seed (#170).

Computing the real, calibrated fraction needs `z_valences` (each element's
*chosen pseudopotential's* valence electron count -- not a textbook/nominal
count, real UPF files vary, e.g. whether semicore states are included).
`pseudo_selection.py` picks that pseudopotential, and picking it needs
`spin_orbit_enabled` from *this* file (for the relativistic requirement) --
which is why the decision is the two steps above: `magnetic_config` takes
`z_valences` once selection has happened. Without them (no table installed
yet), every element still gets `DEFAULT_MAGNETIZATION_FRACTION` (aiida's own
flat default, not this package's invention) rather than either guessing a
`z_valence` or leaving `starting_magnetization` empty -- the latter would
silently reopen A2. The same `z_valences` turn the seeds back into the net
moment they start from, `MagneticConfigFacts.seeded_moment` in Bohr
magnetons, which sizes a collinear smearing run's majority spin channel
(`advisors/nbnd.py`, #131); without them that moment is unknown.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Annotated, Literal, NamedTuple

import numpy as np
import spglib
from pydantic import Field, field_validator
from pymatgen.core import Lattice, Structure
from pymatgen.symmetry.groups import SpaceGroup

from goldilocks_core.advisors.hubbard_u import HubbardUDecision
from goldilocks_core.advisors.magnetic_enumeration import (
    enumerate_orderings,
    enumlib_installed,
)
from goldilocks_core.advisors.species_split import split_species
from goldilocks_core.analysis.geometry import LATTICE_AXES, vacuum_axes
from goldilocks_core.analysis.is_magnetic import Magnetism
from goldilocks_core.analysis.local_moments import LocalMomentFacts, local_moments
from goldilocks_core.analysis.symmetry import SYMPREC
from goldilocks_core.assets.pseudopotentials.registry import PseudoTable
from goldilocks_core.inputs.overrides import HumanInput, LlmInput
from goldilocks_core.pw_symmetry import PwFrame, pw_frame
from goldilocks_core.resolution import (
    Blocked,
    FieldState,
    Provenance,
    Resolved,
    Source,
    Unavailable,
    Warning,
    blocked_by,
    field_sources_from,
)

_MAX_MAGNETIC_SITES_FOR_AFM_ENUMERATION = 8
"""The most sublattice sites (``_afm_sublattice``) in the primitive cell an
antiferromagnetic search enumerates orderings for (#171). pymatgen reduces
the input to its primitive cell and hands enumlib only the magnetic sites,
so they, not the atom count, drive the cost: 16 seeded sites took 18 s
(alpha-Pu) and 46 s (Lu2O3, every Lu seeded), while the 4 Fe of 28-site
LiFePO4 and the one Fe of a 54-site FeO supercell took under 2 s. At 8,
pymatgen's own limit of 8 symmetry-distinct magnetic sites is never
reached."""

_ENUMLIB_TIMEOUT_MINUTES = 0.5
"""enumlib's time limit per call, in pymatgen's unit (minutes; its default
is 5), sized for an interactive request (#171)."""

_ORDERING_PATTERN = r"^(fm|afm|afm-[1-9][0-9]*)$"
"""``magnetic_ordering``'s values: the ferromagnetic default, the first
antiferromagnetic candidate, or one listed candidate by its label."""

_LATTICE_TOLERANCE = 1e-5
"""Largest distance from an integer of a vacuum vector's coordinates in a
candidate's lattice basis for it to count as a lattice vector (#144).
pymatgen builds each candidate's lattice from integer combinations of the
primitive cell's, so the coordinates of a vector the lattice holds are
integers to rounding error."""

_SEED_TOLERANCE = 1e-6
"""How far apart two starting magnetizations, as fractions of the valence
charge, may be and still count as equal or opposite in ``_compensated``:
rounding only (#185). A seed copied to six significant digits or more
(the input writes twelve, #178) restates the computed one; a hand-rounded
(0.28 for Ni's 5/18) or deliberately different value does not. Left to
spglib, the seeds would be compared at its ``symprec``, ``SYMPREC``, a
length in Angstrom: seeds within 0.01 of opposite, or a parallel start
below 0.005, would count as compensated."""

_ENUMLIB_FOUND_NO_ORDERING = "Unable to enumerate"
"""The message of the ``ValueError`` pymatgen's
``EnumerateStructureTransformation`` raises when enumlib finds no ordering
at any cell size it tries (it re-raises enumlib's ``EnumError`` as this)."""

DEFAULT_MAGNETIZATION_FRACTION = 0.1
"""aiida-quantumespresso's own flat default for elements with no specific
moment target (`magnetization.yaml`'s `default_magnetization`) -- also the
fallback for every element when `z_valences` isn't available at all, so
`starting_magnetization` is never empty on a spin-polarized result (A2)."""

_MAGNETIC_MOMENT_TARGETS: dict[str, float] = {
    "Ac": 5,
    "Ce": 5,
    "Co": 5,
    "Cr": 5,
    "Dy": 7,
    "Er": 7,
    "Eu": 7,
    "Fe": 5,
    "Gd": 5,
    "Hf": 5,
    "Ho": 7,
    "Ir": 5,
    "La": 5,
    "Lu": 5,
    "Mn": 5,
    "Mo": 5,
    "Nb": 5,
    "Nd": 7,
    "Ni": 5,
    "Np": 5,
    "Os": 5,
    "Pa": 5,
    "Pm": 7,
    "Pr": 7,
    "Pt": 5,
    "Pu": 7,
    "Re": 5,
    "Rh": 5,
    "Ru": 5,
    "Sc": 5,
    "Sm": 7,
    "Ta": 5,
    "Tb": 7,
    "Tc": 5,
    "Th": 5,
    "Ti": 5,
    "Tm": 7,
    "U": 5,
    "V": 5,
    "W": 5,
    "Y": 5,
    "Zr": 5,
}
"""Target initial magnetic moment (Bohr magnetons) per element, for elements
with a partially-occupied d or f shell -- an aggressive "aim for the maximal
possible moment" guess to reliably break spin symmetry, not a physical
prediction (ported verbatim from aiida-quantumespresso's
`workflows/protocols/magnetization.yaml`, itself a per-element, not a
per-oxidation-state, table). Every element not listed here has no specific
target and falls back to `DEFAULT_MAGNETIZATION_FRACTION`; notably this
includes Cu/Zn (filled or near-filled d-shell as a neutral element) despite
both being `is_transition_metal` in `analysis/composition.py`."""

SpinMode = Literal["none", "collinear", "noncollinear"]

OrderingCriterion = Literal["identity", "smallest_cell", "requested"]
"""Why ``OrderingRecord.applied`` is the cell written (#144): ``identity``,
the input kept; ``smallest_cell``, plain ``afm``'s pick, the first listed
candidate; ``requested``, the listed label asked for."""

_NONCOLLINEAR_TOT_MAGNETIZATION = (
    "tot_magnetization is not valid with spin_orbit_coupling: a spin-orbit run "
    "is noncollinear, and pw.x accepts tot_magnetization only for a collinear "
    "spin-polarized run (nspin=2); drop tot_magnetization and set the moments "
    "with starting_magnetization, or turn spin_orbit_coupling off."
)

_MAGNETIZATION_IGNORED_WARNING = Warning(
    code="magnetic.magnetization_ignored_spin_polarized_false",
    level="warning",
    category="magnetic",
    message=(
        "tot_magnetization/starting_magnetization were given but "
        "spin_polarized is explicitly false; both are ignored."
    ),
)

_ORDERING_IGNORED_WARNING = Warning(
    code="magnetic.ordering_ignored_spin_polarized_false",
    level="warning",
    category="magnetic",
    message=(
        "a magnetic_ordering was given but spin_polarized is explicitly "
        "false; the ordering is ignored and the run is not spin-polarized."
    ),
)

_SOC_SUGGESTED = (
    "heavy, non-s-block elements are present; consider enabling "
    "spin_orbit_coupling (not enabled automatically -- it changes cost and setup)"
)

_SOC_UNAVAILABLE = (
    "heavy, non-s-block elements are present, where spin-orbit coupling can "
    "matter, but spin_orbit_coupling cannot be enabled for them with this "
    "functional and the registered pseudopotential tables"
)

_MOMENT_DIRECTION_DEFAULTED_WARNING = Warning(
    code="magnetic.soc_moment_direction_defaulted",
    level="info",
    category="magnetic",
    message=(
        "the moments of this spin-orbit run start along [0 0 1] of the "
        "uploaded cell (its third lattice vector). The direction is a "
        "physical choice -- magnetic anisotropy, orbital moments and band "
        "splittings depend on it -- not a converged default; set "
        "moment_direction to a lattice direction [u, v, w] of the uploaded "
        "cell to choose another."
    ),
)

_MOMENT_DIRECTION_IGNORED_WARNING = Warning(
    code="magnetic.moment_direction_ignored",
    level="warning",
    category="magnetic",
    message=(
        "moment_direction was given but only a spin-polarized run with "
        "spin_orbit_coupling has a moment direction; it is ignored."
    ),
)

_SEED_IT_YOURSELF = (
    "set starting_magnetization per site label, on a cell whose labels "
    "separate the sublattices, to seed an ordering yourself"
)

_NO_OPEN_SHELL_SITES_WARNING = Warning(
    code="magnetic.afm_no_open_shell_sites",
    level="warning",
    category="magnetic",
    message=(
        "no site carries a local d or f moment, so there is no "
        "antiferromagnetic ordering to apply; only ferromagnetic order is "
        f"available. To change that, {_SEED_IT_YOURSELF}."
    ),
)

_FRAME_NOTICE_ANGSTROM = 1e-4
"""Idealization that moves an atom or lattice vector by this much or more
earns the ``magnetic.cell_framed`` notice (#140). CIF rounding moves most
cells by about 1e-5 A, which would make the notice fire on almost every
run."""

_CELL_FRAMED = "magnetic.cell_framed"

_HUBBARD_OPEN_SHELL = "magnetic.spin_polarized_for_hubbard_open_shell"

WARNING_CATALOGUE = (
    Warning(
        code="magnetic.soc_suggested",
        level="info",
        category="magnetic",
        message=(
            f"{_SOC_SUGGESTED}; with it, automatic selection uses the named "
            "fully relativistic table."
        ),
    ),
    Warning(
        code="magnetic.soc_unavailable",
        level="info",
        category="magnetic",
        message=(
            f"{_SOC_UNAVAILABLE}: the table selector's refusal names what "
            "rejected each table."
        ),
    ),
    Warning(
        code="magnetic.magnetism_unknown_defaulted_spin_polarized",
        level="warning",
        category="magnetic",
        message="magnetism could not be determined; defaulted to spin-polarized.",
    ),
    Warning(
        code=_HUBBARD_OPEN_SHELL,
        level="warning",
        category="magnetic",
        message=(
            "a Hubbard U acts on an odd d or f electron count, which only a "
            "spin-polarized run can polarize; spin polarization is turned on "
            "over the llm's or is_magnetic's spin-unpolarized answer."
        ),
    ),
    Warning(
        code="magnetic.afm_ordering_unavailable",
        level="warning",
        category="magnetic",
        message=(
            "antiferromagnetic ordering was requested but could not be "
            "produced; kept ferromagnetic order."
        ),
    ),
    _NO_OPEN_SHELL_SITES_WARNING,
    Warning(
        code="magnetic.afm_ordering_applied",
        level="info",
        category="magnetic",
        message=(
            "an antiferromagnetic ordering (opposite starting moments on the "
            "sites with a local moment) was found and applied: the label, why "
            "it was picked and the other listed candidates of its size are "
            "named; the input is written for its cell, which can differ from "
            "the uploaded one."
        ),
    ),
    _MAGNETIZATION_IGNORED_WARNING,
    _ORDERING_IGNORED_WARNING,
    _MOMENT_DIRECTION_DEFAULTED_WARNING,
    _MOMENT_DIRECTION_IGNORED_WARNING,
    Warning(
        code=_CELL_FRAMED,
        level="info",
        category="magnetic",
        message=(
            "the cell is written turned rigidly, with its origin moved, or "
            "idealized to its space group, in the frame where pw.x, which tests "
            "fixed Cartesian rotations only, keeps the most of its symmetry "
            "operations (a slab with its vacuum along c always with a along "
            "+x); the rotation, shift, largest displacement and number of "
            "operations kept are named and recorded as magnetic.frame."
        ),
    ),
)
"""Every warning code this module can emit -- ``capabilities.py``'s
``warnings[]`` catalogue aggregates one of these tuples per advisor. The
real, per-occurrence messages for
``magnetic.magnetism_unknown_defaulted_spin_polarized``,
``magnetic.spin_polarized_for_hubbard_open_shell``,
``magnetic.afm_ordering_unavailable``, ``magnetic.cell_framed`` and the
two spin-orbit notices name the actual reason (built at their call sites
in ``_resolve_spin_polarized``, ``_hubbard_spin``, ``_afm_unavailable``,
``_frame_notice`` and ``_soc_notice`` below); these are the generic
descriptions, for a caller that has not seen them fire."""


@dataclass(frozen=True, slots=True)
class OrderingRecord:
    """The magnetic ordering asked for (``None`` when
    ``magnetic_ordering`` is unset, which keeps the input cell and, unlike
    an explicit ``"fm"``, leaves spin polarization to the classifier) and
    the one applied: the label of the antiferromagnetic candidate that replaced
    the input cell (``"afm-1"`` for ``"afm"``), as the listing numbers it,
    otherwise ``"fm"`` -- the input cell kept (the FM identity
    pass-through). ``None`` for a run without spin polarization, which
    applies no ordering and keeps the input cell: ``magnetic_ordering``
    resolves here, and any value of it asks for spin polarization (#187).

    ``criterion`` says why ``applied`` was written and ``alternatives``
    lists the other candidates with as many sites, by label (#144); the
    defaults are the FM identity's. Whether the applied ordering is
    compensated depends on the seeds, so it is
    ``MagneticConfigFacts.compensated``, not part of this record (#185)."""

    requested: str | None
    applied: str | None
    criterion: OrderingCriterion = "identity"
    alternatives: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MomentDirection:
    """The direction every moment of a magnetic noncollinear run starts
    along (module docstring, #172): ``uvw``, a lattice direction of the
    uploaded cell, from a human ``moment_direction`` (``source`` human) or
    the default [001] (``source`` heuristic)."""

    uvw: tuple[float, float, float]
    source: Literal["human", "heuristic"]


@dataclass(frozen=True, slots=True)
class MagneticCell:
    """The simulated cell and the spin decisions taken before
    pseudopotential selection (module docstring).

    ``structure`` is the input structure, or the applied antiferromagnetic
    candidate (possibly a different cell), split into species
    (``split_species``, module docstring): each site's label is its
    species label (``Ni1``/``Ni2``/``O``), and in a spin-polarized cell
    each site's ``Species.spin`` is its starting-magnetization class -- the
    human value of its label, else the heuristic sign (+1, -1 or 0).
    ``cell_in_input_basis`` is its
    lattice in the input's basis, rows being lattice vectors:
    ``structure.lattice.matrix == cell_in_input_basis @ input.lattice.matrix
    @ R.T``, with R the rotation of ``frame`` (the identity until
    ``framed_cell`` writes the cell in pw.x's frame) and equality to within
    the frame's idealization. That is an integer supercell matrix for a
    primitive input, but fractional when enumeration reduced a conventional
    input to a smaller cell (determinant 1/2 for rock-salt's 8-atom cell).

    ``frame`` is how ``framed_cell`` wrote ``structure`` in pw.x's frame
    and how many operations pw.x keeps there (``pw_symmetry.pw_frame``,
    #140); ``None`` before.

    ``magnetic_elements`` is the antiferromagnetic sublattice: the
    elements ``local_moments`` says carry a local d or f moment, empty when
    it cannot decide or the run is not spin-polarized (#143).

    ``tot_magnetization`` is the human request admitted for this run: set
    only for a collinear spin-polarized run (module docstring, #146). The
    rendered moment is ``OccupationsDecision.tot_magnetization`` (#138).

    ``moment_direction`` is set exactly when the run is spin-polarized with
    spin-orbit coupling (module docstring, #172).

    ``site_labels`` are the labels a human ``starting_magnetization`` is
    keyed by, in site order (module docstring, #185): the input's, or an
    applied ordering's sublattice labels; the input's when the run is not
    spin-polarized. ``human_seeded_labels`` are the species labels of
    ``structure`` whose class is a requested value, not a spin sign."""

    structure: Structure
    spin_polarized: bool
    spin_orbit_enabled: bool
    magnetic_elements: tuple[str, ...]
    ordering: OrderingRecord
    cell_in_input_basis: tuple[tuple[float, ...], ...]
    tot_magnetization: float | None
    moment_direction: MomentDirection | None = None
    frame: PwFrame | None = None
    site_labels: tuple[str, ...] = ()
    human_seeded_labels: tuple[str, ...] = ()
    warnings: tuple[Warning, ...] = ()

    @property
    def moment_axis(self) -> np.ndarray | None:
        """``moment_direction`` as a Cartesian unit vector of ``structure``
        as written, ``None`` without one. [uvw] in the input's basis is
        ``f`` with ``f @ cell_in_input_basis == [uvw]`` in the cell's
        basis, then ``f @ structure.lattice.matrix`` (scaled by its largest
        component first, so no size of [uvw] under- or overflows). This
        holds for any written frame whose lattice is ``cell_in_input_basis
        @ input lattice`` turned rigidly, so the moment turns with the frame
        ``framed_cell`` writes (#140)."""
        if self.moment_direction is None:
            return None
        uvw = np.array(self.moment_direction.uvw)
        fractional = np.linalg.solve(
            np.array(self.cell_in_input_basis).T, uvw / np.abs(uvw).max()
        )
        cartesian = fractional @ self.structure.lattice.matrix
        return cartesian / np.linalg.norm(cartesian)


@dataclass(frozen=True, slots=True)
class MagneticConfigFacts:
    """The magnetic decision the writer renders. ``cell``, ``ordering``,
    ``spin_polarized``, ``magnetic_elements``, ``tot_magnetization``,
    ``spin_orbit_enabled`` and ``moment_direction`` are copied from the
    ``MagneticCell`` (``cell`` is the same object as
    ``MagneticCell.structure``), and so are ``frame``, the record of how
    the cell is written (#140), and ``site_labels`` and
    ``human_seeded_labels``, the keys a ``starting_magnetization`` takes
    and the species it set (#185); ``warnings`` are the cell's plus this
    step's. ``angle1``/``angle2`` are QE's angles of the moment direction
    (``_angles``), one per species, set with it.

    ``compensated``: the applied antiferromagnetic ordering, seeded with
    ``starting_magnetization``, has an operation that maps every site onto
    one of the same element with the opposite seed (``_compensated``), so
    its net moment is zero by symmetry (#138). Decided here, on the seeds
    as written, to rounding: a requested value restates a computed seed
    only once the z_valences fix that seed (#185). False for ``"fm"`` and
    for a run without spin polarization.

    ``seeded_moment`` is the net moment the starting magnetization seeds,
    in Bohr magnetons per cell: each site's ``starting_magnetization``
    times its element's ``z_valence``, summed over ``cell``
    (``_seeded_moment``). ``None`` without seeds (a run without spin
    polarization) or without a z_valence for every element. ``nbnd``
    sizes the majority spin channel of a collinear smearing run from it
    (#131)."""

    cell: Structure
    ordering: OrderingRecord
    spin_polarized: bool
    magnetic_elements: tuple[str, ...]
    starting_magnetization: dict[str, float] | None
    compensated: bool
    tot_magnetization: float | None
    spin_orbit_enabled: bool
    angle1: dict[str, float] | None
    angle2: dict[str, float] | None
    seeded_moment: float | None = None
    moment_direction: MomentDirection | None = None
    frame: PwFrame | None = None
    site_labels: tuple[str, ...] = ()
    human_seeded_labels: tuple[str, ...] = ()
    warnings: tuple[Warning, ...] = ()

    @property
    def spin_mode(self) -> SpinMode:
        """``noncollinear`` with spin-orbit coupling, otherwise
        ``collinear`` when spin-polarized, otherwise ``none`` (module
        docstring). Derived from the two switches, so it cannot disagree
        with them; a property, not a field, so records do not carry it."""
        if self.spin_orbit_enabled:
            return "noncollinear"
        return "collinear" if self.spin_polarized else "none"


_Fraction = Annotated[float, Field(gt=-1.0, lt=1.0)]
"""A starting magnetization as a fraction of the species' valence charge.
From QE 7.3 a value of magnitude 1 or more turns every species' value into
a moment in Bohr magnetons, divided by its valence
(``PW/src/input.f90:1441-1442``), so the bounds are exclusive."""


class MagneticConfigHumanInput(HumanInput):
    spin_polarized: bool | None = None
    spin_orbit_coupling: bool | None = None
    tot_magnetization: float | None = None
    starting_magnetization: dict[str, _Fraction] | None = None
    """A final, already-QE-scale fraction per key, strictly between -1 and 1
    -- not a moment in Bohr magnetons -- matching aiida-quantumespresso's
    "Using the parameters" path (direct
    `parameters['SYSTEM']['starting_magnetization']`), as opposed to its
    "Using the SpinType" path (a physical moment scaled by `z_valences`,
    which is what the heuristic tier below does). A key is a site label of
    the cell it applies to -- the input's, or an applied ordering's
    sublattice labels (``Ni1``/``Ni2``/``O``), ``MagneticCell.site_labels``
    -- or an element symbol, for all of that element's sites, refused where
    an applied ordering seeds them differently; a label beats its element.
    Sites it leaves out keep their computed seeds, and the cell is split by
    these values (module docstring, ``_requested_seeds``, #185)."""
    magnetic_ordering: str | None = Field(default=None, pattern=_ORDERING_PATTERN)
    """Opt-in only (unset, the input cell is kept and spin polarization is
    left to the classifier): stays off by default because attempting an
    antiferromagnetic ordering calls out to an external process and can
    take seconds, and because which
    ordering is *actually* the ground state is not something this module
    can determine on its own -- see the module docstring. ``"afm"`` applies
    the first listed candidate, the smallest cell and the most symmetric of
    its size, ``"afm-<n>"`` the listed candidate of that label (#170, #144),
    ``"fm"`` the input cell. Each is a request for a spin-polarized run, like
    the two magnetization keys (#145): ``"fm"`` too, so the listing's
    ferromagnetic candidate generates a ferromagnetic run (#170)."""
    moment_direction: tuple[float, float, float] | None = None
    """The direction the moments of a spin-polarized spin-orbit run start
    along, as a lattice direction [u, v, w] of the uploaded cell (module
    docstring, #172); not the zero vector. Ignored, with a warning, by any
    other run."""

    @field_validator("moment_direction")
    @classmethod
    def _nonzero_direction(
        cls, value: tuple[float, float, float] | None
    ) -> tuple[float, float, float] | None:
        if value is not None and not any(value):
            raise ValueError("moment_direction must be a non-zero direction [u, v, w]")
        return value


class MagneticConfigLlmInput(LlmInput):
    spin_polarized: bool | None = None
    spin_orbit_coupling: bool | None = None


def magnetic_cell(
    structure: Structure,
    is_magnetic: FieldState[Magnetism],
    human: MagneticConfigHumanInput | None = None,
    llm: MagneticConfigLlmInput | None = None,
    *,
    hubbard: FieldState[HubbardUDecision] | None = None,
) -> FieldState[MagneticCell]:
    """The simulated cell (module docstring): spin polarization,
    spin-orbit coupling, the admitted ``tot_magnetization``, the moment
    direction (#172), and ``structure`` with the requested ordering
    applied -- the one enumeration of a calculation -- split into species.
    ``hubbard``, the run's Hubbard decision, turns spin polarization on
    where it applies a U to an odd d or f count (``_hubbard_spin``, #147);
    ``None`` or an unresolved decision applies no U. ``Blocked`` when
    ``is_magnetic`` is, when a human ``tot_magnetization`` comes with
    spin-orbit coupling (#146), when ``magnetic_ordering`` names a
    candidate the enumeration does not produce (#170), when a human
    ``starting_magnetization`` has a key outside its domain
    (``_requested_seeds``, #185). The provenance names, per setting, who
    decided it (``_provenance``, #173)."""
    human = human or MagneticConfigHumanInput()
    llm = llm or MagneticConfigLlmInput()

    if isinstance(is_magnetic, Blocked):
        # Blocked (something upstream of is_magnetic failed) is not the same
        # as Unavailable (the heuristic tried and could not tell) -- only
        # the former leaves nothing safe to default to.
        return Blocked(by=is_magnetic)

    spin = _hubbard_spin(
        _resolve_spin_polarized(is_magnetic, human, llm),
        structure,
        is_magnetic,
        hubbard,
    )
    spin_polarized, warnings = spin.polarized, spin.warnings
    spin_orbit_enabled = human.spin_orbit_coupling is True
    # A requested moment belongs to a spin-polarized run: an explicit
    # spin_polarized=false drops it (the warning above). With spin-orbit
    # coupling the run is noncollinear, where pw.x has none (#146).
    tot_magnetization = human.tot_magnetization if spin_polarized else None
    if tot_magnetization is not None and spin_orbit_enabled:
        return Blocked(by=_NONCOLLINEAR_TOT_MAGNETIZATION)
    direction, direction_warnings = _moment_direction(
        human.moment_direction, magnetic=spin_polarized and spin_orbit_enabled
    )
    warnings = (*warnings, *direction_warnings)
    requested = human.magnetic_ordering

    magnetic_elements: tuple[str, ...] = ()
    if spin_polarized:
        moments = local_moments(structure)
        magnetic_elements = moments.value.moment_elements if moments.ok else ()
        ordered = _ordered(structure, moments, requested or "fm")
        if isinstance(ordered, str):
            return Blocked(by=ordered)
        seeded = _seeded_split(ordered, human.starting_magnetization)
        if isinstance(seeded, str):
            return Blocked(by=seeded)
        ordering = OrderingRecord(
            requested=requested,
            applied=ordered.applied,
            criterion=ordered.criterion,
            alternatives=ordered.alternatives,
        )
        warnings = (*warnings, *ordered.warnings)
    else:
        seeded = _Seeded(split_species(structure, None), _site_labels(structure))
        ordering = OrderingRecord(requested=requested, applied=None)

    facts = MagneticCell(
        structure=seeded.cell,
        spin_polarized=spin_polarized,
        spin_orbit_enabled=spin_orbit_enabled,
        magnetic_elements=magnetic_elements,
        ordering=ordering,
        cell_in_input_basis=_cell_in_input_basis(seeded.cell, structure),
        tot_magnetization=tot_magnetization,
        moment_direction=direction,
        site_labels=seeded.site_labels,
        human_seeded_labels=seeded.human_seeded_labels,
        warnings=warnings,
    )
    return Resolved(facts, _provenance(facts, human, spin))


def _provenance(
    facts: MagneticCell, human: MagneticConfigHumanInput, spin: _SpinChoice
) -> Provenance:
    """The magnetic record's provenance (#173), over the settings ``facts``
    applies: ``spin_polarized`` and ``spin_orbit_coupling`` always; the
    ordering and the starting magnetization on a spin-polarized cell;
    ``tot_magnetization`` and ``moment_direction`` where the cell kept one.
    ``spin_polarized`` reads the tier that decided it, ``derived_from``
    naming ``is_magnetic`` when that fact did, or ``hubbard`` when a U on
    an odd shell did (#147); every other setting reads
    ``human`` when the request set it, else ``heuristic``. No llm input is
    read here: the llm's ``spin_polarized`` is in ``spin.source`` and
    spin-orbit coupling takes the human switch alone."""
    applied = {
        "spin_polarized": True,
        "spin_orbit_coupling": True,
        "magnetic_ordering": facts.spin_polarized,
        "starting_magnetization": facts.spin_polarized,
        "tot_magnetization": facts.tot_magnetization is not None,
        "moment_direction": facts.moment_direction is not None,
    }
    field_sources = field_sources_from(
        human,
        None,
        fields=[name for name, used in applied.items() if used],
        decided={"spin_polarized": spin.source},
    )
    return Provenance.from_field_sources(field_sources, derived_from=spin.derived_from)


def magnetic_config(
    cell: FieldState[MagneticCell],
    needs_soc: FieldState[bool] | None = None,
    soc_table: FieldState[PseudoTable] | None = None,
    z_valences: dict[str, float] | None = None,
) -> FieldState[MagneticConfigFacts]:
    """The starting moments on ``cell``, one per species (``_seeds``): the
    value a human ``starting_magnetization`` gave a species
    (``MagneticCell.human_seeded_labels``, split onto the cell by
    ``magnetic_cell``), else the heuristic fraction, scaled by
    the selected pseudopotentials' ``z_valences`` when known -- with the
    net moment they seed (``_seeded_moment``), the spin-orbit notice
    (``_soc_notice``, from ``needs_soc`` and ``soc_table``, the table
    selection spin-orbit coupling would make), the angles of the cell's
    moment direction (``_angles``) and whether the applied ordering,
    seeded so, is compensated (``_compensated``). Copies the cell's other
    facts, with the cell's provenance; ``Blocked`` when the cell is not
    resolved."""
    if not cell.ok:
        return Blocked(by=blocked_by(cell))
    facts = cell.value

    starting_magnetization = (
        _seeds(facts.structure, z_valences, facts.human_seeded_labels)
        if facts.spin_polarized
        else None
    )
    compensated = (
        starting_magnetization is not None
        and facts.ordering.applied != "fm"
        and _compensated(facts.structure, starting_magnetization)
    )

    warnings = (
        *facts.warnings,
        *_soc_notice(facts.spin_orbit_enabled, needs_soc, soc_table),
    )

    angle1 = angle2 = None
    axis = facts.moment_axis
    if axis is not None and starting_magnetization is not None:
        polar, azimuth = _angles(axis)
        angle1 = dict.fromkeys(starting_magnetization, polar)
        angle2 = dict.fromkeys(starting_magnetization, azimuth)

    config = MagneticConfigFacts(
        cell=facts.structure,
        ordering=facts.ordering,
        spin_polarized=facts.spin_polarized,
        magnetic_elements=facts.magnetic_elements,
        starting_magnetization=starting_magnetization,
        compensated=compensated,
        tot_magnetization=facts.tot_magnetization,
        spin_orbit_enabled=facts.spin_orbit_enabled,
        angle1=angle1,
        angle2=angle2,
        seeded_moment=_seeded_moment(
            facts.structure, starting_magnetization, z_valences
        ),
        moment_direction=facts.moment_direction,
        frame=facts.frame,
        site_labels=facts.site_labels,
        human_seeded_labels=facts.human_seeded_labels,
        warnings=warnings,
    )
    return Resolved(config, cell.provenance)


def _soc_notice(
    spin_orbit_enabled: bool,
    needs_soc: FieldState[bool] | None,
    soc_table: FieldState[PseudoTable] | None,
) -> tuple[Warning, ...]:
    """The spin-orbit notice of a run without spin-orbit coupling whose
    ``needs_soc`` resolved true: ``magnetic.soc_suggested`` naming the
    table when ``soc_table`` resolved, else ``magnetic.soc_unavailable``
    carrying the selector's refusal (#181). None when spin-orbit coupling
    is on, ``needs_soc`` did not resolve true, or no ``soc_table`` was
    given. Automatic selection only resolves or refuses, so an unresolved
    ``soc_table`` is ``Unavailable``."""
    if spin_orbit_enabled or soc_table is None:
        return ()
    if needs_soc is None or not (needs_soc.ok and needs_soc.value):
        return ()
    if isinstance(soc_table, Resolved):
        code = "magnetic.soc_suggested"
        message = (
            f"{_SOC_SUGGESTED}; with it, automatic selection uses the fully "
            f"relativistic table {soc_table.value.id}."
        )
    else:
        code = "magnetic.soc_unavailable"
        message = f"{_SOC_UNAVAILABLE}: {soc_table.reason}"
    return (Warning(code=code, level="info", category="magnetic", message=message),)


def framed_cell(cell: MagneticCell) -> MagneticCell:
    """``cell`` written in the frame where pw.x keeps the most of its
    point group (``pw_symmetry.pw_frame``, #140), with the ``PwFrame``
    recorded and the ``magnetic.cell_framed`` notice added when the cell
    was turned, its origin moved, or an atom or lattice vector moved by
    ``_FRAME_NOTICE_ANGSTROM`` or more. ``cell_in_input_basis`` is kept:
    the frame keeps the lattice basis and turns it rigidly, so
    ``moment_axis`` turns with it."""
    structure, frame = pw_frame(cell.structure)
    warnings = cell.warnings
    if (
        frame.rotated
        or any(frame.origin_shift)
        or frame.max_displacement_angstrom >= _FRAME_NOTICE_ANGSTROM
    ):
        warnings = (*warnings, _frame_notice(frame))
    return replace(cell, structure=structure, frame=frame, warnings=warnings)


def _frame_notice(frame: PwFrame) -> Warning:
    """The ``magnetic.cell_framed`` notice for ``frame``."""
    changes = [frame.describe_rotation()] if frame.rotated else []
    if any(frame.origin_shift):
        shift = ", ".join(f"{value:.6g}" for value in frame.origin_shift)
        changes.append(f"with its origin moved by [{shift}] (crystal coordinates)")
    if frame.max_displacement_angstrom > 0.0:
        changes.append(
            "idealized to its space group, no atom or lattice vector moving more "
            f"than {frame.max_displacement_angstrom:.2g} Å"
        )
    turned = (
        " Cartesian cell_dofree masks would not, and are refused."
        if frame.rotated
        else ""
    )
    return Warning(
        code=_CELL_FRAMED,
        level="info",
        category="magnetic",
        message=(
            f"the cell is written {', '.join(changes)}; pw.x, which tests fixed "
            f"Cartesian rotations only, keeps {frame.operations} symmetry "
            "operations in it. Fractional "
            "coordinates (up to the origin shift), labels, the k-point grid and "
            f"moment directions keep their meaning.{turned}"
        ),
    )


@dataclass(frozen=True, slots=True)
class _Ordered:
    """What a ``magnetic_ordering`` request resolves to, before the
    species split: ``base`` with the labels a human
    ``starting_magnetization`` is keyed by (the input's own, or an applied
    candidate's sublattice labels), each site's heuristic spin sign, the
    applied label, its ``OrderingRecord`` criterion and alternatives, and
    the ordering's warnings."""

    base: Structure
    signs: tuple[float, ...]
    applied: str
    criterion: OrderingCriterion = "identity"
    alternatives: tuple[str, ...] = ()
    warnings: tuple[Warning, ...] = ()


def _ordered(
    structure: Structure, moments: FieldState[LocalMomentFacts], requested: str
) -> _Ordered | str:
    """``requested`` on a spin-polarized ``structure`` (module docstring):
    the ferromagnetic input with every site positive, or the listed
    antiferromagnetic candidate it names -- ``"afm"`` names ``afm-1`` and
    falls back to ferromagnetic order with a warning when there is none.
    A label past the listed candidates gives the reason it is refused."""
    signs = (1.0,) * len(structure)
    if requested == "fm":
        return _Ordered(structure, signs, "fm")
    candidates, none = _afm_candidates(structure, moments)
    index = 1 if requested == "afm" else int(requested.removeprefix("afm-"))
    if index <= len(candidates):
        criterion = "smallest_cell" if requested == "afm" else "requested"
        return _applied(structure, candidates, index, criterion)
    if requested == "afm":
        return _Ordered(structure, signs, "fm", warnings=(none.warning,))
    available = ", ".join(
        ["fm", *(f"afm-{number}" for number in range(1, len(candidates) + 1))]
    )
    reason = (
        f"magnetic_ordering {requested!r} is not one of this structure's "
        f"orderings ({available}; see goldilocks magnetic-orderings)"
    )
    return reason if none is None else f"{reason}: {none.reason}"


_CRITERION_PHRASES: dict[OrderingCriterion, str] = {
    "smallest_cell": "the smallest cell listed, the most symmetric of its size",
    "requested": "as requested",
}


def _applied(
    structure: Structure,
    candidates: tuple[Structure, ...],
    index: int,
    criterion: OrderingCriterion,
) -> _Ordered:
    """The listed candidate ``afm-<index>`` as the cell to seed, picked by
    ``criterion``, with the labels of the other candidates of its size."""
    cell = _sublattice_cell(candidates[index - 1])
    alternatives = tuple(
        f"afm-{number}"
        for number, other in enumerate(candidates, start=1)
        if number != index and len(other) == len(cell)
    )
    applied = Warning(
        code="magnetic.afm_ordering_applied",
        level="info",
        category="magnetic",
        message=(
            f"antiferromagnetic ordering afm-{index} applied, "
            f"{_CRITERION_PHRASES[criterion]}: {cell.num_sites} sites, "
            f"{len(set(cell.labels))} distinct species (was "
            f"{structure.num_sites} sites, {len(set(structure.species))} "
            "species). Other candidates of this size: "
            f"{', '.join(alternatives) or 'none'}; set magnetic_ordering to a "
            "label to write another (goldilocks magnetic-orderings lists them)."
        ),
    )
    return _Ordered(
        cell, _spin_signs(cell), f"afm-{index}", criterion, alternatives, (applied,)
    )


class _Seeded(NamedTuple):
    """The split cell, the labels a ``starting_magnetization`` is keyed by
    (``MagneticCell.site_labels``) and the species labels of the cell whose
    class is a requested value (``MagneticCell.human_seeded_labels``)."""

    cell: Structure
    site_labels: tuple[str, ...]
    human_seeded_labels: tuple[str, ...] = ()


def _site_labels(structure: Structure) -> tuple[str, ...]:
    """The distinct site labels of ``structure``, in site order."""
    return tuple(dict.fromkeys(site.label for site in structure))


def _seeded_split(
    ordered: _Ordered, override: dict[str, float] | None
) -> _Seeded | str:
    """``ordered.base`` split into species by each site's class: the
    value ``override`` requests for it (``_requested_seeds``), else its
    spin sign, so a partial override is merged onto the computed seeds
    (#185). A requested value lies strictly between -1 and 1 and a sign is
    +1, -1 or 0, so a requested and a computed class coincide only at 0,
    where both seeds are 0 whatever the z_valence: no species holds two
    different seeds. The two kinds of class are on different scales, so
    compensation is decided on the seeds (``_compensated``), not on them;
    and a request equal to another label's computed seed of its element
    (Ni1 set to Ni2's -5/18) still makes a species of its own, since the
    two meet only once the z_valences are known. The reason a key is
    refused, instead."""
    requested: tuple[float | None, ...] = (None,) * len(ordered.base)
    if override is not None:
        resolved = _requested_seeds(override, ordered)
        if isinstance(resolved, str):
            return resolved
        requested = resolved
    cell = split_species(
        ordered.base,
        [
            sign if value is None else value
            for sign, value in zip(ordered.signs, requested, strict=True)
        ],
    )
    human = (
        site.label
        for site, value in zip(cell, requested, strict=True)
        if value is not None
    )
    return _Seeded(cell, _site_labels(ordered.base), tuple(dict.fromkeys(human)))


def _requested_seeds(
    override: dict[str, float], ordered: _Ordered
) -> tuple[float | None, ...] | str:
    """The value a human ``starting_magnetization`` requests for each site
    of ``ordered.base``, ``None`` where it leaves the site to its computed
    seed; the reason a key is refused, instead. This is the key domain
    (#185): a site label of ``ordered.base`` -- the input's own (#32), or
    an applied ordering's sublattice labels -- sets the sites of that
    label; an element symbol that is not a label sets every other site of
    that element (``_element_keys``). Any other key is refused, naming the
    labels and element keys there are: a key that matches no site would
    otherwise seed nothing (#46)."""
    labels = _site_labels(ordered.base)
    unlabelled = {key: value for key, value in override.items() if key not in labels}
    elements = _element_keys(unlabelled, ordered)
    if isinstance(elements, str):
        return elements
    unknown = sorted(unlabelled.keys() - elements.keys())
    if unknown:
        usable = sorted(set(ordered.base.symbol_set) - _split_elements(ordered).keys())
        return (
            f"starting_magnetization has unknown key(s) {', '.join(unknown)}; "
            f"it takes this cell's site labels ({', '.join(labels)}) or an "
            f"element symbol for all of that element's sites ({', '.join(usable)})"
        )
    return tuple(
        override.get(site.label, elements.get(site.specie.symbol))
        for site in ordered.base
    )


def _element_keys(
    unlabelled: dict[str, float], ordered: _Ordered
) -> dict[str, float] | str:
    """The entries of ``unlabelled`` (keys that are not site labels) keyed
    by an element symbol of ``ordered.base``, each shorthand for all of
    that element's sites -- or the reason one names an element whose
    sites carry different computed seeds, an applied ordering's up and
    down sublattices, which one value would merge, naming the labels to
    set instead. Element keys partly reverse #46, which refused every
    one."""
    split = _split_elements(ordered)
    refused = [
        f"starting_magnetization cannot set {element!r} by element: the applied "
        f"magnetic ordering seeds its sites differently (labels "
        f"{', '.join(split[element])}); set each of those labels instead"
        for element in sorted(unlabelled.keys() & split.keys())
    ]
    if refused:
        return "; ".join(refused)
    return {
        element: value
        for element, value in unlabelled.items()
        if element in ordered.base.symbol_set
    }


def _split_elements(ordered: _Ordered) -> dict[str, tuple[str, ...]]:
    """The labels of each element of ``ordered.base`` whose sites carry
    more than one spin sign, in site order."""
    signs: dict[str, set[float]] = {}
    labels: dict[str, dict[str, None]] = {}
    for site, sign in zip(ordered.base, ordered.signs, strict=True):
        signs.setdefault(site.specie.symbol, set()).add(sign)
        labels.setdefault(site.specie.symbol, {})[site.label] = None
    return {
        element: tuple(labels[element])
        for element, found in signs.items()
        if len(found) > 1
    }


def _compensated(cell: Structure, seeds: dict[str, float]) -> bool:
    """Whether an operation of ``cell`` maps every site onto a site of the
    same element whose starting magnetization (``seeds``, by species label,
    as written) is the negative of its own: spglib's magnetic symmetry of
    the seeds as collinear moments, which spatial operations leave
    unchanged (``is_axial=False``), has a time-reversed operation. Only
    then is the net moment zero by construction; balanced spin counts are
    not enough -- spinel Fe3O4's R-3m candidate has 3 Fe up and 3 down,
    but both tetrahedral Fe down, and no operation maps a tetrahedral site
    onto an octahedral one (#138). The seeds decide, not the species
    classes: a requested value restating one sublattice's computed seed
    meets the other sublattice's seed, not its bare spin sign (#185).
    Positions are matched at ``SYMPREC``, the tolerance ``symmetry_eff`` is
    counted with, and seeds to rounding (``_SEED_TOLERANCE``)."""
    dataset = spglib.get_magnetic_symmetry(
        (
            cell.lattice.matrix,
            cell.frac_coords,
            [site.specie.Z for site in cell],
            [seeds[site.label] for site in cell],
        ),
        symprec=SYMPREC,
        mag_symprec=_SEED_TOLERANCE,
        is_axial=False,
    )
    return dataset is not None and bool(np.any(dataset["time_reversals"]))


def _spin_signs(candidate: Structure) -> tuple[float, ...]:
    """Each site's spin sign on an enumerated candidate: +1 or -1 on the
    seeded sublattice, 0 on every other site."""
    spins = (getattr(site.specie, "spin", None) or 0.0 for site in candidate)
    return tuple(1.0 if spin > 0 else -1.0 if spin < 0 else 0.0 for spin in spins)


def _sublattice_cell(candidate: Structure) -> Structure:
    """An enumerated candidate as a cell: one species per element and
    spin sign (``Ni1``/``Ni2``/``O``), the labels a human
    ``starting_magnetization`` on an applied ordering is keyed by."""
    return split_species(candidate, _spin_signs(candidate))


def _cell_in_input_basis(
    cell: Structure, structure: Structure
) -> tuple[tuple[float, ...], ...]:
    """``cell``'s lattice vectors in ``structure``'s basis (rows):
    ``cell.lattice.matrix == M @ structure.lattice.matrix``."""
    matrix = np.linalg.solve(structure.lattice.matrix.T, cell.lattice.matrix.T).T
    return tuple(tuple(float(value) for value in row) for row in matrix)


def _moment_direction(
    requested: tuple[float, float, float] | None, *, magnetic: bool
) -> tuple[MomentDirection | None, tuple[Warning, ...]]:
    """The moment direction of a ``magnetic`` noncollinear run (module
    docstring, #172) and its warning: ``requested``, or [001] with the
    defaulted notice. Any other run has none and ignores ``requested``
    with a warning."""
    if not magnetic:
        ignored = () if requested is None else (_MOMENT_DIRECTION_IGNORED_WARNING,)
        return None, ignored
    if requested is None:
        return MomentDirection((0.0, 0.0, 1.0), "heuristic"), (
            _MOMENT_DIRECTION_DEFAULTED_WARNING,
        )
    return MomentDirection(requested, "human"), ()


def _angles(axis: np.ndarray) -> tuple[float, float]:
    """QE's ``angle1`` (from Cartesian z) and ``angle2`` (of the xy
    projection, from x), in degrees, of the unit vector ``axis``.
    Components within 1e-12 of 0 are 0, so an axis along z has angle2 0,
    and the angles are rounded to 1e-6 degrees."""
    x, y, z = (float(value) + 0.0 for value in np.round(axis, 12))
    polar = round(math.degrees(math.acos(z)), 6) + 0.0
    azimuth = round(math.degrees(math.atan2(y, x)), 6) + 0.0
    return polar, azimuth


def _spin_requests(human: MagneticConfigHumanInput) -> tuple[Warning, ...]:
    """One warning per kind of human setting that asks for a spin-polarized
    run -- ``tot_magnetization``/``starting_magnetization`` (#34), any
    ``magnetic_ordering``, ``"fm"`` included (#145, #170) -- each saying that
    an explicit ``spin_polarized=false`` ignores it."""
    magnetization_given = (
        human.tot_magnetization is not None or human.starting_magnetization is not None
    )
    ordering_given = human.magnetic_ordering is not None
    return tuple(
        warning
        for warning, given in (
            (_MAGNETIZATION_IGNORED_WARNING, magnetization_given),
            (_ORDERING_IGNORED_WARNING, ordering_given),
        )
        if given
    )


_IS_MAGNETIC = ("is_magnetic",)
"""``derived_from`` of a spin decision the ``is_magnetic`` fact made."""


class _SpinChoice(NamedTuple):
    """Whether the run is spin-polarized, the tier that decided it, the
    record it followed (``("is_magnetic",)`` when that fact decided), and
    the warnings the decision carries."""

    polarized: bool
    source: Source
    derived_from: tuple[str, ...] = ()
    warnings: tuple[Warning, ...] = ()


def _resolve_spin_polarized(
    is_magnetic: FieldState[Magnetism],
    human: MagneticConfigHumanInput,
    llm: MagneticConfigLlmInput,
) -> _SpinChoice:
    """Whether the run is spin-polarized: an explicit human
    ``spin_polarized`` first, then any human spin request
    (``_spin_requests``) as true, then the llm, then ``is_magnetic``,
    defaulting to true when that is ``Unavailable``. The magnetism
    classifier is ``is_magnetic``'s ML tier, so this step has none of its
    own."""
    requests = _spin_requests(human)
    if human.spin_polarized is not None:
        # An explicit spin_polarized is a human override and wins, but a
        # request it overrides is reported, never silently dropped (#34,
        # #145).
        return _SpinChoice(
            human.spin_polarized,
            "human",
            warnings=() if human.spin_polarized else requests,
        )
    if requests:
        # A human request for moments or an ordering is a request for a
        # spin-polarized run, whatever the classifier says: it used to be
        # dropped whenever spin_polarized otherwise resolved false (#34,
        # #145).
        return _SpinChoice(True, "human")
    if llm.spin_polarized is not None:
        return _SpinChoice(llm.spin_polarized, "llm")
    if is_magnetic.ok:
        return _SpinChoice(is_magnetic.value == "magnetic", "heuristic", _IS_MAGNETIC)
    # #142: an SCF can quench a seeded moment, but a spin-unpolarized run
    # can never find one -- a wrong default this way costs compute time,
    # never a silently missing moment.
    return _SpinChoice(
        True,
        "heuristic",
        _IS_MAGNETIC,
        (
            Warning(
                code="magnetic.magnetism_unknown_defaulted_spin_polarized",
                level="warning",
                category="magnetic",
                message=(
                    f"magnetism could not be determined ({is_magnetic.reason}); "
                    "defaulted to spin-polarized, since the SCF can quench a "
                    "seeded moment but a spin-unpolarized run cannot find one. "
                    "Set spin_polarized to decide."
                ),
            ),
        ),
    )


_HUBBARD = ("hubbard",)
"""``derived_from`` of a spin decision a Hubbard U on an odd shell made."""

_ODD_SHELL_COUNTS = frozenset(range(1, 14, 2))
"""The odd d (1-9) and f (1-13) electron counts."""


def _hubbard_spin(
    spin: _SpinChoice,
    structure: Structure,
    is_magnetic: FieldState[Magnetism],
    hubbard: FieldState[HubbardUDecision] | None,
) -> _SpinChoice:
    """``spin``, or a spin-polarized run when ``spin`` is a
    spin-unpolarized answer of the llm or of ``is_magnetic`` and
    ``hubbard`` applies a U to an odd d or f count (``_odd_shells``; module
    docstring, #147), with the warning naming the shells and the answer
    overridden. A human ``spin_polarized`` and a spin-polarized answer
    stand, so the rule only ever turns spin polarization on."""
    if spin.polarized or spin.source == "human" or hubbard is None or not hubbard.ok:
        return spin
    shells = _odd_shells(structure, hubbard.value)
    if not shells:
        return spin
    overridden = (
        "the llm's spin_polarized=false"
        if spin.source == "llm"
        else f"is_magnetic={is_magnetic.value!r} ({is_magnetic.source})"
    )
    warning = Warning(
        code=_HUBBARD_OPEN_SHELL,
        level="warning",
        category="magnetic",
        message=(
            f"a Hubbard U acts on an odd d or f electron count: {shells}. "
            "Without spin polarization each spin holds half of that count, "
            "which fills no whole orbital, so +U can neither form the moment "
            f"nor open the gap. Spin polarization is turned on over {overridden}; "
            "set spin_polarized=false to keep a spin-unpolarized run."
        ),
    )
    return _SpinChoice(True, "heuristic", _HUBBARD, (warning,))


def _odd_shells(structure: Structure, decision: HubbardUDecision) -> str:
    """The elements ``decision`` applies a U to whose d or f count
    (``local_moments``' ``shell_counts``) is odd, as ``Cu 3d9``, joined;
    empty without a U on one, or when ``local_moments`` cannot count the
    shells (an undecided element)."""
    if not decision.u_values:
        return ""
    moments = local_moments(structure)
    if not moments.ok:
        return ""
    counts = moments.value.shell_counts
    return ", ".join(
        f"{entry.element} {entry.manifold}{counts[entry.element]:g}"
        for entry in decision.u_values
        if counts.get(entry.element) in _ODD_SHELL_COUNTS
    )


def unpolarized_if_non_magnetic(
    magnetic: FieldState[MagneticConfigFacts],
    hubbard: FieldState[HubbardUDecision] | None,
) -> bool:
    """Whether the answer is_magnetic=non_magnetic gives the run of
    ``magnetic`` no spin polarization: its spin polarization followed the
    is_magnetic fact, not a human ``spin_polarized`` or spin request or the
    llm (``_resolve_spin_polarized``), and ``hubbard`` applies no U to an odd
    d or f count of its cell (``_odd_shells``), which would turn spin
    polarization back on (``_hubbard_spin``). A spin decision the fact made
    requests no ordering, so the cell is the input's (the FM identity, or no
    ordering without spin polarization) and has its composition."""
    if not magnetic.ok:
        return False
    provenance = magnetic.provenance
    decided = (provenance.field_sources or {}).get("spin_polarized")
    if decided != "heuristic" or "is_magnetic" not in provenance.derived_from:
        return False
    if hubbard is None or not hubbard.ok:
        return True
    return not _odd_shells(magnetic.value.cell, hubbard.value)


def _fraction_for(symbol: str, z_valences: dict[str, float] | None) -> float:
    target = _MAGNETIC_MOMENT_TARGETS.get(symbol, 0)
    if not target:
        return DEFAULT_MAGNETIZATION_FRACTION
    if z_valences is None or symbol not in z_valences:
        # The real fraction needs this element's chosen pseudopotential's
        # valence electron count; without it, fall back to the flat default
        # rather than guess a z_valence -- still non-zero (A2), just not the
        # calibrated value yet.
        return DEFAULT_MAGNETIZATION_FRACTION
    return target / z_valences[symbol]


@dataclass(frozen=True, slots=True)
class _NoAfmOrdering:
    """Why no antiferromagnetic candidate was produced: the ``reason`` a
    refused ``afm-<n>`` gives, and the ``warning`` a ferromagnetic fallback
    and the listing report."""

    reason: str
    warning: Warning


def _afm_unavailable(reason: str) -> _NoAfmOrdering:
    """``reason`` with the ``magnetic.afm_ordering_unavailable`` warning
    that names it."""
    return _NoAfmOrdering(
        reason=reason,
        warning=Warning(
            code="magnetic.afm_ordering_unavailable",
            level="warning",
            category="magnetic",
            message=f"{reason}; kept ferromagnetic order.",
        ),
    )


_NO_OPEN_SHELL_SITES = _NoAfmOrdering(
    reason=f"no site carries a local d or f moment to order; {_SEED_IT_YOURSELF}",
    warning=_NO_OPEN_SHELL_SITES_WARNING,
)


def _afm_sublattice(
    moments: FieldState[LocalMomentFacts],
) -> tuple[str, ...] | _NoAfmOrdering:
    """The elements an antiferromagnetic ordering may compensate on --
    those ``local_moments`` says carry a local d or f moment -- or why
    there are none: ``magnetic.afm_no_open_shell_sites`` when no site
    carries one (closed shells, or a radical such as solid O2),
    ``magnetic.afm_ordering_unavailable`` with the model's reason when it
    cannot decide (#143)."""
    if isinstance(moments, Unavailable):
        return _afm_unavailable(
            f"the sites carrying a local moment could not be determined "
            f"({moments.reason}); {_SEED_IT_YOURSELF}"
        )
    sublattice = moments.value.moment_elements
    return sublattice if sublattice else _NO_OPEN_SHELL_SITES


def _afm_candidates(
    structure: Structure, moments: FieldState[LocalMomentFacts]
) -> tuple[tuple[Structure, ...], _NoAfmOrdering | None]:
    """Return every antiferromagnetic-origin candidate pymatgen's own
    ``MagneticStructureEnumerator`` (itself backed by
    ``MagOrderingTransformation``'s symmetry-aware enumeration) finds for
    ``structure``, spin-decorated and in ``_canonical_order`` (``afm-1``
    first), or an empty tuple plus why there is none.

    Only the sublattice (``_afm_sublattice``) is seeded, so a compensated
    candidate is compensated on the moment-bearing sites: seeding every
    transition metal, lanthanide and actinide let 4f0 La3+ in La2CuO4 or
    the induced moment of Pt in FePt carry the opposing spin while the
    real moments stayed parallel (#143). An empty or undecidable sublattice
    never reaches the enumerator.

    Shared by ``magnetic_cell`` (applies one candidate) and
    ``enumerate_magnetic_orderings`` (lists every candidate, for a caller
    -- e.g. an mMACE-based energy ranking, #87 -- that wants to compare
    more than one), so both number them alike. The enumerator runs on a
    worker process in a private directory
    (``magnetic_enumeration.enumerate_orderings``, #136).

    The structure the enumerator sees carries no moments of its own (a
    magCIF's arrive as a ``magmom`` site property): the sublattice seeds are
    the only ones it reads, and pymatgen refuses an input whose moments are
    non-collinear. Past ``_MAX_MAGNETIC_SITES_FOR_AFM_ENUMERATION`` sublattice
    sites in the primitive cell, enumlib is not run at all. Each enumlib
    call gets ``_ENUMLIB_TIMEOUT_MINUTES`` and no process pool, and only the
    plain ferromagnetic and antiferromagnetic strategies run: pymatgen's
    automatic ferrimagnetic ones never give an ``"afm"`` candidate (#171).

    The antiferromagnetic candidates are then kept and written only as
    the input's vacuum allows (``_keeping_the_vacuum``, module docstring,
    #144) before they are numbered.

    The enumerator's two answers about the structure become reasons, each
    with a fixed wording that quotes no exception text: enumlib found no
    ordering (pymatgen's ``ValueError('Unable to enumerate')``) or ran out
    of time (``TimeoutError``). Anything else propagates -- an ``OSError``
    from a scratch directory, numpy's ``LinAlgError`` or any other
    ``ValueError``, a dead worker process -- because the checks above leave
    pymatgen nothing else to refuse a structure for, so it is a fault."""
    sublattice = _afm_sublattice(moments)
    if isinstance(sublattice, _NoAfmOrdering):
        return (), sublattice
    unmagnetized = _without_moments(structure)
    magnetic_sites = _primitive_sublattice_sites(unmagnetized, sublattice)
    if magnetic_sites > _MAX_MAGNETIC_SITES_FOR_AFM_ENUMERATION:
        return (), _afm_unavailable(
            f"the primitive cell has {magnetic_sites} magnetic sites "
            f"({', '.join(sublattice)}), over the "
            f"{_MAX_MAGNETIC_SITES_FOR_AFM_ENUMERATION} this heuristic "
            "enumerates orderings for"
        )
    if not enumlib_installed():
        return (), _afm_unavailable(
            "antiferromagnetic ordering needs the enumlib executables on PATH "
            "(enum.x or multienum.x, plus makestr.x, makeStr.x or makeStr.py) "
            "and at least one was not found"
        )

    orderings = _enumerated(unmagnetized, sublattice)
    if isinstance(orderings, _NoAfmOrdering):
        return (), orderings
    candidates = tuple(candidate for candidate, origin in orderings if origin == "afm")
    if not candidates:
        return (), _afm_unavailable("no antiferromagnetic ordering was found")
    kept = _keeping_the_vacuum(structure, candidates)
    if isinstance(kept, _NoAfmOrdering):
        return (), kept
    return _canonical_order(kept), None


def _keeping_the_vacuum(
    structure: Structure, candidates: tuple[Structure, ...]
) -> tuple[Structure, ...] | _NoAfmOrdering:
    """The ``candidates`` whose lattice has a basis holding every vacuum
    vector of ``structure`` (``analysis.geometry.vacuum_axes``) at its own
    index, each written in such a basis (``_with_vacuum_vectors``), or why
    there is none (#144). Every candidate of a structure without vacuum is
    kept as it is."""
    axes = vacuum_axes(structure)
    if not axes:
        return candidates
    indices = tuple(LATTICE_AXES.index(axis) for axis in axes)
    kept = tuple(
        cell
        for candidate in candidates
        if (cell := _with_vacuum_vectors(candidate, structure, indices)) is not None
    )
    if kept:
        return kept
    return _afm_unavailable(
        "every antiferromagnetic ordering found repeats the "
        f"structure across its vacuum along {' and '.join(axes)} instead of "
        "keeping the uploaded period there"
    )


def _with_vacuum_vectors(
    candidate: Structure, structure: Structure, indices: tuple[int, ...]
) -> Structure | None:
    """``candidate`` in a basis of its lattice whose vectors ``indices``
    are those vacuum vectors of ``structure``, the others moved along them
    into the plane of the rest of ``structure``'s vectors and flipped as
    needed for ``structure``'s handedness, its sites where they were; or
    ``None`` when no basis holds them (module docstring, #144)."""
    vacuum = structure.lattice.matrix[list(indices)]
    coordinates = np.linalg.solve(candidate.lattice.matrix.T, vacuum.T).T
    integral = np.rint(coordinates)
    if not np.allclose(coordinates, integral, rtol=0.0, atol=_LATTICE_TOLERANCE):
        return None
    basis = _unimodular_with_rows(integral.astype(int), indices)
    if basis is None:
        return None
    matrix = basis @ candidate.lattice.matrix
    matrix[list(indices)] = vacuum
    reciprocal = structure.lattice.reciprocal_lattice_crystallographic.matrix
    free = [row for row in range(3) if row not in indices]
    for row in free:
        matrix[row] -= np.rint(reciprocal[list(indices)] @ matrix[row]) @ vacuum
    if free and np.linalg.det(matrix) * np.linalg.det(structure.lattice.matrix) < 0:
        matrix[free[0]] *= -1
    return Structure(
        Lattice(matrix),
        candidate.species,
        candidate.cart_coords,
        coords_are_cartesian=True,
        to_unit_cell=True,
        site_properties=candidate.site_properties,
    )


def _unimodular_with_rows(
    rows: np.ndarray, indices: tuple[int, ...]
) -> np.ndarray | None:
    """An integer 3x3 matrix of determinant +-1 whose row ``indices[k]`` is
    ``rows[k]``: a basis of a lattice, in the coordinates of another of its
    bases, that holds the given lattice vectors. ``None`` when none does,
    because some integer fraction of a combination of them is a lattice
    vector too. Column operations reduce each row in turn to the unit
    vector of its index (Euclid's algorithm on its entries outside the
    indices already placed); the basis is the inverse of their product."""
    operations = np.eye(3, dtype=int)
    placed: list[int] = []
    for row, index in zip(rows, indices, strict=True):
        reduced = row @ operations
        free = [column for column in range(3) if column not in placed]
        pivot = _euclid(reduced, operations, free)
        if pivot is None:
            return None
        operations[:, [pivot, index]] = operations[:, [index, pivot]]
        reduced[[pivot, index]] = reduced[[index, pivot]]
        operations[:, index] *= reduced[index]
        for column in placed:
            operations[:, column] -= reduced[column] * operations[:, index]
        placed.append(index)
    return np.rint(np.linalg.inv(operations)).astype(int)


def _euclid(reduced: np.ndarray, operations: np.ndarray, free: list[int]) -> int | None:
    """Euclid's algorithm on the ``free`` entries of the integer row
    ``reduced`` by column operations, applied to it and to ``operations``
    alike, until one entry is left: its column if that entry is +-1,
    ``None`` otherwise."""
    while True:
        nonzero = [column for column in free if reduced[column]]
        if not nonzero:
            return None
        pivot = min(nonzero, key=lambda column: abs(reduced[column]))
        if len(nonzero) == 1:
            return pivot if abs(reduced[pivot]) == 1 else None
        for column in nonzero:
            if column != pivot:
                quotient = reduced[column] // reduced[pivot]
                reduced[column] -= quotient * reduced[pivot]
                operations[:, column] -= quotient * operations[:, pivot]


def _canonical_order(candidates: tuple[Structure, ...]) -> tuple[Structure, ...]:
    """``candidates`` smallest cell first, then most symmetric -- the
    operation count of the spin-decorated cell's space group in its
    conventional setting, as pymatgen's own ``truncate_by_symmetry`` ranks
    them, then the space-group number, both descending -- then by the
    spin-decorated sites of the Niggli-reduced cell (``_site_signature``).

    pymatgen keeps the first ``max_orderings`` of enumlib's structures,
    smallest cells first, and ranks them by that operation count, breaking
    ties in both by the order it reads enumlib's ``vasp.*`` output files in.
    The worker reads them in enumlib's numbering (``magnetic_enumeration``),
    so the host that lists the candidates and the one that generates one by
    its label get the same cells (#170); this order depends on the cells
    alone, so ``afm-<n>`` names the same cell on both, for one pymatgen-core,
    spglib and enumlib version."""
    return tuple(sorted(candidates, key=_canonical_key))


def _canonical_key(
    candidate: Structure,
) -> tuple[int, int, int, tuple[object, ...]]:
    _symbol, number = candidate.get_space_group_info()
    operations = len(SpaceGroup.from_int_number(number).symmetry_ops)
    return (len(candidate), -operations, -number, _site_signature(candidate))


def _site_signature(candidate: Structure) -> tuple[object, ...]:
    """The Niggli-reduced cell of ``candidate``: its lattice vectors and
    its sites as (element, spin sign, fractional coordinates in [0, 1)),
    sorted, rounded to 1e-4."""
    reduced = candidate.get_reduced_structure("niggli")
    sites = sorted(
        (
            site.specie.symbol,
            sign,
            tuple(round(float(value) % 1.0, 4) % 1.0 for value in site.frac_coords),
        )
        for site, sign in zip(reduced, _spin_signs(reduced), strict=True)
    )
    lattice = tuple(round(float(value), 4) for value in reduced.lattice.matrix.flat)
    return (lattice, tuple(sites))


def _without_moments(structure: Structure) -> Structure:
    """A copy of ``structure`` without spins or a ``magmom`` site
    property."""
    unmagnetized = structure.copy()
    unmagnetized.remove_spin()
    if "magmom" in unmagnetized.site_properties:
        unmagnetized.remove_site_property("magmom")
    return unmagnetized


def _primitive_sublattice_sites(
    structure: Structure, sublattice: tuple[str, ...]
) -> int:
    """How many sites of ``sublattice`` the primitive cell of ``structure``
    (without moments) has, as pymatgen reduces it before enumerating.
    Counted on ``structure`` itself when that is within the ceiling, since
    the reduction never adds sites."""

    def count(cell: Structure) -> int:
        return sum(site.specie.symbol in sublattice for site in cell)

    in_structure = count(structure)
    if in_structure <= _MAX_MAGNETIC_SITES_FOR_AFM_ENUMERATION:
        return in_structure
    return count(structure.get_primitive_structure(use_site_props=False))


def _enumerated(
    structure: Structure, sublattice: tuple[str, ...]
) -> tuple[tuple[Structure, str], ...] | _NoAfmOrdering:
    """``enumerate_orderings`` on ``structure`` with ``sublattice`` seeded,
    or why there are none when enumlib finds no ordering or runs out of
    time; any other error propagates (``_afm_candidates``)."""
    try:
        return enumerate_orderings(
            structure,
            default_magmoms=dict.fromkeys(sublattice, 5.0),
            strategies=("ferromagnetic", "antiferromagnetic"),
            automatic=False,
            truncate_by_symmetry=True,
            max_orderings=16,
            transformation_kwargs={"timeout": _ENUMLIB_TIMEOUT_MINUTES, "n_jobs": 1},
        )
    except TimeoutError:
        return _afm_unavailable(
            "enumlib did not finish within its "
            f"{_ENUMLIB_TIMEOUT_MINUTES * 60:g} s time limit"
        )
    except ValueError as error:
        if str(error) != _ENUMLIB_FOUND_NO_ORDERING:
            raise
        return _afm_unavailable(
            "enumlib found no ordering of the magnetic sites for this structure"
        )


def enumerate_magnetic_orderings(
    structure: Structure, moments: FieldState[LocalMomentFacts]
) -> tuple[tuple[tuple[str, Structure], ...], Warning | None]:
    """List every magnetic-ordering candidate this heuristic tier can
    produce for ``structure``, whose ``local_moments`` are ``moments``: the
    plain ferromagnetic identity (label ``"fm"``, the input structure),
    plus every antiferromagnetic candidate ``_afm_candidates`` finds and
    keeps for the input's vacuum (#144),
    labeled ``"afm-<n>"`` in its canonical order and split into one
    species per element and spin sign -- the cell ``magnetic_cell`` writes
    for ``magnetic_ordering="afm-<n>"`` without a human
    ``starting_magnetization`` (#170).

    Unlike ``magnetic_cell``, this never picks a winner -- it is
    the listing half of #87's "enumerate, then optionally rank with mMACE,
    then generate" split. Returns just the ``"fm"`` entry, with no
    antiferromagnetic candidates, whenever ``_afm_candidates`` finds none
    (no moment-bearing site, an undecidable sublattice, too many magnetic
    sites, missing enumlib, enumlib finding no ordering or running out of
    time, no compensated ordering found, or every one repeating across the
    vacuum); any other enumeration error propagates.

    The second return value is the warning saying why whenever no AFM
    candidate was found, ``None`` otherwise -- surfaced so a caller (#87's
    ``list_magnetic_orderings``) can tell a real "no compensated ordering
    exists" result apart from "AFM enumeration could not run here" (e.g.
    missing enumlib), which otherwise look identical from the candidate
    list alone."""
    candidates: list[tuple[str, Structure]] = [("fm", structure)]
    afm_candidates, none = _afm_candidates(structure, moments)
    for index, candidate in enumerate(afm_candidates, start=1):
        candidates.append((f"afm-{index}", _sublattice_cell(candidate)))
    return tuple(candidates), None if none is None else none.warning


def _seeds(
    cell: Structure,
    z_valences: dict[str, float] | None,
    human_seeded_labels: tuple[str, ...],
) -> dict[str, float]:
    """One starting magnetization per species label of the spin-polarized
    ``cell`` (``generation/quantum_espresso/scf.py``'s ``species_index``
    keys by the same label, #32): the species' class (``Species.spin``,
    ``MagneticCell``) itself for a label in ``human_seeded_labels`` -- a
    human value --, otherwise the class (the spin sign: +1, -1 or 0) times
    its element's fraction (``_fraction_for``). Both paths that can apply
    one ordering -- plain ``afm`` and a listed ``afm-<n>`` -- read the same
    cell, so they seed it alike (#170)."""
    seeds: dict[str, float] = {}
    for site in cell:
        if site.label in seeds:
            continue
        spin = site.specie.spin
        seeds[site.label] = (
            spin
            if site.label in human_seeded_labels
            else spin * _fraction_for(site.specie.symbol, z_valences)
        )
    return seeds


def _seeded_moment(
    cell: Structure,
    seeds: dict[str, float] | None,
    z_valences: dict[str, float] | None,
) -> float | None:
    """The net moment ``seeds`` start ``cell`` from, in Bohr magnetons:
    QE's ``starting_magnetization`` is a fraction of the species'
    valence charge, so each site contributes its label's fraction times
    its element's z_valence. ``None`` without seeds or without a
    z_valence for one of the cell's elements."""
    if seeds is None or z_valences is None:
        return None
    if any(site.specie.symbol not in z_valences for site in cell):
        return None
    return sum(seeds[site.label] * z_valences[site.specie.symbol] for site in cell)
