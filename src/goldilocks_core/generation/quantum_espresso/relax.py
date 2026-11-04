"""write_qe_relax: render one ``pw.x`` relax/vc-relax ``Step`` from
resolved settings.

New in v2 (v2 epic 10, #10). ``write_qe_scf`` (v2 epic 7, #7) never
rendered a relax/vc-relax input at all -- its own docstring explicitly
earmarked "whichever future ``generation/quantum_espresso/relax.py``"
for that job. This module is that writer, sharing every
purpose-agnostic card/namelist helper with ``scf.py`` (un-privatized
there for this reuse: ``control_keywords``/``system_keywords``/
``electrons_keywords``/``atomic_species``/``cell_parameters``/
``atomic_positions``/``k_points``/``validated_pseudo_by_element``/
``hubbard_lines``/``pw_exit_status_check``) --
the &CONTROL/&SYSTEM/&ELECTRONS namelists and every card are identical
between an scf step and a relax step; only &IONS/&CELL (this module's
own ``ions_keywords``/``cell_keywords``) and the ``&CONTROL``
relaxation-stopping keywords (``forc_conv_thr``/``etot_conv_thr``/
``nstep``, added to ``scf.py``'s own ``control_keywords`` since they
are real ``&CONTROL`` keys per ``INPUT_PW.txt``/ASE's own
``ALL_KEYS['pw']['control']`` registry, confirmed 2026-09-14 -- not an
``&IONS`` key as the design doc's own directory sketch might suggest)
are new.

``system_keywords`` also writes the phonon tasks' nr1-nr3 and
``dftd3_threebody`` (``PwSettings.dfpt_system_keywords``, #215). A
fixed-cell relaxation keeps nr1-nr3 through every ionic step and stores
them in the save ph.x reads (QE 7.3 ``PW/src/pw_restart_new.f90:398-400``);
a vc-relax's final scf drops them and rebuilds pw.x's own grid for the
relaxed cell (``PW/src/run_pwscf.f90:404-405``), so vc-relax.in is given
none.

``render_namelist`` sections a flat keyword dict automatically (ASE's
``Namelist.to_nested``, keyed against ``ALL_KEYS['pw']``) -- this writer
does not need to know or assert which QE namelist a keyword belongs to,
only which *keywords* apply, matching every other writer in this
package.

**``if_pos`` slab-layer fixing (#44).** When ``relax.fix_bottom_layers``
is set, this module freezes every atom of the slab's bottom N atomic
layers, passing their indices to ``atomic_positions``. The layers are
``analysis.geometry.slab_layers`` of ``system.magnetic.cell`` (the
simulated cell) -- the exact structure ``atomic_positions`` iterates,
whose site count and order AFM species-splitting can change
(``advisors/relax.py``'s own docstring). They run along the slab's one
vacuum axis, whichever lattice vector that is, up from the upper edge of
the vacuum, so a slab that straddles the cell boundary still has its
bottom layer first (#160).
``checks.py``'s ``_fix_bottom_layers_requires_slab`` evaluates the same
function on the same cell, so a request that passed ``check()`` always
applies here.
"""

from __future__ import annotations

from typing import Literal

from pymatgen.core import Structure

from goldilocks_core.advisors.relax import RelaxOptions, VcRelaxOptions
from goldilocks_core.analysis.geometry import slab_layers, vacuum_axes
from goldilocks_core.generation.errors import GenerationError
from goldilocks_core.generation.quantum_espresso.namelists import render_namelist
from goldilocks_core.generation.quantum_espresso.scf import (
    atomic_positions,
    atomic_species,
    cell_parameters,
    control_keywords,
    electrons_keywords,
    hubbard_lines,
    k_points,
    pw_exit_status_check,
    system_keywords,
    validated_pseudo_by_element,
)
from goldilocks_core.step_settings import PwSettings
from goldilocks_core.steps import SharedContext, Step
from goldilocks_core.system_settings import SystemSettings


