"""capabilities: the v2 capabilities contract (v2 epic 8, #8;
goldilocks-core-design.md S4.2).

Consumers: the frontend (render forms), the agent (know what's tunable),
the CLI (``goldilocks settings``' data source, ``--set`` key validation),
and cross-repo vocabulary version checks.

**`settings[]` is reflected from the override dataclasses `service/`
already built, not hand-listed** -- this is design point (1)'s "add an
advisor, its settings automatically appear in capabilities" promise,
made real via `pydantic`'s own `model_fields` plus `typing.get_type_hints`
on the plain dataclasses `service/_system_overrides.py`/`_step_kpoints.py`/
`_step_resources.py` already compose. Concretely: for each of those three
classes, every non-``_llm`` field is either (a) a plain type (like
``pseudo_table_id: str | None``), which becomes one setting directly, or
(b) a ``HumanInput`` subclass (like ``cutoffs: CutoffsHumanInput | None``),
whose *own* pydantic fields each become one setting, grouped under the
outer field's name. This walk only needs to import the three composing
classes themselves, not any of the ~15 individual advisor modules behind
them -- which is also why this module comfortably fits this project's
import-surface ceiling (``scripts/check_complexity.py``) despite
covering every advisor: reflection at runtime doesn't cost an `import`
statement the way a hand-written list of every advisor's types would.

**`group`/`scope`/`steps` are derived structurally, not annotated
per-field**: `group` is the outer composing field's own name (e.g. every
field inside ``CutoffsHumanInput`` gets ``group="cutoffs"`` for free);
`scope` is which composing class a field came from (``AnalysisOverrides``/
``SystemOverrides`` -> ``"system"``, ``JobOverrides`` -> ``"task"``, the
step classes -> ``"per_step"``); `steps` is the step purposes a per-step
setting applies to, by composing class (``_BRANCH_STEPS``: every pw.x step;
relax and vc-relax; dos; a band task's bands step and a phonon task's
dispersion step, which follow the band path; or a phonon task's ph, q2r or
phonon_dos step), narrowed per key where ``_SETTING_META`` says so
(vc-relax's cell keys, relax's ``etot_conv_thr``, the SCF loop's mixing and
iteration keys, which an nscf or bands step does not read, and the
occupations and k-mesh keys, which a bands step takes from its scf step and
its band path). A phonon task's first step keeps its pw.x purpose (scf,
relax or vc-relax), so the pw.x settings reach it through those steps.
`tasks` and `programs` follow from `steps` through ``plan.expand_task``; a
system or task setting applies to every task, once, and has no `steps`
(#154). ``set_overrides`` routes a request with the same
``SettingBinding.steps``, so what is published is what is accepted.

**What genuinely can't be derived** -- physical unit, a confidently-known
fixed default (many fields have no fixed default at all: cutoffs and
electron count are pseudopotential-dependent, `nbnd` is formula-derived,
walltime defaults to the partition ceiling), a declared `ml_target`, the
one `enum_from`, the description, and whether a value is a judgement about
the structure (``structure_specific``, #188) -- lives in `_SETTING_META`
below, one table, the same pattern this codebase already uses for
``scripts/check_complexity.py``'s ``LIMITS`` dict. Every setting needs an
entry that declares ``structure_specific`` (``_setting_from_leaf`` raises
without one), so no setting is published unclassified. This is not "hand
-written instead of auto-generated": the *existence*, *key*, *type*, and
*grouping* of every setting is still 100% reflected; this table only
supplies the facts pydantic's type system cannot know (what unit a
``float`` is in, whether an ml model is planned for it, whether a value
still holds for another structure).

**`resolved_in` says where a setting's resolved value is published
(#187)**, so a client reads it without matching setting names against
record names: ``record`` is the record of the decision the setting feeds,
``path`` the keys of the setting's own value inside that record's value.
Both default structurally -- the record of the setting's group (each
composing field feeds the advisor whose record bears its name) and the
setting's own field name -- and ``_SETTING_META`` declares the
exceptions: ``pseudo_table_id`` resolves in ``pseudo_table.id``,
``spin_orbit_coupling`` in ``magnetic.spin_orbit_enabled``,
``magnetic_ordering`` in ``magnetic.ordering.applied``, ``k_grid`` in
``k_sampling.mesh``, ``hubbard_projectors`` in ``hubbard.projectors``,
``q_grid`` in the phonon tasks' ``q_sampling.mesh``, and a knob no record
holds a value of (``extra_bands``, ``hubbard_needs_correlation``,
``u_by_element``) has no path. Neither has a setting published under a key
other than its field name, since a record's ``field_sources`` names
settings by field name.

**One real key collision, resolved by renaming, not by luck**:
``advisors/hubbard_u.py``'s own ``HubbardUHumanInput.needs_correlation``
and ``analysis/needs_correlation.py``'s fact-level override both use the
field name ``needs_correlation`` -- but they are genuinely different
knobs (the fact is a general "does this structure need correlation
treatment" judgement; hubbard's own field is a stronger, hubbard
-specific escape hatch that overrides even a human-set fact, see
``hubbard_u()``'s own priority order). Exposed as flat ``--set`` keys
they would collide, so hubbard's is renamed to
``hubbard_needs_correlation`` in ``_SETTING_META`` -- the Python
attribute name is untouched, only the exposed capabilities key differs.

**`facts[]` lists the four scalar analysis facts** (``is_metal``,
``is_magnetic``, ``needs_soc``, ``needs_correlation``) in the design
doc's illustrative shape (``{"key", "type": "enum", "values",
"ml_target", "overridable", "description"}``). Only which facts exist,
their ``ml_target`` and their description are hand-written (``_FACTS``).
``type``/``values`` come from the fact's record type on
``service.AnalysisFacts`` (``FieldState[Literal[...]]`` is an enum of the
Literal's members, ``FieldState[bool]`` a boolean), and ``overridable``
is whether the key has an analysis binding. The overrides are typed with
the same record Literals, so every advertised value is an accepted one
(#139: ``is_metal`` advertised ``metal``/``non_metal`` while its override
took only booleans). ``needs_soc`` has no binding (#186): only a notice
reads it and ``spin_orbit_coupling`` alone enables spin-orbit coupling, so
it is published read-only, with no ``human`` approach.
``composition``/``geometry``/``symmetry`` are
structural, multi-field records with no override at all
(``analysis/composition.py``'s and ``analysis/symmetry.py``'s own
docstrings say so explicitly) and don't fit this shape; they are not
exposed here.

**`warnings[]` is aggregated, not hand-listed**, the same reflection
-over-imports-elsewhere-in-the-codebase spirit as `settings[]`: every
advisor that can emit a ``resolution.Warning`` declares its own
``WARNING_CATALOGUE`` constant (code/level/category/a generic
description), and ``advisors/warning_catalogue.py`` -- a dedicated
aggregator, not this module -- imports every one of them so this module
itself only needs one import to get the full list without blowing its
own import-surface ceiling.

**`models[]`/`approaches` (v2 epic 11, #11).** ``models[]`` lists every
model ``ml/registry.toml`` registers (``ml.models.registered_models``),
whether or not it is actually installed; ``approaches`` (design point
(1)-b) is the honest "is ml actually usable right now" signal -- a
fact/setting's ``ml_target`` only gains ``"ml"`` once
``ml.predict.model_ready`` passes the checks a prediction makes first: the
model's asset installed and verified and, for ``is_magnetic``, the mMACE
backbone configured and the mace packages installed (#130).
``is_metal``/``is_magnetic`` (``ml.models.ML_CLASSIFIER_ROLES``) and
``k_distance`` (QRF95) are wired this way; ``k_index``'s own
``ml_target`` names a real, published goldilocks-ml *ladder-rung* model
that is a distinct thing from QRF95 and is not registered/wired yet
(#90) -- it stays ``["human", "heuristic"]`` honestly rather than
claiming support that would raise on every real call. That model predicts
rungs on goldilocks-data's ladder (``ladder_1based.v2``), which core's
ladder no longer matches rung for rung (#163, ``kmesh``).
"""

