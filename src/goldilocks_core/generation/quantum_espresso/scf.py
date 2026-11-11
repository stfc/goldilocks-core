"""write_qe_scf: render one ``pw.x`` scf ``Step`` from resolved settings.

New in v2 (v2 epic 7, #7). Rewrites ``generation/qe/scf.py`` (v1, 270
lines) as pure translation: every value written here traces to an
already-resolved ``SystemSettings``/``PwSettings`` field, and every
``if`` below formats a value or validates input shape -- none of them
choose one, per this epic's own invariant
(goldilocks-core-design.md:1049: "generation never makes a scientific
choice, only translation and formatting").

Card-writing knowledge (``ATOMIC_SPECIES``/``ATOMIC_POSITIONS``/
``CELL_PARAMETERS``/``K_POINTS``) is reused as content from v1's
``atomic_species``/``atomic_positions``/``cell_parameters``/
``k_points`` (``generation/qe/scf.py:225-262``), restructured against
the new types; namelist formatting (``&CONTROL``/``&SYSTEM``/
``&ELECTRONS``) is delegated to ``namelists.render_namelist`` instead of
v1's own hand-written ``_control_section``/``_system_section``/
``_electrons_section``.

``max_seconds`` (&CONTROL) is ``PwSettings.max_seconds``, this step's
own share of the task's walltime (``JobDecision.max_seconds_by_step``,
``advisors/job_resources.py``): pw.x counts it from its own start, so
every step of a multi-step task needs its own. It has to be baked into
the input file at generation time, not injected by
``submission/slurm.py`` at runtime -- pw.x has no command-line switch
for it, and editing the input file after generation would mean the
published ``goldilocks.json`` sha256 no longer describes the bytes
actually run (goldilocks-core-design.md:1230-1237, publication
guarantee 3). The allocation itself (``nodes``/``ntasks``/
``walltime_h``/``partition``) is ``submission/slurm.py``'s concern, not
this writer's. A step without a share (``None``: its task runs a job
timer instead, ``JobDecision.timer_seconds``, #215) is written without
``max_seconds``, so pw.x keeps its default of 1e7 s (QE 7.3
``Modules/input_parameters.f90:174``, ``PW/src/input.f90:1266``) and
stops at the timer's stop file instead.

Structure always comes from ``system.magnetic.cell``, the simulated cell,
never a separately-passed ``Structure`` -- goldilocks-qe-pw-parameter-audit
finding F18 (also goldilocks-core-design.md:2854): every card in a
multi-step task must be generated from the *same* cell, or a later step's
``ATOMIC_SPECIES`` can silently disagree with an earlier one's. Taking it
as a separate parameter would let a caller pass a different (unlabeled)
structure by mistake; reading it off ``system`` makes that impossible by
construction. Every count rendered here (``nbnd``, ``conv_thr``, the
charge) was decided on that same cell (#128). Its species are rendered as
the cell carries them, one ``ATOMIC_SPECIES`` entry per site label: the
magnetic step splits the cell into species (``advisors/species_split.py``)
before symmetry and k-points are counted, so this writer never regroups
sites -- regrouping here once let the counted symmetry describe other
species than the ones written (#170). Its orientation is chosen upstream
too: pw.x finds symmetry by testing fixed Cartesian rotations against the
cell as given, so the magnetic step writes the cell where that test finds
the most of its point group (``pw_symmetry.pw_frame``, #140), and this writer
renders its lattice vectors and fractional coordinates as they are. The
cell copied verbatim in pymatgen's frame once showed pw.x 4 of diamond
Si's 48 operations, so it ran six times the k-points ``n_irr_k`` counted.

**v1 bugs this fixes (issue #7, section (c)):**

- Bracket-access into a plain ``dict``, bare ``KeyError`` on a
  missing/renamed key (``generation/qe/scf.py:167,186-188,194-195,
  217-219``) -- every lookup here is a typed dataclass attribute, and
  every value-shape problem raises ``GenerationError`` at this
  boundary, never a raw ``KeyError``.
- Unconditional hardcoded literals with no provenance
  (``generation/qe/scf.py:134-135,153``: ``pseudo_dir``/``outdir``/
  ``ibrav``) -- ``pseudo_dir``/``outdir``/``prefix`` now come from a
  constructed ``SharedContext`` (``steps.py``); ``ibrav = 0`` is the one
  literal kept unconditional, because it is not a scientific choice but
  a fixed consequence of this writer always emitting an explicit
  ``CELL_PARAMETERS`` card (QE requires ``ibrav=0`` whenever the cell is
  given explicitly rather than derived from Bravais-lattice parameters).
  With ``ibrav=0`` pw.x finds only the symmetry the card's orientation
  shows it, which is why the cell is framed upstream (above).
- ``if`` branches that pick a value (``_smearing_lines``/``_spin_lines``/
  ``_vdw_lines``, ``generation/qe/scf.py:166-211``) -- every decision
  those made now happens upstream, in ``advisors/occupations.py``/
  ``magnetic_config.py``/``vdw_method.py``. What looks like branching
  below only decides *whether a keyword applies at all* given an
  already-resolved fact (e.g. ``vdw_corr`` is only meaningful when
  ``vdw.use_vdw`` is true) or *which QE spelling* an already-chosen
  value maps to (``_QE_VDW_CORR``, ``_QE_ASSUME_ISOLATED``) -- never which
  value to choose.

**Hubbard ``HUBBARD`` card (v2 #88).** In QE >= 7.1 only the inter-site
``V`` line is atom-index-keyed (QE 7.3 ``Doc/Hubbard_input.tex``,
``Modules/read_cards.f90``'s ``card_hubbard``); the onsite ``U`` line,
the only Hubbard parameter ``HubbardUDecision`` models, is keyed by
atomic *type* (species label) plus its Hubbard manifold, e.g.
``U Mn-3d 5.0``. ``hubbard_lines`` renders one such line per species
label whose element has a U value, under the projector type the decision
names, and no card when none does, so every resolved Hubbard decision
renders (#135).

**Shared with the bands writer (#118).** ``generation/quantum_espresso/
bands.py`` renders ``bands.in`` with this module's namelist and card
helpers, so its species and every keyword that defines the Hamiltonian
repeat ``scf.in``'s, and writes its ``K_POINTS crystal_b`` rows with
``format_float``; only that card is its own.

**The phonon tasks' first step (#215).** ``system_keywords`` adds
``PwSettings.dfpt_system_keywords``: nr1-nr3, the dense FFT grid ph.x
accepts where it would refuse pw.x's own, and ``dftd3_threebody =
.false.``, so that the energy and forces use the two-body D3 of d3hess.x's
Hessian. ``relax.py`` shares ``system_keywords``, so relax.in and
vc-relax.in carry them too; no other task sets them.

**Still not in this epic's scope, on purpose:**

- ``ConvergenceDecision.etot_conv_thr``/``RelaxOptions``. QE only
  consults ``etot_conv_thr``/``forc_conv_thr`` for ionic minimization
  (``calculation`` in ``{relax, vc-relax, md, ...}``); a plain ``scf``
  calculation has no ionic loop to compare energies across, so this
  writer never emits either -- ``generation/quantum_espresso/relax.py``
  (v2 epic 10, #10) is the writer that does, reusing this module's own
  ``control_keywords``/``system_keywords``/``electrons_keywords``/
  ``atomic_species``/``cell_parameters``/``atomic_positions``/
  ``k_points``/``validated_pseudo_by_element`` (un-privatized for that
  reuse) rather than duplicating them.
- ``nosym``/``noinv``/``no_t_rev``. No setting decides them, so pw.x runs
  with its defaults, which ``advisors/n_irr_k.py`` counts k-points with
  (#225).
"""

