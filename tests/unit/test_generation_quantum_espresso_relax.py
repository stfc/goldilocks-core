from __future__ import annotations

import dataclasses

import numpy as np
import pytest
from support import (
    carbon_pair_in_a_box,
    graphene_monolayer,
    graphite,
    written_alpha_sulfur,
)

from goldilocks_core.advisors.boundary import BoundaryFacts
from goldilocks_core.advisors.convergence import ConvergenceDecision
from goldilocks_core.advisors.cutoffs import CutoffsDecision
from goldilocks_core.advisors.electron_count import ElectronCountDecision
from goldilocks_core.advisors.hubbard_u import HubbardU, HubbardUDecision
from goldilocks_core.advisors.k_sampling import KSamplingDecision
from goldilocks_core.advisors.magnetic_config import (
    MagneticConfigFacts,
    OrderingRecord,
)
from goldilocks_core.advisors.nbnd import NbndDecision
from goldilocks_core.advisors.occupations import OccupationsDecision
from goldilocks_core.advisors.parallelisation import ParallelisationDecision
from goldilocks_core.advisors.relax import RelaxOptions, VcRelaxOptions
from goldilocks_core.advisors.vdw_method import VdwFacts
from goldilocks_core.generation.errors import GenerationError
from goldilocks_core.generation.quantum_espresso.relax import write_qe_relax
from goldilocks_core.step_settings import PwSettings
from goldilocks_core.steps import ExitStatusCheck, SharedContext
from goldilocks_core.system_settings import SystemSettings

_CTX = SharedContext(prefix="pwscf", outdir="./out", pseudo_dir="./pseudo")
_UNSET = object()


def _system(
    structure,
    pseudo_metadata_factory,
    *,
    functional: str = "PBEsol",
    hubbard: HubbardUDecision | None = None,
    boundary: BoundaryFacts | None = None,
):
    elements = sorted({site.specie.symbol for site in structure})
    return SystemSettings(
        functional=functional,
        cutoffs=CutoffsDecision(ecutwfc_ry=30.0, ecutrho_ry=120.0),
        electron_count=ElectronCountDecision(
            nelec=4.0 * len(structure), tot_charge=0.0
        ),
        pseudopotentials=tuple(
            pseudo_metadata_factory(element, functional=functional, z_valence=4.0)
            for element in elements
        ),
        magnetic=MagneticConfigFacts(
            cell=structure,
            ordering=OrderingRecord(requested=None, applied=None),
            spin_polarized=False,
            magnetic_elements=(),
            starting_magnetization=None,
            compensated=False,
            tot_magnetization=None,
            spin_orbit_enabled=False,
            angle1=None,
            angle2=None,
        ),
        vdw=VdwFacts(use_vdw=False, method=None),
        hubbard=hubbard or HubbardUDecision(),
        boundary=boundary or BoundaryFacts(isolation="periodic"),
    )


def _step(
    *,
    relax,
    convergence: ConvergenceDecision | None = _UNSET,
    max_seconds: int | None = 574560,
) -> PwSettings:
    return PwSettings(
        occupations=OccupationsDecision(
            occupations="fixed", smearing_type=None, degauss=None
        ),
        k_sampling=KSamplingDecision(mesh=(3, 3, 3), shift=(0, 0, 0), k_distance=0.3),
        n_irr_k=4,
        nbnd=NbndDecision(nbnd=4),
        convergence=(
            ConvergenceDecision(
                conv_thr=1e-8,
                etot_conv_thr=4e-5,
                mixing_beta=0.4,
                electron_maxstep=80,
                mixing_mode="plain",
                mixing_fixed_ns=None,
            )
            if convergence is _UNSET
            else convergence
        ),
        parallel=ParallelisationDecision(npool=2, ndiag=None, kpoint_spin_pairs=4),
        max_seconds=max_seconds,
        relax=relax,
    )


def _line_with(content: str, needle: str) -> str:
    (line,) = (line for line in content.splitlines() if needle in line)
    return line