from __future__ import annotations

import types
import typing
from dataclasses import dataclass
from importlib.metadata import version as package_version
from typing import Literal, Required, TypedDict

from goldilocks_core.advisors.warning_catalogue import (
    WARNING_CATALOGUE as _ADVISOR_WARNING_CATALOGUE,
)
from goldilocks_core.assets.pseudopotentials.registry import load_tables
from goldilocks_core.inputs.hpc import list_hpc_profiles, load_hpc_profile
from goldilocks_core.ml.predict import model_ready
from goldilocks_core.plan import expand_task
from goldilocks_core.service import (
    OVERRIDES_WARNING_CATALOGUE,
    AnalysisFacts,
    AnalysisOverrides,
    DosOverrides,
    JobOverrides,
    KPathOverrides,
    KpointsOverrides,
    PhononDosOverrides,
    PhOverrides,
    Q2rOverrides,
    RelaxOverrides,
    ResourceOverrides,
    SystemOverrides,
)
from goldilocks_core.types import CalcTask

VOCABULARY_VERSION = "5"
"""Bump when the settings/facts vocabulary changes in a way other
ecosystem repos (ml/agent/data) need to know about -- goldilocks-core
-design.md S4.2's cross-repo validation antidote."""

SOURCES: tuple[Literal["human", "ml", "llm", "heuristic"], ...] = (
    "human",
    "ml",
    "llm",
    "heuristic",
)
"""Order is priority, matching ``resolution.Source`` -- closed, four
tiers, per design point (5)."""

_CODE = "quantum_espresso"
_TASK = "scf_single_point"
_DOS_TASK = "dos"
_BAND_TASK = "band"
_RELAX_TASK = "relax"
_VC_RELAX_TASK = "vc-relax"
_PHONON_TASK = "phonon"
_RELAX_PHONON_TASK = "relax-phonon"
_VC_RELAX_PHONON_TASK = "vc-relax-phonon"
_TASK_IDS: tuple[CalcTask, ...] = typing.get_args(CalcTask)
"""Every task, in ``types.CalcTask``'s order: the code's ``tasks`` and
what each setting's ``tasks`` is drawn from."""
_PROGRAM = "pw.x"

_Branch = Literal[
    "analysis",
    "system",
    "job",
    "kpoints",
    "resources",
    "relax",
    "dos",
    "k_path",
    "ph",
    "q2r",
    "phonon_dos",
]
_Scope = Literal["system", "task", "per_step"]

_PW_STEPS = ("scf", "nscf", "bands", "relax", "vc-relax")
_RELAX_STEPS = ("relax", "vc-relax")
_SCF_LOOP_STEPS = ("scf", "relax", "vc-relax")
"""The pw.x steps that run an SCF loop. An nscf or bands step diagonalizes
once in the density the scf step wrote: QE 7.3 runs ``non_scf`` instead of
``electrons`` (``run_pwscf.f90``) and sets ``niter = 1`` (``setup.f90``), so
``mixing_beta``, ``mixing_mode``, ``mixing_fixed_ns`` and
``electron_maxstep`` have no effect on it."""
_MESH_STEPS = ("scf", "nscf", "relax", "vc-relax")
"""The pw.x steps on a k-mesh. A bands step runs the band path of its cell
(``k_path_distance``) with the occupations of the scf step before it
(#118), so the k-mesh and occupations keys have no effect on it."""
_BRANCH_STEPS: dict[_Branch, tuple[str, ...] | None] = {
    "analysis": None,
    "system": None,
    "job": None,
    "kpoints": _PW_STEPS,
    "resources": _PW_STEPS,
    "relax": _RELAX_STEPS,
    "dos": ("dos",),
    "k_path": ("bands", "dispersion"),
    "ph": ("ph",),
    "q2r": ("q2r",),
    "phonon_dos": ("phonon_dos",),
}
"""The step purposes (``plan.PlannedStep.purpose``) each composing class's
settings apply to; ``None`` for a task-level class, set once per task."""


def _approaches(ml_target: str | None) -> list[str]:
    """Design point (1)-b: ``ml_target`` is a static declaration;
    ``approaches`` is what's *actually* usable right now, computed as
    ``["human"] + (["ml"] if that target's model would run) +
    ["heuristic"]``. v2 epic 11 (#11): ``is_metal``/``is_magnetic`` are
    registered, real, ``goldilocks_ml.inference``-loadable classifiers
    (``ml.models.ML_CLASSIFIER_ROLES``), and ``k_distance`` is QRF95
    (#92) -- ``"ml"`` appears for any of these once
    ``ml.predict.model_ready`` finds it set up, not merely declared.
    ``k_index``'s ``ml_target`` names a different, not-yet-registered/wired
    ladder-rung model (#90), which ``model_ready`` never reports ready, so
    it keeps resolving to ``["human", "heuristic"]`` honestly rather than
    claiming ml support that would raise ``MlModelUnavailable`` on every
    real call."""
    if ml_target is not None and model_ready(ml_target):
        return ["human", "ml", "heuristic"]
    return ["human", "heuristic"]


class ResolvedIn(TypedDict):
    """Where a setting's resolved value is published (#187): ``record`` is
    the record of the decision the setting feeds, in ``explain``/``run``'s
    ``records``; ``path`` the keys leading to the setting's own value inside
    that record's ``value`` -- ``[]`` for the value itself, ``None`` where
    the record holds no value of the setting (an input-only knob such as
    ``extra_bands``, which only shifts ``nbnd``)."""

    record: str
    path: list[str] | None


class Setting(TypedDict, total=False):
    """One ``--set``-able key. ``tasks`` are the tasks it applies to;
    ``steps``/``programs`` are the steps (purposes, the names of
    ``steps.<purpose>.<key>``) and programs a ``per_step`` setting applies
    to, ``None`` for a ``system`` or ``task`` setting, set once per task.
    ``structure_specific`` is whether a value is a judgement about the
    structure it was set for (#188, ``_SettingExtra``); ``resolved_in``
    where its resolved value is published (#187)."""

    key: str
    group: str
    type: str
    enum: list[str]
    unit: str | None
    default: object
    enum_from: str
    codes: list[str]
    tasks: list[str]
    steps: list[str] | None
    programs: list[str] | None
    scope: _Scope
    structure_specific: bool
    resolved_in: ResolvedIn
    ml_target: str | None
    approaches: list[str]
    description: str


class Fact(TypedDict):
    key: str
    type: str
    values: list[str] | None
    ml_target: str | None
    approaches: list[str]
    overridable: bool
    description: str