from __future__ import annotations

import re
from typing import Literal

from pymatgen.core.periodic_table import Element

from goldilocks_core.advisors.boundary import BoundaryFacts, Isolation
from goldilocks_core.generation.errors import GenerationError
from goldilocks_core.generation.quantum_espresso.namelists import render_namelist
from goldilocks_core.step_settings import PwSettings
from goldilocks_core.steps import ExitStatusCheck, SharedContext, Step
from goldilocks_core.system_settings import SystemSettings

_QE_VDW_CORR: dict[str, tuple[str, int | None]] = {
    "d3bj": ("grimme-d3", 4),
}
"""Our own vdW-method vocabulary (``advisors/vdw_method.py``'s ``VdwMethod``)
-> QE's own keyword spelling. A name translation, not a decision: which
method to use was already decided upstream; only its QE spelling is
resolved here (matches v1's ``_QE_VDW_CORR``, ``generation/qe/scf.py:16-21``,
restricted to the one method ``VdwMethod`` currently allows)."""

_QE_ASSUME_ISOLATED: dict[Isolation, str] = {
    "slab": "2D",
    "isolated": "martyna-tuckerman",
}
"""``BoundaryFacts.isolation`` -> QE's ``assume_isolated`` spelling (QE 7.3
PW/src/input.f90:1332-1359). 'periodic' writes no keyword, QE's default
'none'."""