def test_writes_one_relax_step_with_an_ions_namelist_and_no_cell(
    silicon_structure, pseudo_metadata_factory
) -> None:
    system = _system(silicon_structure, pseudo_metadata_factory)
    step = _step(relax=RelaxOptions())

    steps = write_qe_relax(system, step, _CTX, "relax")

    assert len(steps) == 1
    rendered = steps[0]
    assert rendered.name == "relax"
    assert rendered.args == ("-npool", "2", "-in", "relax.in")
    assert rendered.stdout == "relax.out"
    content = rendered.files["relax.in"]
    assert "calculation      = 'relax'" in content
    assert "&IONS" in content
    assert "&CELL" not in content
    assert "ion_dynamics" in content
    assert "forc_conv_thr" in content
    assert "etot_conv_thr" in content
    assert "nstep" in content
    assert "trust_radius_max" in content
    assert "trust_radius_min" in content
    assert "trust_radius_ini" in content
    # shared with scf: same system/electrons/cards
    assert "ecutwfc          = 30.0" in content
    assert "ATOMIC_SPECIES" in content
    assert "CELL_PARAMETERS angstrom" in content
    assert "ATOMIC_POSITIONS crystal" in content
    assert "K_POINTS automatic" in content


@pytest.mark.parametrize(
    "purpose, relax", [("relax", RelaxOptions()), ("vc-relax", VcRelaxOptions())]
)
def test_relax_step_is_checked_by_the_status_pw_x_always_writes(
    diamond_silicon, pseudo_metadata_factory, purpose, relax
) -> None:
    """#129: a relax whose SCF does not converge, or that reaches
    max_seconds, records exit_status 2 or 255 only in the .save schema
    XML (punch('config')), not in <prefix>.xml."""
    system = _system(diamond_silicon, pseudo_metadata_factory)
    ctx = SharedContext(prefix="si", outdir="./scratch", pseudo_dir="./pseudo")

    (rendered,) = write_qe_relax(system, _step(relax=relax), ctx, purpose)

    assert rendered.completion == ExitStatusCheck(
        "./scratch/si.save/data-file-schema.xml"
    )
    assert "disk_io" not in rendered.files[f"{purpose}.in"]


def test_writes_vc_relax_step_with_ions_and_cell_namelists(
    silicon_structure, pseudo_metadata_factory
) -> None:
    system = _system(silicon_structure, pseudo_metadata_factory)
    step = _step(relax=VcRelaxOptions())

    steps = write_qe_relax(system, step, _CTX, "vc-relax")

    assert len(steps) == 1
    rendered = steps[0]
    assert rendered.name == "vc-relax"
    assert rendered.args == ("-npool", "2", "-in", "vc-relax.in")
    content = rendered.files["vc-relax.in"]
    assert "calculation      = 'vc-relax'" in content
    assert "&IONS" in content
    assert "&CELL" in content
    assert "cell_dynamics" in content
    assert "cell_dofree" in content
    assert "press" in content
    assert "press_conv_thr" in content
    assert "cell_factor" in content


def test_vc_relax_of_a_periodic_cell_writes_tstress(
    diamond_silicon, pseudo_metadata_factory
) -> None:
    system = _system(diamond_silicon, pseudo_metadata_factory)
    step = _step(relax=VcRelaxOptions())

    steps = write_qe_relax(system, step, _CTX, "vc-relax")

    assert "tstress          = .true." in steps[0].files["vc-relax.in"]


def test_relax_under_martyna_tuckerman_writes_no_tstress(
    pseudo_metadata_factory,
) -> None:
    """The relax writer passes the resolved boundary to the shared
    &CONTROL keywords, like write_qe_scf (#126)."""
    system = _system(
        carbon_pair_in_a_box(),
        pseudo_metadata_factory,
        boundary=BoundaryFacts(isolation="isolated"),
    )
    step = _step(relax=RelaxOptions())

    content = write_qe_relax(system, step, _CTX, "relax")[0].files["relax.in"]

    assert "assume_isolated  = 'martyna-tuckerman'" in content
    assert "tstress" not in content


def test_vc_relax_of_a_slab_boundary_writes_the_2d_truncation_and_tstress(
    pseudo_metadata_factory,
) -> None:
    """#161: under '2D' pw.x computes the in-plane stress a '2Dxy' vc-relax
    needs. The plain '2Dxy' is written beside ibrav = 0, the only ibrav
    ``CellDofree`` is valid for (#153)."""
    system = _system(
        graphene_monolayer(),
        pseudo_metadata_factory,
        boundary=BoundaryFacts(isolation="slab"),
    )
    step = _step(relax=VcRelaxOptions(cell_dofree="2Dxy"))

    content = write_qe_relax(system, step, _CTX, "vc-relax")[0].files["vc-relax.in"]

    assert "assume_isolated  = '2D'" in content
    assert "tstress          = .true." in content
    assert "   ibrav            = 0" in content.splitlines()
    assert "cell_dofree      = '2Dxy'" in content