class Capabilities(TypedDict):
    core_version: str
    vocabulary_version: str
    codes: list[dict[str, object]]
    tasks: list[dict[str, object]]
    facts: list[Fact]
    settings: list[Setting]
    pseudopotential_tables: list[dict[str, object]]
    hpc_profiles: list[dict[str, object]]
    models: list[dict[str, object]]
    warnings: list[dict[str, object]]
    sources: list[str]


class _SettingExtra(TypedDict, total=False):
    """A setting's ``_SETTING_META`` entry, which every setting has.

    ``structure_specific`` (#188) is true when a value is a judgement about
    the structure it was set for -- its elements, magnetism, geometry, size
    or k-mesh -- and false for a method, accuracy or job choice. When another
    structure is opened, the Workbench keeps the values of the settings for
    which it is false and clears the rest, and every fact override, since a
    fact is a judgement about the structure by definition.

    ``record`` and ``path`` (#187) are declared only where the published
    ``resolved_in`` differs from its default: the record of the setting's
    group and, as the path, the setting's own field name. ``path`` ``None``
    declares that the record holds no value of the setting."""

    key: str
    unit: str | None
    default: object
    enum_from: str
    ml_target: str | None
    steps: tuple[str, ...]
    structure_specific: Required[bool]
    record: str
    path: tuple[str, ...] | None
    description: str