_SAFE_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")

_CARD_ZERO = 1e-10
"""Card values of smaller magnitude are written as ``0`` (#178): A for the
lattice, crystal units for coordinates. It removes the ~1e-16 A left where
a lattice vector has a zero component (cos(90 deg) in a pymatgen lattice
built from its angles, or a cell turned into its standard orientation) and
the ~1e-36 coordinates some CIFs list (MC3D CrO2, LiCoO2), far below pw.x's
symmetry tolerances (1e-6 for the lattice, 1e-5 for atoms).
``pw_symmetry.pw_frame`` already writes components within 1e-12 of 0 as 0
in the cell it frames; this snap is the writer's own and covers every card
value, including a cell ``pw_frame`` returns as it is and residues between
1e-12 and 1e-10."""


def write_qe_scf(
    system: SystemSettings,
    step: PwSettings,
    ctx: SharedContext,
    purpose: Literal["scf", "nscf"] = "scf",
) -> list[Step]:
    """``purpose`` (v2 epic 9, #9) selects QE's own ``&CONTROL
    calculation`` value and this step's name/filenames -- both real,
    documented ``pw.x`` values, not a new scientific choice this writer
    makes (the *decision* to run an nscf step at all, with what k-mesh/
    occupations, is ``service/_dos.py``'s job, upstream of here). Added
    once ``dos``'s nscf step became a second real caller; ``scf`` stays
    the default so every existing caller is unaffected.
    """
    structure = system.magnetic.cell
    if step.relax is not None:
        raise GenerationError(
            "write_qe_scf does not render a relax/vc-relax input; "
            "PwSettings.relax must be None for an scf step"
        )
    for name, value in (
        ("occupations", step.occupations),
        ("k_sampling", step.k_sampling),
        ("nbnd", step.nbnd),
        ("convergence", step.convergence),
        ("parallel", step.parallel),
    ):
        if value is None:
            raise GenerationError(
                f"PwSettings.{name} is required to generate {purpose}.in"
            )
    elements = sorted({site.specie.symbol for site in structure})
    pseudo_by_element = validated_pseudo_by_element(elements, system)
    species_labels = sorted({site.label for site in structure})
    label_to_element = {site.label: site.specie.symbol for site in structure}
    species_index = {label: index + 1 for index, label in enumerate(species_labels)}

    keywords: dict[str, object] = {}
    keywords.update(control_keywords(ctx, system.boundary, step, purpose))
    keywords.update(
        system_keywords(structure, system, step, len(species_labels), species_index)
    )
    keywords.update(electrons_keywords(step))

    lines = [render_namelist(keywords)]
    lines.append(atomic_species(species_labels, label_to_element, pseudo_by_element))
    lines.append(cell_parameters(structure))
    lines.append(atomic_positions(structure))
    lines.append(k_points(step))
    lines.extend(hubbard_lines(system, label_to_element))
    content = "\n".join(lines)

    args = ["-npool", str(step.parallel.npool)]
    if step.parallel.ndiag is not None:
        args += ["-ndiag", str(step.parallel.ndiag)]
    args += ["-in", f"{purpose}.in"]

    return [
        Step(
            name=purpose,
            executable="pw.x",
            args=tuple(args),
            files={f"{purpose}.in": content},
            stdout=f"{purpose}.out",
            completion=pw_exit_status_check(ctx),
        )
    ]


