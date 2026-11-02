"""write_qe_bands and write_qe_bands_x: the band task's ``pw.x`` bands input
and its ``bands.x`` inputs (#118).

**bands.in.** A bands run reads the cell and the positions from the scf's
save and recomputes the potential from its charge density (QE 7.3
``PW/src/input.f90:816-823``, ``:1632-1645``, ``potinit.f90:86-118``), but
takes its species and every keyword that defines the Hamiltonian from its own
input. So ``write_qe_bands`` renders it from the same ``SystemSettings`` as
``scf.in``, through ``scf.py``'s namelist and card helpers, as ``relax.py``
does. The step's own values are ``calculation = 'bands'``, which runs no SCF
loop and computes no forces (``input.f90:469-473``), ``nbnd``, ``conv_thr``,
which sets the diagonalization threshold (``setup.f90:374``),
``max_seconds``, the occupations the step is given, and the path. Nothing is
added: ``diago_full_acc`` acts only where an SCF run relaxes the threshold of
empty bands (``sum_band.f90:105-113``), so a bands run converges every band;
``startingpot`` is forced to 'file' (``input.f90:860-864``); pw.x runs a
bands k-point list as given, unreduced by symmetry (``setup.f90:579-585``),
so it needs no ``nosym``; and the default ``disk_io`` writes the
wavefunctions bands.x reads.

**The path card** (``k_points_crystal_b``). ``K_POINTS crystal_b``
(``Modules/read_cards.f90:719-838``) takes the number of vertices, then one
row per vertex: its crystal coordinates in the reciprocal vectors of the
written cell and the number of equal steps to the next vertex -- 0 at the end
of a branch another follows, where pw.x goes straight to the next vertex, and
1 at the last vertex, whose number pw.x reads but does not use
(``Modules/generate_k_along_lines.f90``). pw.x then runs
``KPathDecision.n_kpoints`` points per spin channel
(``read_cards.f90:824-827``). Each label follows its row as a ``!`` comment:
a row starting with a letter is read as a symbolic point, which needs an
``ibrav`` other than 0 (``read_cards.f90:790-818``). Coordinates follow the
card rule of ``scf.format_float`` (#178). matdyn.x reads the rows of
``path_rows`` the same way with ``q_in_band_form`` and ``q_in_cryst_coord``.

**bands.x** (``write_qe_bands_x``) writes one spin channel per run: a
collinear run's two channels (``spin_component`` 1 and 2) run one after the
other, since both rewrite ``prefix.wfc*``, each with its own ``filband``;
otherwise it runs once, a noncollinear run accepting only ``spin_component``
1 (``PP/src/bands.f90:119-120``). ``filband`` is always given: the default,
``bands.out``, opened and rewound (``bands.f90:54``, ``:193-195``), would
overwrite the pw.x bands step's stdout. ``lsym`` is off: its group theory,
run after ``filband`` is written (``bands.f90:127-128``), can stop bands.x
(``find_group``, ``divide_class``). Without it ``no_overlap`` keeps its
default, so the bands are sorted by energy as ``lsym`` would force
(``bands.f90:56``, ``:102``), and only ``filband.rap`` is not written. Like
dos.x (``dos.py``), bands.x runs on one MPI task, since a rank that owns no
FFT plane aborts, and writes no status file, so ``JOB DONE`` in its stdout
passes the step; ``errore`` exits non-zero.
"""

from __future__ import annotations

from goldilocks_core.advisors.k_path import KPathDecision
from goldilocks_core.advisors.magnetic_config import SpinMode
from goldilocks_core.generation.errors import GenerationError
from goldilocks_core.generation.quantum_espresso.namelists import render_namelist
from goldilocks_core.generation.quantum_espresso.scf import (
    atomic_positions,
    atomic_species,
    cell_parameters,
    control_keywords,
    electrons_keywords,
    format_float,
    hubbard_lines,
    pw_exit_status_check,
    system_keywords,
    validated_pseudo_by_element,
)
from goldilocks_core.step_settings import PwSettings
from goldilocks_core.steps import SharedContext, StdoutMarkerCheck, Step
from goldilocks_core.system_settings import SystemSettings