_SETTING_META: dict[str, _SettingExtra] = {
    "functional": {
        "structure_specific": False,
        "path": (),
        "default": "PBEsol",
        "enum_from": "pseudopotential_tables.functional",
        "description": "Exchange-correlation functional label (e.g. PBE, PBEsol).",
    },
    "pseudo_table_id": {
        "structure_specific": True,
        "record": "pseudo_table",
        "path": ("id",),
        "description": (
            "Pin an explicit pseudopotential table id instead of automatic selection."
        ),
    },
    "ecutwfc_ry": {
        "structure_specific": True,
        "unit": "Ry",
        "description": "Plane-wave wavefunction kinetic-energy cutoff.",
    },
    "ecutrho_ry": {
        "structure_specific": True,
        "unit": "Ry",
        "description": (
            "Charge-density cutoff. Unset: the largest the selected "
            "pseudopotentials publish (SSSP), or the table's "
            "charge_density_dual times the resolved ecutwfc_ry where it "
            "publishes none (PseudoDojo)."
        ),
    },
    "nelec": {
        "structure_specific": True,
        "description": (
            "Total valence electron count of the uploaded cell (otherwise "
            "summed from pseudopotential z_valence), written as tot_charge, "
            "its difference from the neutral count; refused when "
            "magnetic_ordering writes a cell of another size."
        ),
    },
    "spin_polarized": {
        "structure_specific": True,
        "description": (
            "Force spin polarization on or off: a collinear nspin=2 run, or a "
            "magnetic noncollinear one with spin_orbit_coupling."
        ),
    },
    "spin_orbit_coupling": {
        "structure_specific": True,
        "path": ("spin_orbit_enabled",),
        "description": (
            "Enable noncollinear spin-orbit-coupling mode (always opt-in, "
            "never auto-enabled)."
        ),
    },
    "tot_magnetization": {
        "structure_specific": True,
        "description": (
            "Total per-cell magnetization target of a collinear spin-polarized "
            "run (nspin=2); refused with spin_orbit_coupling, whose noncollinear "
            "run takes starting_magnetization instead, and ignored when "
            "spin_polarized is false. Fixed occupations need an integer of the "
            "electron count's parity; a non-metal gets them by default only "
            "then, and smearing otherwise. A collinear band task refuses it: "
            "bands.x stops on the two Fermi energies it gives."
        ),
    },
    "starting_magnetization": {
        "structure_specific": True,
        "description": (
            "Starting spin-polarization fraction (each value strictly between "
            "-1 and 1) per site label -- the uploaded structure's labels "
            "(inspect lists them), or Ni1/Ni2/O-style labels of an applied "
            "magnetic_ordering; records.magnetic.site_labels lists the ones "
            "in force -- or per element symbol, for all of that element's "
            "sites, refused where an applied magnetic_ordering seeds them "
            "differently. A label beats its element. Sites left out keep the "
            "valence-electron-based heuristic seed, and sites with different "
            "values become separate species."
        ),
    },
    "magnetic_ordering": {
        "structure_specific": True,
        "path": ("ordering", "applied"),
        "description": (
            "Opt in to an antiferromagnetic ordering instead of the "
            "ferromagnetic default ('fm' or unset), over the sites that carry "
            "a local d or f moment: 'afm' applies the first candidate the "
            "magnetic-orderings listing gives (the smallest cell, then the "
            "most symmetric), 'afm-<n>' the listed candidate of that label; "
            "records.magnetic names the criterion and the other candidates of "
            "that size. A slab, wire or boxed molecule gets only candidates "
            "that keep its vacuum vectors. Any value, 'fm' included, turns spin "
            "polarization on unless spin_polarized is false, which ignores it "
            "with a warning. 'afm' degrades to ferromagnetic with a warning if "
            "there is no candidate; an 'afm-<n>' that is not listed is refused."
        ),
    },
    "moment_direction": {
        "structure_specific": True,
        "path": ("moment_direction", "uvw"),
        "description": (
            "Direction the moments of a spin-polarized spin_orbit_coupling run "
            "start along, as a lattice direction [u, v, w] of the uploaded "
            "cell (non-zero), written as QE's angle1/angle2 and used to count "
            "the k-points by magnetic symmetry. A physical choice: unset, the "
            "moments start along [0, 0, 1], with a notice. Ignored with a "
            "warning by any other run."
        ),
    },
    "use_vdw": {
        "structure_specific": True,
        "description": (
            "Force whether a van der Waals dispersion correction is applied. "
            "D3(BJ) needs parameters for the functional, which Quantum "
            "ESPRESSO has only for PBE and PBEsol: with any other functional, "
            "such as LDA, the default is no correction and true is refused."
        ),
    },
    "method": {
        "structure_specific": False,
        "description": (
            "Dispersion-correction method when use_vdw is set (only d3bj is "
            "implemented)."
        ),
    },
    "isolation": {
        "structure_specific": True,
        "description": (
            "How the electrostatics treat periodic images. 'periodic': no "
            "truncation, the default for any cell periodic along at least one "
            "lattice vector, including molecular crystals, slabs and wires "
            "(pw.x has no 1D truncation). 'slab': Quantum ESPRESSO's 2D Coulomb "
            "truncation (assume_isolated='2D', Sohier et al. 2017), never the "
            "default; refused unless the vacuum lies along c only, a and b lie "
            "in the xy plane, c lies along z, the cell is at least 11.11 Å "
            "(21 bohr) high and the vacuum is at least 10.58 Å (20 bohr) wider "
            "than the slab, and a vc-relax needs cell_dofree='2Dxy' or '2Dshape'. "
            "'isolated': Martyna-Tuckerman (assume_isolated='martyna-tuckerman'), "
            "the default with vacuum along all three lattice vectors and refused "
            "otherwise; pw.x computes no stress under it, so vc-relax is refused."
        ),
    },
    "needs_correlation": {
        "key": "hubbard_needs_correlation",
        "structure_specific": True,
        "path": None,
        "description": (
            "Force whether a Hubbard +U correction is applied, overriding even "
            "a human-set needs_correlation fact: false runs without +U, true "
            "applies the built-in U table to the structure's d and f elements."
        ),
    },
    "u_by_element": {
        "structure_specific": True,
        "path": None,
        "unit": "eV",
        "description": (
            "Dudarev U_eff in eV (> 0) per element symbol; replaces the built-in "
            "table, so only listed elements present in the structure get +U. "
            "La and Ac are rejected: no installed pseudopotential has an "
            "occupied La 4f or any Ac 5f channel, so pw.x stops on any U for them."
        ),
    },
    "hubbard_projectors": {
        "structure_specific": False,
        "path": ("projectors",),
        "default": "ortho-atomic",
        "description": (
            "Projector type of the HUBBARD card when an element gets +U: "
            "'ortho-atomic', the default, which Quantum ESPRESSO recommends, or "
            "'atomic', the only type ph.x accepts with +U. A U value is tied to "
            "the projectors it was derived with, so switching changes what a "
            "given U means; the built-in U table is used unchanged with either."
        ),
    },
    "occupations": {
        "structure_specific": True,
        "steps": _MESH_STEPS,
        "description": (
            "Electronic-occupation scheme (fixed, smearing, or tetrahedra_opt). "
            "Default: smearing for a metal or unconfirmed metallicity; fixed for "
            "a non-metal where fixed occupations can run -- an even electron "
            "count without spin polarization (spin_orbit_coupling or not), any "
            "count on a spin-polarized spin_orbit_coupling run, and, for a "
            "collinear spin-polarized run, an integer tot_magnetization of the "
            "count's parity (one set, or, except on a band task, 0 for a "
            "magnetic_ordering compensated by symmetry) -- and smearing "
            "otherwise. An explicit fixed on a collinear run with no such moment "
            "is refused. On a band task it sets the scf step, whose occupations "
            "the bands step takes, tetrahedra_opt written there as cold "
            "smearing."
        ),
    },
    "smearing_type": {
        "structure_specific": False,
        "steps": _MESH_STEPS,
        "description": (
            "Smearing function used when occupations=smearing, by Quantum "
            "ESPRESSO's name: gaussian, mp (Methfessel-Paxton), cold "
            "(Marzari-Vanderbilt) or fd (Fermi-Dirac); defaults to 'cold'. "
            "Fixed occupations are occupations=fixed."
        ),
    },
    "degauss": {
        "structure_specific": False,
        "unit": "Ry",
        "steps": _MESH_STEPS,
        "description": (
            "Smearing width used when occupations=smearing; heuristic default "
            "0.01 Ry for metals."
        ),
    },
    "k_grid": {
        "structure_specific": True,
        "path": ("mesh",),
        "steps": _MESH_STEPS,
        "description": (
            "Explicit Monkhorst-Pack mesh dimensions (nk1, nk2, nk3); wins "
            "outright over k_index/k_distance if more than one is set."
        ),
    },
    "k_index": {
        "structure_specific": True,
        "ml_target": "k_index",
        "steps": _MESH_STEPS,
        "description": (
            "A specific 1-based rung on this structure's own k-mesh ladder, "
            "the distinct meshes its point group maps onto itself (rung 1 is "
            "Gamma-only); wins over k_distance if both are set."
        ),
    },
    "k_distance": {
        "structure_specific": False,
        "unit": "1/Angstrom",
        "ml_target": "k_distance",
        "steps": _MESH_STEPS,
        "description": (
            "Target k-point spacing along each periodic axis; axes the point "
            "group mixes share the larger count, and a vacuum axis always gets "
            "one k-point. Heuristic default is 0.15 for metals or when "
            "metallicity is unknown, 0.30 for a confirmed non-metal."
        ),
    },
    "shift": {
        "structure_specific": False,
        "steps": _MESH_STEPS,
        "description": (
            "K-mesh origin offset per axis (0 or 1); defaults to Gamma-centered."
        ),
    },
    "k_path_distance": {
        "structure_specific": False,
        "unit": "1/Angstrom",
        "description": (
            "Largest spacing between neighbouring points of the high-symmetry "
            "path that a band task's bands step and a phonon task's dispersion "
            "step follow, with 2 pi included as for k_distance: each segment "
            "takes the fewest equal steps no longer than it, except that on "
            "fixed occupations, unless isolation is 'slab', a segment of the "
            "dispersion that ends at Gamma can take a few more (49 becomes 50), "
            "so that matdyn.x lands on Gamma exactly. Default 0.025, "
            "aiida-quantumespresso's bands.yaml. The path is read from the "
            "written cell's own symmetry, so a conventional cell or a supercell "
            "gives folded bands and phonon branches."
        ),
    },
    "nbnd": {
        "structure_specific": True,
        "description": (
            "Total number of Kohn-Sham bands (per spin channel with nspin=2), "
            "overriding the default written otherwise: pw.x's setup.f90 rule, "
            "with a collinear smearing run's majority channel raised for its "
            "seeded moment, and three times the occupied bands on a band task's "
            "bands step (aiida-quantumespresso's bands.yaml). Refused when below "
            "the electrons a spin channel holds (pw.x's 'too few bands'); a "
            "count that holds the moment below its seed gets a warning."
        ),
    },
    "extra_bands": {
        "structure_specific": False,
        "path": None,
        "description": (
            "Extra bands added on top of the default band count (pw.x's "
            "setup.f90 rule, with a collinear smearing run's majority channel "
            "raised for its seeded moment, or three times the occupied bands on "
            "a band task's bands step); a total below the electrons a spin "
            "channel holds is refused."
        ),
    },
    "conv_thr": {
        "structure_specific": False,
        "unit": "Ry",
        "description": (
            "SCF self-consistency energy-convergence threshold; otherwise "
            "scaled per atom. An nscf or bands step, which runs no SCF loop, "
            "takes it as its diagonalization threshold, 0.1 x min(0.01, "
            "conv_thr / nelec) and at least 1e-13."
        ),
    },
    "etot_conv_thr": {
        "structure_specific": False,
        "unit": "Ry",
        "steps": _RELAX_STEPS,
        "description": (
            "Total-energy convergence threshold between ionic steps of a "
            "relax/vc-relax; otherwise scaled per atom."
        ),
    },
    "mixing_beta": {
        "structure_specific": False,
        "default": 0.4,
        "steps": _SCF_LOOP_STEPS,
        "description": "Charge-density mixing parameter for SCF convergence.",
    },
    "electron_maxstep": {
        "structure_specific": False,
        "default": 80,
        "steps": _SCF_LOOP_STEPS,
        "description": "Maximum number of SCF iterations allowed before giving up.",
    },
    "mixing_mode": {
        "structure_specific": False,
        "steps": _SCF_LOOP_STEPS,
        "description": (
            "SCF density-mixing algorithm; heuristic default is local-TF for a "
            "cell with vacuum along any lattice vector (a slab, wire or isolated "
            "system) and plain otherwise, including bulk layered crystals."
        ),
    },
    "mixing_fixed_ns": {
        "structure_specific": False,
        "steps": _SCF_LOOP_STEPS,
        "description": (
            "Number of initial SCF iterations during which pw.x holds the "
            "Hubbard occupation matrix at its starting value (+U runs only). "
            "Unset by default (QE's 0). pw.x can report convergence inside "
            "this window, so energies, forces and stresses from a nonzero "
            "value are not self-consistent DFT+U results; use it only for a "
            "preparatory run whose output seeds a separate run with ns free."
        ),
    },
    "partition": {
        "structure_specific": False,
        "description": "HPC queue/partition to submit to.",
    },
    "nodes": {
        "structure_specific": False,
        "description": (
            "Number of compute nodes requested; otherwise the fewest on which "
            "pw.x's estimated memory per process, for the layout each step "
            "runs, times the tasks per node and a 1.2 safety factor fits a "
            "node."
        ),
    },
    "ntasks": {
        "structure_specific": False,
        "description": (
            "Total number of MPI tasks requested; otherwise nodes x cores_per_node."
        ),
    },
    "walltime_h": {
        "structure_specific": False,
        "unit": "hours",
        "description": (
            "Requested job walltime; heuristic default is the partition's own "
            "maximum. 95% of it is split across the task's pw.x steps as "
            "max_seconds, by estimated workload. The phonon tasks write no "
            "max_seconds: their job timer creates <prefix>.EXIT at 95% of it, "
            "where pw.x or ph.x, whichever is running, stops cleanly."
        ),
    },
    "account": {
        "structure_specific": False,
        "description": (
            "HPC accounting/billing code; personal to the submitter, never guessed."
        ),
    },
    "npool": {
        "structure_specific": True,
        "description": (
            "Number of k-point pools passed to pw.x as -npool; must divide "
            "ntasks. Default: the most pools, up to one per k-point/spin "
            "pair (two per k-point with collinear spin), that keep the pools "
            "at least 80% busy."
        ),
    },
    "ndiag": {
        "structure_specific": True,
        "description": (
            "Linear-algebra group size passed to pw.x as -ndiag; unset by "
            "default so pw.x chooses it from nbnd. Refused when its s x s "
            "grid, s = isqrt(min(ndiag, ntasks/npool)), cannot distribute "
            "nbnd bands (needs nbnd > (s-1)^2)."
        ),
    },
    "ion_dynamics": {
        "structure_specific": False,
        "default": "bfgs",
        "description": (
            "Ionic relaxation algorithm for relax/vc-relax; vc-relax only "
            "accepts 'bfgs' in this codebase (QE couples cell_dynamics to it)."
        ),
    },
    "forc_conv_thr": {
        "structure_specific": False,
        "unit": "Ry/Bohr",
        "description": (
            "Force-convergence threshold of a relaxation. Default: Quantum "
            "ESPRESSO's 1e-3 for the relax and vc-relax tasks, and 1e-4, "
            "aiida-quantumespresso's balanced pw protocol, for the relaxation "
            "of relax-phonon and vc-relax-phonon, where a looser value gets a "
            "warning."
        ),
    },
    "nstep": {
        "structure_specific": False,
        "default": 50,
        "description": "Maximum number of ionic/cell relaxation steps.",
    },
    "trust_radius_max": {
        "structure_specific": False,
        "unit": "Bohr",
        "default": 0.8,
        "description": "Maximum BFGS ionic-displacement trust radius (bfgs only).",
    },
    "trust_radius_min": {
        "structure_specific": False,
        "unit": "Bohr",
        "default": 1.0e-3,
        "description": (
            "Minimum BFGS ionic-displacement trust radius; BFGS resets below "
            "this (bfgs only)."
        ),
    },
    "trust_radius_ini": {
        "structure_specific": False,
        "unit": "Bohr",
        "default": 0.5,
        "description": "Initial BFGS ionic-displacement trust radius (bfgs only).",
    },
    "remove_rigid_rot": {
        "structure_specific": True,
        "default": False,
        "description": (
            "Cancel spurious rigid-body torque for isolated-system relaxation; "
            "trades total-energy/force self-consistency for speed."
        ),
    },
    "fix_bottom_layers": {
        "structure_specific": True,
        "description": (
            "Fix the bottom N atomic layers of a slab (if_pos) during "
            "relax/vc-relax, counted up from the vacuum; refused unless the cell "
            "to be written has one vacuum gap, along exactly one lattice vector, "
            "and at least N layers (atoms within 0.5 Å along the normal share "
            "one). The phonon tasks refuse it: pinned atoms keep their forces, "
            "and the phonons are computed where every force is zero."
        ),
    },
    "cell_dofree": {
        "structure_specific": True,
        "default": "all",
        "steps": ("vc-relax",),
        "description": (
            "Which cell degrees of freedom vc-relax may move, among the values "
            "pw.x honours under the written ibrav = 0 ('volume' and the 'ibrav' "
            "forms are not). Default 'all'; "
            "'2Dxy' for a slab with its vacuum along c, which is written with a "
            "along x and a, b in the xy plane. A wire or a slab with its vacuum "
            "along a or b has no default. '2Dxy' and '2Dshape' are refused unless "
            "a and b lie in the xy plane and any vacuum lies along c; the masks "
            "of Cartesian components ('a', 'b', 'c', 'x', 'y', 'z', 'xy', 'xz', "
            "'yz', 'xyz') are refused when the cell is written rotated."
        ),
    },
    "press": {
        "structure_specific": False,
        "unit": "kbar",
        "default": 0.0,
        "steps": ("vc-relax",),
        "description": "Target external pressure for vc-relax.",
    },
    "press_conv_thr": {
        "structure_specific": False,
        "unit": "kbar",
        "default": 0.5,
        "steps": ("vc-relax",),
        "description": "Pressure-convergence threshold for vc-relax.",
    },
    "cell_factor": {
        "structure_specific": False,
        "default": 2.0,
        "steps": ("vc-relax",),
        "description": (
            "Pseudopotential-table interpolation headroom; must exceed the "
            "maximum linear cell contraction expected during vc-relax."
        ),
    },
    "delta_e": {
        "structure_specific": False,
        "unit": "eV",
        "description": (
            "dos.x energy step of the DOS grid (DeltaE, > 0); default 0.01 eV, "
            "aiida-quantumespresso's pdos.yaml."
        ),
    },
    "emin": {
        "structure_specific": True,
        "unit": "eV",
        "description": (
            "Lower edge of the dos.x energy window (Emin); unset, dos.x's own, "
            "from the lowest band energy. Must be below emax."
        ),
    },
    "emax": {
        "structure_specific": True,
        "unit": "eV",
        "description": (
            "Upper edge of the dos.x energy window (Emax); unset, dos.x's own, "
            "from the highest band energy."
        ),
    },
    "broadening": {
        "structure_specific": False,
        "unit": "Ry",
        "description": (
            "dos.x broadening width (degauss, > 0); unset, the nscf step's "
            "smearing width, or none after tetrahedra occupations, whose "
            "integration dos.x then uses."
        ),
    },
    "ngauss": {
        "structure_specific": False,
        "description": (
            "dos.x broadening function: -99 Fermi-Dirac, -1 cold "
            "(Marzari-Vanderbilt), 0 Gaussian (default) or 1..10 a "
            "Methfessel-Paxton order. dos.x reads it only with a broadening "
            "width, so it needs broadening unless the nscf step uses smearing."
        ),
    },
    "q_grid": {
        "structure_specific": True,
        "path": ("mesh",),
        "description": (
            "Explicit Gamma-centred q-point mesh (nq1, nq2, nq3) of a phonon "
            "task's ph.x run; wins outright over q_distance if both are set. "
            "Each count is at most 1024 and their product at most 49152, "
            "within q2r.x's limits. Refused unless every symmetry operation "
            "pw.x keeps maps it onto itself, with one division along each "
            "vacuum axis and equal counts on two axes an operation mixes, and "
            "refused with more than 1024 irreducible q-points."
        ),
    },
    "q_distance": {
        "structure_specific": False,
        "unit": "1/Angstrom",
        "default": 0.3,
        "description": (
            "Target q-point spacing of a phonon task's ph.x mesh, with 2 pi "
            "included as for k_distance: axes the point group mixes share the "
            "larger count, and a vacuum axis always gets one q-point. Default "
            "0.3, aiida-quantumespresso's ph protocol (balanced). A mesh beyond "
            "q2r.x's limits, more than 1024 divisions along an axis or 1024 "
            "irreducible q-points, is refused. The first step's k-mesh, unless "
            "the request sets it, is raised against the q-mesh: to the next "
            "multiple of each q-axis with smearing or tetrahedra, to at least "
            "it with fixed occupations."
        ),
    },
    "tr2_ph": {
        "structure_specific": False,
        "default": 1.0e-18,
        "description": (
            "Threshold of ph.x's self-consistent linear response (> 0). Default "
            "1e-18, aiida-quantumespresso's ph protocol (balanced); ph.x's own "
            "is 1e-12."
        ),
    },
    "alpha_mix": {
        "structure_specific": False,
        "default": 0.4,
        "description": (
            "Mixing factor of ph.x's linear-response potential, alpha_mix(1), "
            "from 0 to 1, which ph.x applies at every iteration. Default 0.4, "
            "aiida-quantumespresso's ph protocol (balanced); ph.x's own is 0.7."
        ),
    },
    "nmix_ph": {
        "structure_specific": False,
        "default": 8,
        "description": (
            "Number of iterations ph.x's potential mixing uses (>= 1). Default "
            "8, aiida-quantumespresso's ph protocol (balanced); ph.x's own is 4."
        ),
    },
    "asr": {
        "structure_specific": False,
        "default": "simple",
        "description": (
            "Acoustic sum rule q2r.x applies to the effective charges and "
            "matdyn.x to the force constants of the phonon DOS and the "
            "dispersion. Default 'simple', which corrects the on-site force "
            "constants at every q, where the dominant violation, the FFT-grid "
            "error, sits; 'crystal', matdyn.x's projection, corrects that "
            "violation at Gamma only and can leave spurious imaginary modes "
            "elsewhere."
        ),
    },
    "dos_q_distance": {
        "structure_specific": False,
        "unit": "1/Angstrom",
        "default": 0.1,
        "description": (
            "Spacing of the mesh on which matdyn.x interpolates the phonon DOS "
            "(tetrahedra, every 1 cm^-1), with 2 pi included as for "
            "k_distance. Default 0.10, the dos task's nscf spacing "
            "(aiida-quantumespresso's pdos.yaml)."
        ),
    },
}