def pw_exit_status_check(ctx: SharedContext) -> ExitStatusCheck:
    """How the submission script decides a ``pw.x`` step finished: the
    ``<exit_status>`` in ``<outdir>/<prefix>.save/data-file-schema.xml``.
    QE 7.3 writes that file on every ``punch`` (``PW/src/punch.f90:77``),
    including after a non-converged or ``max_seconds`` stop
    (``run_pwscf.f90:197-212``); the ``<outdir>/<prefix>.xml`` copy is
    made only by ``punch('all')`` (``punch.f90:110-120``), so it is
    missing or stale after exactly those stops."""
    return ExitStatusCheck(f"{ctx.outdir}/{ctx.prefix}.save/data-file-schema.xml")


def validated_pseudo_by_element(
    elements: list[str], system: SystemSettings
) -> dict[str, object]:
    pseudo_by_element = {pseudo.element: pseudo for pseudo in system.pseudopotentials}
    if len(pseudo_by_element) != len(system.pseudopotentials):
        raise GenerationError("pseudopotential selection contains duplicate elements")
    missing = sorted(set(elements) - set(pseudo_by_element))
    extra = sorted(set(pseudo_by_element) - set(elements))
    if missing or extra:
        raise GenerationError(
            "pseudopotential selection coverage mismatch; "
            f"missing: {', '.join(missing) or 'none'}; "
            f"extra: {', '.join(extra) or 'none'}"
        )
    for symbol, pseudo in pseudo_by_element.items():
        if pseudo.functional != system.functional:
            raise GenerationError(
                f"pseudopotential functional mismatch for {symbol}: "
                f"calculation requires {system.functional}, selected "
                f"{pseudo.functional or 'unknown'}"
            )
        if _SAFE_FILENAME.fullmatch(pseudo.filename) is None:
            raise GenerationError(
                f"unsafe pseudopotential filename: {pseudo.filename!r}"
            )
    return pseudo_by_element


def control_keywords(
    ctx: SharedContext,
    boundary: BoundaryFacts,
    step: PwSettings,
    purpose: Literal["scf", "nscf", "bands", "relax", "vc-relax"],
) -> dict[str, object]:
    """``&CONTROL`` keywords. ``max_seconds`` is written only when the step
    has a share of the walltime (module docstring).

    ``tprnfor`` and ``tstress`` are written only for the steps that compute
    forces and stress (#289): pw.x ignores both in an nscf or bands step,
    resetting lforce (QE 7.3 PW/src/input.f90:466, 471) and keeping the
    stress only for a self-consistent run (input.f90:646). ``tstress`` is
    also left out when ``boundary`` is 'isolated': pw.x computes no stress
    under Martyna-Tuckerman and clears the flag (input.f90:1361-1365), even
    for vc-relax, where input.f90:646 switches it on. Under '2D', 'slab', it
    computes the stress in a two-dimensional framework
    (PW/Doc/INPUT_PW.def:1655-1675)."""
    keywords: dict[str, object] = {
        "calculation": purpose,
        "prefix": ctx.prefix,
        "outdir": ctx.outdir,
        "pseudo_dir": ctx.pseudo_dir,
    }
    if step.max_seconds is not None:
        keywords["max_seconds"] = step.max_seconds
    if purpose in ("scf", "relax", "vc-relax"):
        keywords["tprnfor"] = True
        if boundary.isolation != "isolated":
            keywords["tstress"] = True
    if step.relax is not None:
        # forc_conv_thr/etot_conv_thr/nstep are real &CONTROL keys, not
        # &IONS ones (INPUT_PW.txt, ASE's own ALL_KEYS['pw']['control']
        # registry, both checked 2026-09-14) -- only reachable when
        # step.relax is set, i.e. only from write_qe_relax
        # (generation/quantum_espresso/relax.py, v2 epic 10, #10);
        # write_qe_scf itself still rejects a non-None step.relax.
        keywords["forc_conv_thr"] = step.relax.forc_conv_thr
        keywords["etot_conv_thr"] = step.relax.etot_conv_thr
        keywords["nstep"] = step.relax.nstep
    return keywords