def test_etot_conv_thr_matches_the_resolved_convergence_decision(
    silicon_structure, pseudo_metadata_factory
) -> None:
    system = _system(silicon_structure, pseudo_metadata_factory)
    relax = RelaxOptions(etot_conv_thr=4e-5)
    step = _step(relax=relax)

    content = write_qe_relax(system, step, _CTX, "relax")[0].files["relax.in"]

    assert "4e-05" in _line_with(content, "etot_conv_thr")


def test_trust_radius_omitted_when_ion_dynamics_is_not_bfgs(
    silicon_structure, pseudo_metadata_factory
) -> None:
    system = _system(silicon_structure, pseudo_metadata_factory)
    step = _step(relax=RelaxOptions(ion_dynamics="damp"))

    content = write_qe_relax(system, step, _CTX, "relax")[0].files["relax.in"]

    assert "ion_dynamics     = 'damp'" in content
    assert "trust_radius_max" not in content
    assert "trust_radius_min" not in content
    assert "trust_radius_ini" not in content


def test_remove_rigid_rot_true_is_rendered(
    silicon_structure, pseudo_metadata_factory
) -> None:
    system = _system(silicon_structure, pseudo_metadata_factory)
    step = _step(relax=RelaxOptions(remove_rigid_rot=True))

    content = write_qe_relax(system, step, _CTX, "relax")[0].files["relax.in"]

    assert ".true." in _line_with(content, "remove_rigid_rot")


def test_missing_relax_field_raises(silicon_structure, pseudo_metadata_factory) -> None:
    system = _system(silicon_structure, pseudo_metadata_factory)
    step = _step(relax=None)

    with pytest.raises(GenerationError, match="relax"):
        write_qe_relax(system, step, _CTX, "relax")


def test_vc_relax_purpose_with_plain_relax_options_raises(
    silicon_structure, pseudo_metadata_factory
) -> None:
    system = _system(silicon_structure, pseudo_metadata_factory)
    step = _step(relax=RelaxOptions())

    with pytest.raises(GenerationError, match="VcRelaxOptions"):
        write_qe_relax(system, step, _CTX, "vc-relax")


def test_relax_purpose_with_vc_relax_options_raises(
    silicon_structure, pseudo_metadata_factory
) -> None:
    system = _system(silicon_structure, pseudo_metadata_factory)
    step = _step(relax=VcRelaxOptions())

    with pytest.raises(GenerationError, match="RelaxOptions"):
        write_qe_relax(system, step, _CTX, "relax")


def test_missing_convergence_still_raises_same_as_scf(
    silicon_structure, pseudo_metadata_factory
) -> None:
    system = _system(silicon_structure, pseudo_metadata_factory)
    step = _step(relax=RelaxOptions(), convergence=None)

    with pytest.raises(GenerationError, match="convergence"):
        write_qe_relax(system, step, _CTX, "relax")


def test_max_seconds_comes_from_the_steps_own_settings(
    diamond_silicon, pseudo_metadata_factory
) -> None:
    """#169: the step renders PwSettings.max_seconds, its share of the
    task's walltime (all of 95% of it for a one-step relax task)."""
    system = _system(diamond_silicon, pseudo_metadata_factory)
    step = _step(relax=RelaxOptions(), max_seconds=13680)

    content = write_qe_relax(system, step, _CTX, "relax")[0].files["relax.in"]

    assert _line_with(content, "max_seconds") == "   max_seconds      = 13680"


def test_a_step_without_a_max_seconds_share_writes_none(
    diamond_silicon, pseudo_metadata_factory
) -> None:
    """#215: as in scf.in, a relaxation of a task that runs a job timer has
    no share (PwSettings.max_seconds None) and relax.in carries none."""
    system = _system(diamond_silicon, pseudo_metadata_factory)
    step = _step(relax=RelaxOptions(), max_seconds=None)

    content = write_qe_relax(system, step, _CTX, "relax")[0].files["relax.in"]

    assert "max_seconds" not in content
    assert _line_with(content, "calculation") == "   calculation      = 'relax'"