def write_qe_bands(
    system: SystemSettings, step: PwSettings, ctx: SharedContext
) -> list[Step]:
    """The bands step: ``pw.x`` on ``bands.in`` along ``step.k_path``, checked
    by the status file every ``pw.x`` step writes (module docstring)."""
    structure = system.magnetic.cell
    for name, value in (
        ("occupations", step.occupations),
        ("k_path", step.k_path),
        ("nbnd", step.nbnd),
        ("convergence", step.convergence),
        ("parallel", step.parallel),
        ("max_seconds", step.max_seconds),
    ):
        if value is None:
            raise GenerationError(f"PwSettings.{name} is required to generate bands.in")
    elements = sorted({site.specie.symbol for site in structure})
    pseudo_by_element = validated_pseudo_by_element(elements, system)
    species_labels = sorted({site.label for site in structure})
    label_to_element = {site.label: site.specie.symbol for site in structure}
    species_index = {label: index + 1 for index, label in enumerate(species_labels)}

    keywords: dict[str, object] = {}
    keywords.update(control_keywords(ctx, system.boundary, step, "bands"))
    keywords.update(
        system_keywords(structure, system, step, len(species_labels), species_index)
    )
    keywords.update(electrons_keywords(step))

    lines = [render_namelist(keywords)]
    lines.append(atomic_species(species_labels, label_to_element, pseudo_by_element))
    lines.append(cell_parameters(structure))
    lines.append(atomic_positions(structure))
    lines.append(k_points_crystal_b(step.k_path))
    lines.extend(hubbard_lines(system, label_to_element))

    args = ["-npool", str(step.parallel.npool)]
    if step.parallel.ndiag is not None:
        args += ["-ndiag", str(step.parallel.ndiag)]
    args += ["-in", "bands.in"]

    return [
        Step(
            name="bands",
            executable="pw.x",
            args=tuple(args),
            files={"bands.in": "\n".join(lines)},
            stdout="bands.out",
            completion=pw_exit_status_check(ctx),
        )
    ]


def k_points_crystal_b(path: KPathDecision) -> str:
    """``path`` as a ``K_POINTS crystal_b`` card (module docstring)."""
    return "\n".join(["K_POINTS crystal_b", *path_rows(path)]) + "\n"


def path_rows(path: KPathDecision) -> list[str]:
    """The number of vertices of ``path``, then one ``k1 k2 k3 n ! label``
    row per vertex: n is the steps to the next vertex, 0 at the end of a
    branch another follows and 1 at the last vertex."""
    rows = [f"  {sum(len(branch.vertices) for branch in path.branches)}"]
    for index, branch in enumerate(path.branches):
        last = 1 if index == len(path.branches) - 1 else 0
        for vertex, steps in zip(branch.vertices, (*branch.steps, last), strict=True):
            k = "  ".join(format_float(value) for value in vertex.k)
            rows.append(f"  {k}  {steps}  ! {vertex.label}")
    return rows


def write_qe_bands_x(spin_mode: SpinMode, ctx: SharedContext) -> list[Step]:
    """One ``bands.x`` step per spin channel of a run in ``spin_mode``:
    ``bands_x_up`` and ``bands_x_down`` for a collinear run, otherwise
    ``bands_x`` (module docstring)."""
    if spin_mode == "collinear":
        return [
            _bands_x("bands_x_up", "bands_up.dat", 1, ctx),
            _bands_x("bands_x_down", "bands_down.dat", 2, ctx),
        ]
    return [_bands_x("bands_x", "bands.dat", None, ctx)]


def _bands_x(
    name: str, filband: str, spin_component: int | None, ctx: SharedContext
) -> Step:
    """The ``bands.x`` step ``name``, writing the bands of ``spin_component``
    (bands.x's default, 1, when ``None``) to ``filband``."""
    keywords: dict[str, object] = {
        "prefix": ctx.prefix,
        "outdir": ctx.outdir,
        "filband": filband,
        "lsym": False,
    }
    if spin_component is not None:
        keywords["spin_component"] = spin_component
    return Step(
        name=name,
        executable="bands.x",
        args=("-in", f"{name}.in"),
        files={f"{name}.in": render_namelist(keywords, binary="bands")},
        stdout=f"{name}.out",
        completion=StdoutMarkerCheck(),
        ntasks=1,
    )