def system_keywords(
    structure,
    system: SystemSettings,
    step: PwSettings,
    ntyp: int,
    species_index: dict[str, int],
) -> dict[str, object]:
    keywords: dict[str, object] = {
        "ibrav": 0,
        "nat": len(structure),
        "ntyp": ntyp,
        "ecutwfc": system.cutoffs.ecutwfc_ry,
        "ecutrho": system.cutoffs.ecutrho_ry,
        "nbnd": step.nbnd.nbnd,
        **step.dfpt_system_keywords,
    }
    keywords.update(_occupations_keywords(step))
    keywords.update(_magnetic_keywords(system, step, species_index))
    keywords.update(_charge_keywords(system))
    if system.vdw.use_vdw:
        if system.vdw.method not in _QE_VDW_CORR:
            raise GenerationError(
                f"unsupported Quantum ESPRESSO vdW method: {system.vdw.method!r}"
            )
        vdw_corr, dftd3_version = _QE_VDW_CORR[system.vdw.method]
        keywords["vdw_corr"] = vdw_corr
        if dftd3_version is not None:
            keywords["dftd3_version"] = dftd3_version
    assume_isolated = _QE_ASSUME_ISOLATED.get(system.boundary.isolation)
    if assume_isolated is not None:
        keywords["assume_isolated"] = assume_isolated
    return keywords


def _occupations_keywords(step: PwSettings) -> dict[str, object]:
    decision = step.occupations
    keywords: dict[str, object] = {"occupations": decision.occupations}
    if decision.occupations == "smearing":
        keywords["smearing"] = decision.smearing_type
        keywords["degauss"] = decision.degauss
    return keywords


def _magnetic_keywords(
    system: SystemSettings, step: PwSettings, species_index: dict[str, int]
) -> dict[str, object]:
    """The keywords of ``magnetic.spin_mode`` (#146): ``noncollinear``
    writes ``noncolin``/``lspinorb``, ``collinear`` writes ``nspin = 2``
    and the moment the occupations decision pins
    (``OccupationsDecision.tot_magnetization``, 0 included: the one
    rendered moment, #138), ``none`` writes neither; then the starting
    moments and angles, by species label."""
    magnetic = system.magnetic
    keywords: dict[str, object] = {}
    if magnetic.spin_mode == "noncollinear":
        keywords["noncolin"] = True
        keywords["lspinorb"] = True
    elif magnetic.spin_mode == "collinear":
        keywords["nspin"] = 2
        moment = step.occupations.tot_magnetization
        if moment is not None:
            keywords["tot_magnetization"] = moment
    for field_name, values in (
        ("starting_magnetization", magnetic.starting_magnetization),
        ("angle1", magnetic.angle1),
        ("angle2", magnetic.angle2),
    ):
        if not values:
            continue
        for label, value in values.items():
            keywords[f"{field_name}({species_index[label]})"] = value
    return keywords


def _charge_keywords(system: SystemSettings) -> dict[str, object]:
    """``tot_charge`` is the electron-count decision's own charge
    (``ElectronCountDecision.tot_charge``), rendered verbatim and omitted
    when it is zero. QE's ``&SYSTEM`` takes a charge and has no ``nelec``
    keyword (ASE's ``ALL_KEYS['pw']['system']`` lists ``tot_charge``
    only, #34), so ``advisors/electron_count.py`` turns a requested
    electron count into the charge, on the cell rendered here. This
    writer never derives a charge from two electron counts: counting the
    uploaded cell while rendering an AFM supercell once turned the
    difference into ``tot_charge = 24`` (#128)."""
    tot_charge = system.electron_count.tot_charge
    if tot_charge == 0.0:
        return {}
    return {"tot_charge": tot_charge}


def electrons_keywords(step: PwSettings) -> dict[str, object]:
    decision = step.convergence
    keywords: dict[str, object] = {
        "conv_thr": decision.conv_thr,
        "mixing_beta": decision.mixing_beta,
        "electron_maxstep": decision.electron_maxstep,
        "mixing_mode": decision.mixing_mode,
    }
    if decision.mixing_fixed_ns is not None:
        keywords["mixing_fixed_ns"] = decision.mixing_fixed_ns
    return keywords