def test_relax_in_carries_the_grid_ph_x_accepts_and_two_body_d3(
    pseudo_metadata_factory,
) -> None:
    """relax-phonon's relaxation is the step ph.x reads (#215). Molecular
    alpha-S runs DFT-D3, and at 256 Ry pw.x's own grid, 144x128x96, is one
    ph.x refuses: relax.in writes 144x144x144, which pw.x keeps through the
    relaxation into the save, and two-body D3, as d3hess.x's Hessian."""
    system = dataclasses.replace(
        _system(written_alpha_sulfur(), pseudo_metadata_factory),
        cutoffs=CutoffsDecision(ecutwfc_ry=32.0, ecutrho_ry=256.0),
        vdw=VdwFacts(use_vdw=True, method="d3bj"),
    )
    step = dataclasses.replace(
        _step(relax=RelaxOptions(forc_conv_thr=1e-4), max_seconds=None),
        fft_grid=(144, 144, 144),
        dftd3_threebody=False,
    )

    content = write_qe_relax(system, step, _CTX, "relax")[0].files["relax.in"]

    assert [_line_with(content, f"nr{axis}") for axis in (1, 2, 3)] == [
        f"   nr{axis}              = 144" for axis in (1, 2, 3)
    ]
    assert _line_with(content, "dftd3_threebody") == "   dftd3_threebody  = .false."
    assert _line_with(content, "vdw_corr") == "   vdw_corr         = 'grimme-d3'"


def test_vc_relax_in_carries_two_body_d3_without_a_grid(
    pseudo_metadata_factory,
) -> None:
    """A vc-relax's final scf rebuilds pw.x's own grid for the relaxed cell,
    so vc-relax-phonon writes none, but its D3 is the two-body one (#215)."""
    system = dataclasses.replace(
        _system(graphite(), pseudo_metadata_factory),
        vdw=VdwFacts(use_vdw=True, method="d3bj"),
    )
    step = dataclasses.replace(
        _step(relax=VcRelaxOptions(forc_conv_thr=1e-4), max_seconds=None),
        dftd3_threebody=False,
    )

    content = write_qe_relax(system, step, _CTX, "vc-relax")[0].files["vc-relax.in"]

    assert _line_with(content, "dftd3_threebody") == "   dftd3_threebody  = .false."
    assert "nr1" not in content


def _silicon_slab():
    """A real, multi-layer 2D slab -- unlike ``silicon_structure`` (a
    single-atom bulk placeholder unsuited to layer detection). Built
    the same way #44's own design sketch expects any slab reaching this
    codebase to have been built (``pymatgen``'s ``SlabGenerator``)."""
    from pymatgen.core import Lattice, Structure
    from pymatgen.core.surface import SlabGenerator

    bulk = Structure.from_spacegroup("Fd-3m", Lattice.cubic(5.43), ["Si"], [[0, 0, 0]])
    return SlabGenerator(
        bulk, (0, 0, 1), min_slab_size=10, min_vacuum_size=12, center_slab=True
    ).get_slab()


def _atomic_positions_block(content: str) -> list[str]:
    lines = content.splitlines()
    start = next(
        i for i, line in enumerate(lines) if line.startswith("ATOMIC_POSITIONS")
    )
    end = next(i for i in range(start + 1, len(lines)) if not lines[i].strip())
    return lines[start + 1 : end]


def test_fix_bottom_layers_none_writes_no_if_pos_columns(
    pseudo_metadata_factory,
) -> None:
    slab = _silicon_slab()
    system = _system(slab, pseudo_metadata_factory)
    step = _step(relax=RelaxOptions(fix_bottom_layers=None))

    content = write_qe_relax(system, step, _CTX, "relax")[0].files["relax.in"]

    rows = _atomic_positions_block(content)
    assert len(rows) == len(slab)
    assert not any(row.split()[-3:] == ["0", "0", "0"] for row in rows)


def test_fix_bottom_layers_fixes_exactly_the_lowest_atoms(
    pseudo_metadata_factory,
) -> None:
    slab = _silicon_slab()
    system = _system(slab, pseudo_metadata_factory)
    step = _step(relax=RelaxOptions(fix_bottom_layers=2))

    content = write_qe_relax(system, step, _CTX, "relax")[0].files["relax.in"]

    rows = _atomic_positions_block(content)
    assert len(rows) == len(slab)
    fixed_indices = {
        i for i, row in enumerate(rows) if row.split()[-3:] == ["0", "0", "0"]
    }
    free_indices = set(range(len(rows))) - fixed_indices
    assert fixed_indices, "expected at least one fixed atom"

    # Independent oracle: every fixed atom's cartesian z must be no
    # higher than every free atom's -- "bottom" layers really are the
    # ones with the lowest coordinate along the slab's vacuum direction,
    # not an artifact of whatever index order the detection happened to
    # produce.
    z = slab.cart_coords[:, 2]
    assert max(z[i] for i in fixed_indices) < min(z[i] for i in free_indices)