def write_qe_relax(
    system: SystemSettings,
    step: PwSettings,
    ctx: SharedContext,
    purpose: Literal["relax", "vc-relax"],
) -> list[Step]:
    """``purpose`` selects both QE's own ``&CONTROL calculation`` value
    and which of ``RelaxOptions``/``VcRelaxOptions`` ``step.relax`` must
    be -- the two must agree, checked below, since ``PwSettings.relax``'s
    own type (``RelaxOptions | VcRelaxOptions | None``) cannot enforce
    that by itself.
    """
    structure = system.magnetic.cell
    relax = step.relax
    if relax is None:
        raise GenerationError(
            f"PwSettings.relax is required to generate a {purpose}.in input"
        )
    is_vc_relax = isinstance(relax, VcRelaxOptions)
    if purpose == "vc-relax" and not is_vc_relax:
        raise GenerationError(
            "write_qe_relax needs a VcRelaxOptions for purpose='vc-relax', "
            f"got {type(relax).__name__}"
        )
    if purpose == "relax" and is_vc_relax:
        raise GenerationError(
            "write_qe_relax needs a plain RelaxOptions for purpose='relax'; "
            "got a VcRelaxOptions -- use purpose='vc-relax' instead"
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
    keywords.update(ions_keywords(relax))
    if isinstance(relax, VcRelaxOptions):
        keywords.update(cell_keywords(relax))

    lines = [render_namelist(keywords)]
    lines.append(atomic_species(species_labels, label_to_element, pseudo_by_element))
    lines.append(cell_parameters(structure))
    lines.append(atomic_positions(structure, _fixed_site_indices(structure, relax)))
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


def ions_keywords(relax: RelaxOptions) -> dict[str, object]:
    """``trust_radius_max/min/ini`` are only meaningful for
    ``ion_dynamics='bfgs'`` (INPUT_PW.txt marks all three "(bfgs
    only)") -- omitted rather than writing a value QE would just ignore
    for ``damp``/``fire``, matching this codebase's existing convention
    of only writing a keyword when it applies given an already-resolved
    fact (e.g. ``scf.py``'s own ``_occupations_keywords``)."""
    keywords: dict[str, object] = {
        "ion_dynamics": relax.ion_dynamics,
        "remove_rigid_rot": relax.remove_rigid_rot,
    }
    if relax.ion_dynamics == "bfgs":
        keywords["trust_radius_max"] = relax.trust_radius_max
        keywords["trust_radius_min"] = relax.trust_radius_min
        keywords["trust_radius_ini"] = relax.trust_radius_ini
    return keywords


def cell_keywords(relax: VcRelaxOptions) -> dict[str, object]:
    return {
        "cell_dynamics": relax.cell_dynamics,
        "cell_dofree": relax.cell_dofree,
        "press": relax.press,
        "press_conv_thr": relax.press_conv_thr,
        "cell_factor": relax.cell_factor,
    }


def _fixed_site_indices(
    structure: Structure, relax: RelaxOptions
) -> frozenset[int] | None:
    if relax.fix_bottom_layers is None:
        return None
    return _bottom_layer_site_indices(structure, relax.fix_bottom_layers)


def _bottom_layer_site_indices(structure: Structure, count: int) -> frozenset[int]:
    """0-based indices (``structure``'s own site order) of every atom in the
    bottom ``count`` atomic layers of ``analysis.geometry.slab_layers``."""
    layers = slab_layers(structure)
    if layers is None:
        axes = vacuum_axes(structure)
        found = f"vacuum along {', '.join(axes)}" if axes else "no vacuum"
        if len(axes) == 1:
            found = f"more than one vacuum gap along {axes[0]}"
        raise GenerationError(
            "relax.fix_bottom_layers counts a slab's atomic layers up from its "
            "vacuum, so the cell needs one vacuum gap, along exactly one lattice "
            f"vector, but this cell has {found}"
        )
    if count > len(layers):
        raise GenerationError(
            f"relax.fix_bottom_layers={count} exceeds the {len(layers)} "
            "distinct atomic layers detected in this structure"
        )
    return frozenset(index for layer in layers[:count] for index in layer)