@dataclass(frozen=True, slots=True)
class _FactMeta:
    """What a fact's record type cannot say: its ML model target and its
    description. The description says what the fact means, never how it
    was resolved -- that is the record's ``source`` and provenance, and it
    differs per tier. ``_facts()`` derives the rest."""

    key: str
    ml_target: str | None
    description: str


_FACTS: tuple[_FactMeta, ...] = (
    _FactMeta(
        key="is_metal",
        ml_target="is_metal",
        description="Whether the structure is metallic (zero DFT band gap).",
    ),
    _FactMeta(
        key="is_magnetic",
        ml_target="is_magnetic",
        description="Whether the structure is expected to be magnetic.",
    ),
    _FactMeta(
        key="needs_soc",
        ml_target=None,
        description=(
            "Whether spin-orbit coupling is likely relevant for this structure. "
            "Advice only: the spin_orbit_coupling setting enables it."
        ),
    ),
    _FactMeta(
        key="needs_correlation",
        ml_target=None,
        description="Whether a Hubbard +U (or hybrid) correction is likely needed.",
    ),
)


def _unwrap_optional(annotation: object) -> object:
    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _json_type(annotation: object) -> dict[str, object]:
    annotation = _unwrap_optional(annotation)
    origin = typing.get_origin(annotation)
    if origin is Literal:
        return {"type": "string", "enum": sorted(typing.get_args(annotation))}
    if origin is tuple:
        args = typing.get_args(annotation)
        return {
            "type": "array",
            "items": _json_type(args[0])["type"] if args else "integer",
            "minItems": len(args) or None,
            "maxItems": len(args) or None,
        }
    if origin is dict:
        return {"type": "object"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    return {"type": "string"}


@dataclass(frozen=True, slots=True)
class SettingBinding:
    """One ``--set``-able key's construction recipe, alongside its
    display metadata -- the single walk ``_leaves()`` below performs
    once, shared by ``capabilities()`` (projects to JSON) and the
    shared request-validation layer, so the two can never drift apart
    by walking the override tree two different ways.

    ``branch`` names the composing class this key belongs to;
    ``outer_field`` is that class's own field name
    (``SystemOverrides.cutoffs``, say); ``inner_field`` is the field
    *inside* the ``HumanInput`` class for a wrapped setting, or ``None``
    for a plain-typed one (``pseudo_table_id``) where ``outer_field``
    *is* the setting. ``json_type`` is ``_json_type(annotation)``,
    computed once here rather than re-derived by every consumer --
    the shared request-validation layer's CLI string-coercion reads
    ``json_type["type"]`` directly instead of importing this module's
    own private type-mapping helper.

    ``steps`` are the step purposes the key applies to, ``None`` for a
    system or task setting (set once per task); ``tasks`` and ``programs``
    follow from them (module docstring). ``set_overrides`` routes a request
    by ``steps`` (#154).
    """

    key: str
    group: str
    branch: _Branch
    outer_field: str
    inner_field: str | None
    human_input_cls: type | None
    annotation: object
    json_type: dict[str, object]
    scope: _Scope
    steps: tuple[str, ...] | None
    tasks: tuple[str, ...]
    programs: tuple[str, ...] | None


def _binding(
    branch: _Branch,
    scope: _Scope,
    outer_field: str,
    inner_field: str | None,
    human_input_cls: type | None,
    annotation: object,
) -> SettingBinding:
    name = inner_field or outer_field
    # Analysis leaves always keep their bare field name: they must match
    # `_FACTS`'s own keys exactly (`_settings()` filters them out and
    # `_facts()` derives `overridable` by that same key), and
    # `_SETTING_META`'s one rename entry ("needs_correlation" ->
    # "hubbard_needs_correlation") exists for hubbard_u's *own* field of the
    # same inner name, not this one -- see this module's own docstring on
    # that collision.
    extra = _SETTING_META.get(name, {}) if branch != "analysis" else {}
    steps = extra.get("steps", _BRANCH_STEPS[branch])
    tasks, programs = _TASK_IDS, None
    if steps is not None:
        planned = [(task, step) for task in _TASK_IDS for step in expand_task(task)]
        applied = [(task, step) for task, step in planned if step.purpose in steps]
        tasks = tuple(dict.fromkeys(task for task, _step in applied))
        programs = tuple(sorted({step.program for _task, step in applied}))
    return SettingBinding(
        key=extra.get("key", name),
        group=outer_field,
        branch=branch,
        outer_field=outer_field,
        inner_field=inner_field,
        human_input_cls=human_input_cls,
        annotation=annotation,
        json_type=_json_type(annotation),
        scope=scope,
        steps=steps,
        tasks=tasks,
        programs=programs,
    )


def _leaves_from_overrides(
    overrides_cls: type, *, branch: _Branch, scope: _Scope
) -> list[SettingBinding]:
    hints = typing.get_type_hints(overrides_cls)
    leaves: list[SettingBinding] = []
    for name, annotation in hints.items():
        if name.endswith("_llm"):
            continue
        inner = _unwrap_optional(annotation)
        if not (isinstance(inner, type) and hasattr(inner, "model_fields")):
            leaves.append(_binding(branch, scope, name, None, None, inner))
            continue
        # `include_extras=False` (the default) strips any per-element
        # `Annotated[int, Field(gt=0)]` metadata a field's own tuple members
        # carry (e.g. KSamplingHumanInput.k_grid) back down to the plain
        # `tuple[int, int, int]` shape `_json_type` expects -- reading
        # `model_fields[name].annotation` directly would leave `Annotated`
        # wrappers in place instead, since pydantic keeps per-element
        # constraint metadata on the type itself, not lifted to `FieldInfo`.
        inner_hints = typing.get_type_hints(inner)
        leaves.extend(
            _binding(branch, scope, name, field, inner, inner_hints[field])
            for field in inner.model_fields
        )
    return leaves


def _leaves() -> list[SettingBinding]:
    return [
        *_leaves_from_overrides(AnalysisOverrides, branch="analysis", scope="system"),
        *_leaves_from_overrides(SystemOverrides, branch="system", scope="system"),
        *_leaves_from_overrides(JobOverrides, branch="job", scope="task"),
        *_leaves_from_overrides(KpointsOverrides, branch="kpoints", scope="per_step"),
        *_leaves_from_overrides(
            ResourceOverrides, branch="resources", scope="per_step"
        ),
        *_leaves_from_overrides(RelaxOverrides, branch="relax", scope="per_step"),
        *_leaves_from_overrides(DosOverrides, branch="dos", scope="per_step"),
        *_leaves_from_overrides(KPathOverrides, branch="k_path", scope="per_step"),
        *_leaves_from_overrides(PhOverrides, branch="ph", scope="per_step"),
        *_leaves_from_overrides(Q2rOverrides, branch="q2r", scope="per_step"),
        *_leaves_from_overrides(
            PhononDosOverrides, branch="phonon_dos", scope="per_step"
        ),
    ]


def bindings() -> dict[str, SettingBinding]:
    """Every ``--set``-able key's construction recipe, keyed by its
    exposed capabilities key -- used by the shared request-validation
    layer to turn ``{key: value}`` into a real ``RunOverrides``, and by
    nothing inside this module (``_settings()`` below projects the same
    ``_leaves()`` call to JSON instead)."""
    return {leaf.key: leaf for leaf in _leaves()}


def _listed(values: tuple[str, ...] | None) -> list[str] | None:
    return None if values is None else list(values)


def _resolved_in(leaf: SettingBinding, extra: _SettingExtra) -> ResolvedIn:
    """Where ``leaf``'s resolved value is published: by default in the
    record of its group (the advisor its override feeds, named like the
    override field), under its own field name; ``extra`` declares the
    exceptions (``_SettingExtra``)."""
    field = leaf.inner_field or leaf.outer_field
    path = extra.get("path", (field,))
    return {
        "record": extra.get("record", leaf.group),
        "path": _listed(path),
    }


def _setting_from_leaf(leaf: SettingBinding) -> Setting:
    """``leaf`` projected to the published shape. Raises ``KeyError`` for a
    setting without a ``_SETTING_META`` entry or without its
    ``structure_specific`` declaration."""
    extra = _SETTING_META[leaf.inner_field or leaf.outer_field]
    ml_target = extra.get("ml_target")
    setting: Setting = {
        "key": leaf.key,
        "group": leaf.group,
        **leaf.json_type,
        "unit": extra.get("unit"),
        "codes": [_CODE],
        "tasks": list(leaf.tasks),
        "steps": _listed(leaf.steps),
        "programs": _listed(leaf.programs),
        "scope": leaf.scope,
        "structure_specific": extra["structure_specific"],
        "resolved_in": _resolved_in(leaf, extra),
        "ml_target": ml_target,
        "approaches": _approaches(ml_target),
        "description": extra.get("description", ""),
    }
    if "default" in extra:
        setting["default"] = extra["default"]
    if "enum_from" in extra:
        setting["enum_from"] = extra["enum_from"]
    return setting


def _settings() -> list[Setting]:
    """Every ``--set``-able leaf *except* the overridable analysis facts
    (``is_metal``/``is_magnetic``/``needs_correlation``): ``facts()``
    already describes them, with the type and values of the record their
    override is typed by. They still walk through ``_leaves()`` so
    ``bindings()`` (the `--set`/override construction path) accepts them;
    only this JSON projection skips them."""
    fact_keys = {fact.key for fact in _FACTS}
    return [_setting_from_leaf(leaf) for leaf in _leaves() if leaf.key not in fact_keys]


def _fact_schema(record: object) -> tuple[str, list[str] | None]:
    """A fact's published ``type`` and ``values`` from its ``AnalysisFacts``
    record type ``FieldState[T]``: ``("enum", members)`` for a ``Literal``
    ``T``, ``("boolean", None)`` for ``bool``. Raises ``TypeError`` for any
    other ``T``, which has no scalar fact shape."""
    (value_type,) = typing.get_args(record)
    json_type = _json_type(value_type)
    if "enum" in json_type:
        return "enum", list(json_type["enum"])
    if json_type["type"] == "boolean":
        return "boolean", None
    raise TypeError(f"fact record type {value_type!r} is neither a Literal nor bool")


def _facts() -> list[Fact]:
    """``_FACTS`` projected to the published shape. ``approaches`` is
    computed per call, not at import time, since ``_approaches`` checks
    live installed-asset state (v2 epic 11, #11). A fact is overridable
    exactly when its key has an analysis binding (a ``HumanInput`` on
    ``AnalysisOverrides``); one without a binding (``needs_soc``, #186)
    lists no ``human`` approach."""
    records = typing.get_type_hints(AnalysisFacts)
    bound = {leaf.key for leaf in _leaves() if leaf.branch == "analysis"}
    facts: list[Fact] = []
    for meta in _FACTS:
        fact_type, values = _fact_schema(records[meta.key])
        overridable = meta.key in bound
        approaches = _approaches(meta.ml_target)
        facts.append(
            Fact(
                key=meta.key,
                type=fact_type,
                values=values,
                ml_target=meta.ml_target,
                approaches=[
                    source for source in approaches if overridable or source != "human"
                ],
                overridable=overridable,
                description=meta.description,
            )
        )
    return facts


def _pseudopotential_tables() -> list[dict[str, object]]:
    return [
        {
            "id": table.id,
            "provider": table.provider,
            "version": table.version,
            "functional": table.functional,
            "relativistic": table.relativistic,
            "accuracy": table.accuracy,
            "elements": list(table.elements),
            "licence": table.licence,
            "citation": table.citation,
            "default": table.default,
        }
        for table in load_tables().values()
    ]


def _hpc_profiles() -> list[dict[str, object]]:
    profiles = []
    for name in list_hpc_profiles():
        profile = load_hpc_profile(name)
        profiles.append(
            {
                "id": name,
                "name": profile.name,
                "scheduler": profile.scheduler,
                "partitions": sorted(profile.partitions),
            }
        )
    return profiles


def _codes() -> list[dict[str, object]]:
    return [
        {
            "id": _CODE,
            "name": "Quantum ESPRESSO",
            "tasks": list(_TASK_IDS),
        }
    ]


def _tasks() -> list[dict[str, object]]:
    return [
        {
            "id": _TASK,
            "name": "Single-point SCF",
            "description": "One self-consistent-field calculation, no relaxation.",
            "codes": [_CODE],
            "step_count": 1,
            "executables": [_PROGRAM],
        },
        {
            "id": _DOS_TASK,
            "name": "Density of states",
            "description": (
                "scf, then a denser nscf pass, then dos.x -- three steps "
                "sharing one prefix/outdir (v2 epic 9, #9). Unless set, the "
                "nscf step takes k_distance 0.10 and tetrahedra_opt "
                "occupations from aiida-quantumespresso's pdos.yaml protocol."
            ),
            "codes": [_CODE],
            "step_count": 3,
            "executables": [_PROGRAM, _PROGRAM, "dos.x"],
        },
        {
            "id": _BAND_TASK,
            "name": "Band structure",
            "description": (
                "scf, then pw.x with calculation='bands' along the written "
                "cell's high-symmetry path (K_POINTS crystal_b), then bands.x "
                "once per spin channel -- three steps sharing one prefix/outdir. "
                "Unless set, the bands step takes k_path_distance 0.025 and three "
                "times the occupied bands from aiida-quantumespresso's bands.yaml "
                "protocol."
            ),
            "codes": [_CODE],
            "step_count": 3,
            "executables": [_PROGRAM, _PROGRAM, "bands.x"],
        },
        {
            "id": _RELAX_TASK,
            "name": "Ionic relaxation",
            "description": (
                "One pw.x run, calculation='relax': scf plus BFGS/damped/FIRE "
                "ionic-position optimization (v2 epic 10, #10)."
            ),
            "codes": [_CODE],
            "step_count": 1,
            "executables": [_PROGRAM],
        },
        {
            "id": _VC_RELAX_TASK,
            "name": "Variable-cell relaxation",
            "description": (
                "One pw.x run, calculation='vc-relax': scf plus BFGS ionic "
                "and cell relaxation together (v2 epic 10, #10)."
            ),
            "codes": [_CODE],
            "step_count": 1,
            "executables": [_PROGRAM],
        },
        {
            "id": _PHONON_TASK,
            "name": "Phonon (no relaxation)",
            "description": (
                "scf, then ph.x on a q-point mesh (DFPT), q2r.x, and matdyn.x "
                "for the phonon DOS and for the dispersion along the band "
                "task's path -- five steps in one job sharing one "
                "prefix/outdir, with d3hess.x before ph.x under DFT-D3. The "
                "phonons are computed at the written geometry, so relax it "
                "first or use relax-phonon. Unless set, the q-mesh takes "
                "q_distance 0.3 from aiida-quantumespresso's ph protocol, and "
                "the scf k-mesh is raised against it; the dispersion takes "
                "k_path_distance 0.025 from its bands protocol."
            ),
            "codes": [_CODE],
            "step_count": 5,
            "executables": [_PROGRAM, "ph.x", "q2r.x", "matdyn.x", "matdyn.x"],
        },
        {
            "id": _RELAX_PHONON_TASK,
            "name": "Phonon (incl. relaxation)",
            "description": (
                "A fixed-cell relax, then ph.x on its save on a q-point mesh "
                "(DFPT), q2r.x, and matdyn.x for the phonon DOS and for the "
                "dispersion along the band task's path -- five steps in one "
                "job sharing one prefix/outdir, with d3hess.x before ph.x "
                "under DFT-D3. Unless set, the relaxation takes forc_conv_thr "
                "1e-4 from aiida-quantumespresso's pw protocol, the q-mesh "
                "q_distance 0.3 from its ph protocol and the dispersion "
                "k_path_distance 0.025 from its bands protocol, and the "
                "relaxation's k-mesh is raised against the q-mesh."
            ),
            "codes": [_CODE],
            "step_count": 5,
            "executables": [_PROGRAM, "ph.x", "q2r.x", "matdyn.x", "matdyn.x"],
        },
        {
            "id": _VC_RELAX_PHONON_TASK,
            "name": "Phonon (incl. vc-relaxation)",
            "description": (
                "A vc-relax, then ph.x on the relaxed cell's save on a q-point "
                "mesh (DFPT), q2r.x, and matdyn.x for the phonon DOS and for "
                "the dispersion along the band task's path -- five steps in one "
                "job sharing one prefix/outdir, with d3hess.x before ph.x under "
                "DFT-D3. Refused on a cell whose FFT grid, rebuilt by the "
                "vc-relax, ph.x can refuse; relax-phonon runs there. Unless "
                "set, the relaxation takes forc_conv_thr 1e-4 from "
                "aiida-quantumespresso's pw protocol, the q-mesh q_distance 0.3 "
                "from its ph protocol and the dispersion k_path_distance 0.025 "
                "from its bands protocol; the q-mesh, the relaxation's k-mesh, "
                "raised against it, and the path are built on the input cell."
            ),
            "codes": [_CODE],
            "step_count": 5,
            "executables": [_PROGRAM, "ph.x", "q2r.x", "matdyn.x", "matdyn.x"],
        },
    ]


def _warnings() -> list[dict[str, object]]:
    """Every advisor's catalogue, then the request-routing notices
    (``service.OVERRIDES_WARNING_CATALOGUE``, #154)."""
    return [
        warning.model_dump()
        for warning in (*_ADVISOR_WARNING_CATALOGUE, *OVERRIDES_WARNING_CATALOGUE)
    ]


def _models() -> list[dict[str, object]]:
    """Every ML model registry.toml declares (v2 epic 11, #11) --
    registered, not necessarily installed; a fact's own ``approaches``
    (``_approaches`` above) is the honest "is ml actually usable right
    now" signal, checked per asset. This listing is what registered
    against which target, for a caller that wants to know which models
    exist at all."""
    from goldilocks_core.ml.models import registered_models

    return [
        {
            "id": model.id,
            "role": model.role,
            "name": model.spec.name,
            "version": model.spec.version,
            "target": model.spec.target,
        }
        for model in registered_models()
    ]


def capabilities() -> Capabilities:
    """Everything the design doc's S4.2 shape lists. Cacheable in-process
    per that section's own note ("static... only `models` needs to query
    ml") -- callers needing a fresh read after installing a new
    pseudopotential table or HPC profile file should call this again
    rather than expect a long-lived cache here; this function itself
    does no caching."""
    return {
        "core_version": package_version("goldilocks-core"),
        "vocabulary_version": VOCABULARY_VERSION,
        "codes": _codes(),
        "tasks": _tasks(),
        "facts": _facts(),
        "settings": _settings(),
        "pseudopotential_tables": _pseudopotential_tables(),
        "hpc_profiles": _hpc_profiles(),
        "models": _models(),
        "warnings": _warnings(),
        "sources": list(SOURCES),
    }