def test_fix_bottom_layers_finds_the_layers_of_an_ionic_slab(
    pseudo_metadata_factory,
) -> None:
    """NaCl(001): each atomic layer holds both Na and Cl, and the bottom one
    is every atom at the lowest z. The layers follow the vacuum, not bonds,
    which JmolNN alone misses here (Na-Cl 2.82 A, cutoff 2.41 A, #125)."""
    from pymatgen.core import Lattice, Structure
    from pymatgen.core.surface import SlabGenerator

    bulk = Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(5.64), ["Na", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]]
    )
    slab = SlabGenerator(
        bulk, (0, 0, 1), min_slab_size=10, min_vacuum_size=12, center_slab=True
    ).get_slab()
    system = _system(slab, pseudo_metadata_factory)
    step = _step(relax=RelaxOptions(fix_bottom_layers=1))

    content = write_qe_relax(system, step, _CTX, "relax")[0].files["relax.in"]

    rows = _atomic_positions_block(content)
    fixed_indices = {
        i for i, row in enumerate(rows) if row.split()[-3:] == ["0", "0", "0"]
    }
    z = slab.cart_coords[:, 2]
    assert fixed_indices == {i for i in range(len(slab)) if z[i] < z.min() + 0.1}


def test_fix_bottom_layers_counts_up_from_the_vacuum_across_the_cell_boundary(
    pseudo_metadata_factory,
) -> None:
    """#160: shifted by half a cell, the Si(001) slab straddles z = 0, so
    layers counted from fractional 0 start inside it. Counted up from the
    upper edge of the vacuum, they are the slab's own: the writer fixes the
    same atoms as in the centred slab, its two lowest."""
    from pymatgen.core import Structure

    slab = _silicon_slab()
    shifted = Structure(
        slab.lattice,
        slab.species,
        np.mod(slab.frac_coords + np.array([0, 0, 0.5]), 1.0),
    )
    system = _system(shifted, pseudo_metadata_factory)
    step = _step(relax=RelaxOptions(fix_bottom_layers=2))

    content = write_qe_relax(system, step, _CTX, "relax")[0].files["relax.in"]

    rows = _atomic_positions_block(content)
    fixed_indices = {
        i for i, row in enumerate(rows) if row.split()[-3:] == ["0", "0", "0"]
    }
    z = slab.cart_coords[:, 2]
    assert fixed_indices == {int(i) for i in np.argsort(z)[:2]}


def test_fix_bottom_layers_exceeding_detected_layers_raises(
    pseudo_metadata_factory,
) -> None:
    slab = _silicon_slab()
    system = _system(slab, pseudo_metadata_factory)
    step = _step(relax=RelaxOptions(fix_bottom_layers=999))

    with pytest.raises(GenerationError, match="fix_bottom_layers=999"):
        write_qe_relax(system, step, _CTX, "relax")


def test_fix_bottom_layers_on_a_bulk_structure_raises(
    diamond_silicon, pseudo_metadata_factory
) -> None:
    """``checks.check_all`` rejects this before generation in the real
    pipeline; called directly, the writer fails loudly rather than fixing
    atoms of a cell with no bottom."""
    system = _system(diamond_silicon, pseudo_metadata_factory)
    step = _step(relax=RelaxOptions(fix_bottom_layers=1))

    with pytest.raises(
        GenerationError, match="exactly one lattice vector, but this cell has no vacuum"
    ):
        write_qe_relax(system, step, _CTX, "relax")


def test_u_values_render_the_qe_hubbard_card(
    silicon_structure, pseudo_metadata_factory
) -> None:
    """Same HUBBARD-card rendering as write_qe_scf (#88), reused rather
    than reimplemented -- see scf.py's hubbard_lines docstring for why
    this is species-label-keyed, not atom-index-keyed."""
    system = _system(
        silicon_structure,
        pseudo_metadata_factory,
        hubbard=HubbardUDecision(
            u_values=(HubbardU("Si", "3p", 3.0, "human"),), projectors="ortho-atomic"
        ),
    )
    step = _step(relax=RelaxOptions())

    content = write_qe_relax(system, step, _CTX, "relax")[0].files["relax.in"]

    assert "HUBBARD (ortho-atomic)\n  U  Si-3p  3\n" in content


def test_no_u_values_render_no_hubbard_card(
    silicon_structure, pseudo_metadata_factory
) -> None:
    """#135: no U value means plain DFT -- no card, and no raise."""
    system = _system(silicon_structure, pseudo_metadata_factory)
    step = _step(relax=VcRelaxOptions())

    content = write_qe_relax(system, step, _CTX, "vc-relax")[0].files["vc-relax.in"]

    assert "HUBBARD" not in content