def cell_parameters(structure) -> str:
    lines = ["CELL_PARAMETERS angstrom"]
    lines.extend(
        "  " + "  ".join(format_float(value) for value in vector)
        for vector in structure.lattice.matrix
    )
    return "\n".join(lines) + "\n"


def atomic_species(
    species_labels: list[str],
    label_to_element: dict[str, str],
    pseudo_by_element: dict[str, object],
) -> str:
    """One line per QE species *label* (``Fe1``/``Fe2``/``O``), not per
    real element -- an element the cell splits into two species needs two
    ``ATOMIC_SPECIES`` entries, both pointing at the same
    pseudopotential file (mass/pseudopotential lookup still needs the real
    element underneath; ``Element("Fe1")`` isn't a real periodic-table
    symbol)."""
    lines = ["ATOMIC_SPECIES"]
    for label in species_labels:
        element = label_to_element[label]
        pseudo = pseudo_by_element[element]
        mass = format_float(float(Element(element).atomic_mass))
        lines.append(f"  {label}  {mass}  {pseudo.filename}")
    return "\n".join(lines) + "\n"


def atomic_positions(
    structure, fixed_site_indices: frozenset[int] | None = None
) -> str:
    """``fixed_site_indices`` (#44): 0-based indices, in ``structure``'s
    own site order, of atoms to pin with an ``if_pos`` column. Appended
    only to fixed atoms' rows, never to free atoms' -- matching ASE's
    own ``ase.io.espresso`` writer convention (confirmed by reading its
    source 2026-09-14: it omits the mask entirely for any atom with
    nothing fixed, relying on QE's per-row default of ``1 1 1`` rather
    than writing it out for every atom)."""
    fixed_site_indices = fixed_site_indices or frozenset()
    lines = ["ATOMIC_POSITIONS crystal"]
    for index, site in enumerate(structure):
        coords = "  ".join(format_float(value) for value in site.frac_coords)
        line = f"  {site.label}  {coords}"
        if index in fixed_site_indices:
            line += "  0  0  0"
        lines.append(line)
    return "\n".join(lines) + "\n"


def hubbard_lines(
    system: SystemSettings, label_to_element: dict[str, str]
) -> list[str]:
    """The HUBBARD card for ``system.hubbard.u_values``, shared by
    ``write_qe_scf``/``write_qe_relax``/``write_qe_bands``: one onsite
    ``U <label>-<manifold> <value>`` line per species label whose element
    has an entry, in label order, so each species of a split element
    (``Fe1``/``Fe2``) gets its element's value under the exact label
    ``ATOMIC_SPECIES`` uses. Returns ``[]`` when no species gets +U: QE
    stops on a HUBBARD card without a positive value
    (Modules/read_cards.f90 ``card_hubbard``).
    The header names ``system.hubbard.projectors``, the projector type the
    Hubbard advisor resolved: ``ortho-atomic``, which QE recommends
    (Doc/Hubbard_input.tex:141), unless the request asks for ``atomic``,
    the only type ph.x accepts (PHonon/PH/phq_readin.f90:766-767)."""
    entries = {entry.element: entry for entry in system.hubbard.u_values}
    lines = [
        f"  U  {label}-{entries[element].manifold}  "
        f"{format_float(entries[element].u_ev)}"
        for label, element in sorted(label_to_element.items())
        if element in entries
    ]
    if not lines:
        return []
    return ["\n".join([f"HUBBARD ({system.hubbard.projectors})", *lines]) + "\n"]


def k_points(step: PwSettings) -> str:
    grid = step.k_sampling.mesh
    shift = step.k_sampling.shift
    return (
        "K_POINTS automatic\n"
        f"  {grid[0]}  {grid[1]}  {grid[2]}  {shift[0]}  {shift[1]}  {shift[2]}\n"
    )


def format_float(value: float) -> str:
    """A card number to 10 significant digits; ``0`` below ``_CARD_ZERO``,
    so never ``-0``."""
    if abs(value) < _CARD_ZERO:
        return "0"
    return f"{value:.10g}"
