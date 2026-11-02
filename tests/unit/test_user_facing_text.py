"""User-facing text names settings and their values, not the code (#151).

Every warning ``/capabilities`` publishes and every finding the gate returns
reaches a user verbatim: the Workbench shows it, the CLI prints it and the
MCP tools tell an agent to relay it. None may carry what
``support.INTERNAL_TEXT`` lists: a module path, the package name, a
``repr()`` artefact, an internal literal or a design-document id. Quantum
ESPRESSO literals such as ``'too few bands'`` stay quoted.
"""

from __future__ import annotations

import dataclasses

import pytest
from pymatgen.core import Lattice, Structure
from support import (
    INTERNAL_TEXT,
    alpha_uranium,
    carbon_pair_in_a_box,
    framed_magnetic_cell,
    geometry_facts,
    graphene_monolayer,
    graphite,
    mc3d_42058_silicon,
    molybdenum_disulfide_monolayer,
    rhombohedral_bismuth_selenide,
    rutile_titanium_dioxide,
    written_cell,
)

from goldilocks_core.advisors.boundary import BoundaryFacts, boundary
from goldilocks_core.advisors.cutoffs import CutoffsDecision
from goldilocks_core.advisors.electron_count import ElectronCountDecision
from goldilocks_core.advisors.fft_grid import fft_grid
from goldilocks_core.advisors.hubbard_u import HubbardU, HubbardUDecision
from goldilocks_core.advisors.job_resources import JobDecision
from goldilocks_core.advisors.nbnd import NbndDecision
from goldilocks_core.advisors.occupations import OccupationsDecision
from goldilocks_core.advisors.parallelisation import ParallelisationDecision
from goldilocks_core.advisors.q_sampling import QSamplingHumanInput, q_sampling
from goldilocks_core.advisors.relax import RelaxOptions, VcRelaxOptions
from goldilocks_core.advisors.vdw_method import VdwFacts
from goldilocks_core.advisors.warning_catalogue import WARNING_CATALOGUE
from goldilocks_core.checks import (
    FINDING_CATALOGUE,
    CheckReport,
    check_all,
    with_phonon_findings,
)
from goldilocks_core.pw_symmetry import pw_frame
from goldilocks_core.resolution import Blocked, Provenance, Resolved, Warning
from goldilocks_core.service import OVERRIDES_WARNING_CATALOGUE


def _internal(text: str) -> list[str]:
    return INTERNAL_TEXT.findall(text)


def _resolved(value: object, source: str = "human") -> Resolved[object]:
    return Resolved(value, Provenance(source=source))


def _fixed(tot_magnetization: float | None = None) -> Resolved[object]:
    return _resolved(
        OccupationsDecision(
            occupations="fixed",
            smearing_type=None,
            degauss=None,
            tot_magnetization=tot_magnetization,
        )
    )


def _spin_polarized(structure: Structure) -> Resolved[object]:
    facts = dataclasses.replace(
        written_cell(structure).value,
        spin_polarized=True,
        magnetic_elements=("Fe",),
        starting_magnetization={"Fe": 0.1},
    )
    return _resolved(facts, "heuristic")


def _electrons(nelec: float) -> Resolved[object]:
    return _resolved(ElectronCountDecision(nelec=nelec, tot_charge=0.0), "heuristic")


def _job() -> Resolved[object]:
    return _resolved(
        JobDecision(
            partition="scarf",
            nodes=1,
            ntasks=64,
            ntasks_per_node=64,
            walltime_h=168.0,
            max_seconds_by_step={"scf": 574560},
            memory_per_process_mb=12.5,
            memory_total_mb=900.0,
            account=None,
        ),
        "heuristic",
    )


def _layout(npool: int, ndiag: int | None = None) -> Resolved[object]:
    return _resolved(
        ParallelisationDecision(npool=npool, ndiag=ndiag, kpoint_spin_pairs=64)
    )


def _framed(structure: Structure) -> Resolved[object]:
    framed, frame = pw_frame(structure)
    facts = dataclasses.replace(written_cell(framed).value, frame=frame)
    return _resolved(facts, "heuristic")


def _spin_orbit(structure: Structure) -> Resolved[object]:
    facts = dataclasses.replace(written_cell(structure).value, spin_orbit_enabled=True)
    return _resolved(facts, "heuristic")


def _smearing(tot_magnetization: float | None) -> Resolved[object]:
    return _resolved(
        OccupationsDecision(
            occupations="smearing",
            smearing_type="cold",
            degauss=0.01,
            tot_magnetization=tot_magnetization,
        )
    )


def _hubbard(projectors: str) -> Resolved[object]:
    return _resolved(
        HubbardUDecision(
            u_values=(HubbardU("Ni", "3d", 6.2, "table"),), projectors=projectors
        ),
        "heuristic",
    )


def _alpha_uranium_q_grid(q_grid: tuple[int, int, int]):
    return q_sampling(
        framed_magnetic_cell(alpha_uranium()), QSamplingHumanInput(q_grid=q_grid)
    )


def _alpha_uranium_fft_grid():
    cutoffs = _resolved(CutoffsDecision(ecutwfc_ry=60.0, ecutrho_ry=480.0))
    return fft_grid(framed_magnetic_cell(alpha_uranium()), cutoffs, "vc-relax")


def _phonon(purpose: str = "scf", **states: object) -> CheckReport:
    """The phonon tasks' findings for ``states`` alone."""
    return with_phonon_findings(CheckReport(), purpose=purpose, **states)


_IRON = Structure(Lattice.cubic(2.87), ["Fe", "Fe"], [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]])
_PURPOSE_SCF = {"purpose": "scf"}
_VC_RELAX = {"purpose": "vc-relax"}
_BANDS = {"purpose": "bands"}

_TRIGGERS = {
    "advice.blocked": lambda: check_all(
        Blocked(by=Blocked(by="pseudopotential table sssp is not installed"))
    ),
    "occupations.fixed_needs_tot_magnetization": lambda: check_all(
        occupations=_fixed(), magnetic=_spin_polarized(_IRON), **_PURPOSE_SCF
    ),
    "occupations.fixed_needs_integer_tot_magnetization": lambda: check_all(
        occupations=_fixed(2.5), magnetic=_spin_polarized(_IRON), **_PURPOSE_SCF
    ),
    "occupations.fixed_tot_magnetization_parity": lambda: check_all(
        occupations=_fixed(2.0),
        magnetic=_spin_polarized(_IRON),
        electron_count=_electrons(3.0),
        **_PURPOSE_SCF,
    ),
    "occupations.fixed_needs_even_electron_count": lambda: check_all(
        occupations=_fixed(),
        magnetic=written_cell(_IRON),
        electron_count=_electrons(3.0),
        **_PURPOSE_SCF,
    ),
    "nbnd.too_few_bands": lambda: check_all(
        occupations=_fixed(),
        magnetic=written_cell(_IRON),
        electron_count=_electrons(8.0),
        nbnd=_resolved(NbndDecision(nbnd=2)),
        **_BANDS,
    ),
    "occupations.bands_x_refuses_tot_magnetization": lambda: check_all(
        occupations=_fixed(2.0), magnetic=_spin_polarized(_IRON), **_BANDS
    ),
    "k_path.too_many_kpoints": lambda: check_all(
        parallel=_resolved(
            ParallelisationDecision(npool=1, ndiag=None, kpoint_spin_pairs=40001)
        ),
        **_BANDS,
    ),
    "relax.vc_relax_needs_bfgs": lambda: check_all(
        relax=_resolved(VcRelaxOptions(ion_dynamics="damp")), **_VC_RELAX
    ),
    "boundary.isolated_needs_vacuum": lambda: check_all(
        boundary=_resolved(BoundaryFacts("isolated")),
        magnetic=written_cell(graphite()),
    ),
    "boundary.slab_unsuited_to_2d_truncation": lambda: check_all(
        boundary=_resolved(BoundaryFacts("slab")), magnetic=written_cell(graphite())
    ),
    "boundary.isolated_forbids_vc_relax": lambda: check_all(
        boundary=_resolved(BoundaryFacts("isolated")), **_VC_RELAX
    ),
    "relax.slab_vc_relax_needs_2d_cell_dofree": lambda: check_all(
        boundary=_resolved(BoundaryFacts("slab")),
        relax=_resolved(VcRelaxOptions(cell_dofree="all")),
        magnetic=written_cell(graphene_monolayer()),
        **_VC_RELAX,
    ),
    "relax.two_d_cell_dofree_needs_xy_frame": lambda: check_all(
        relax=_resolved(VcRelaxOptions(cell_dofree="2Dxy")),
        magnetic=written_cell(rhombohedral_bismuth_selenide()),
        **_VC_RELAX,
    ),
    "relax.cartesian_cell_dofree_on_rotated_cell": lambda: check_all(
        relax=_resolved(VcRelaxOptions(cell_dofree="z")),
        magnetic=_framed(mc3d_42058_silicon()),
        **_VC_RELAX,
    ),
    "vdw.use_vdw_without_d3bj_parameters": lambda: check_all(
        vdw=_resolved(VdwFacts(use_vdw=True, method="d3bj")),
        functional=_resolved("LDA"),
    ),
    "relax.fix_bottom_layers_needs_slab": lambda: check_all(
        relax=_resolved(RelaxOptions(fix_bottom_layers=1)),
        magnetic=written_cell(graphite()),
    ),
    "relax.fix_bottom_layers_exceeds_layers": lambda: check_all(
        relax=_resolved(RelaxOptions(fix_bottom_layers=4)),
        magnetic=written_cell(molybdenum_disulfide_monolayer()),
    ),
    "parallelisation.npool_does_not_divide_ntasks": lambda: check_all(
        job=_job(), parallel=_layout(7)
    ),
    "parallelisation.ndiag_grid_too_large": lambda: check_all(
        job=_job(), parallel=_layout(4, 16), nbnd=_resolved(NbndDecision(nbnd=8))
    ),
    "phonon.hubbard_projectors_unsupported": lambda: _phonon(
        hubbard=_hubbard("ortho-atomic")
    ),
    "phonon.noncollinear_hubbard_unsupported": lambda: _phonon(
        hubbard=_hubbard("atomic"), magnetic=_spin_orbit(_IRON)
    ),
    "phonon.isolated_boundary_unsupported": lambda: _phonon(
        boundary=_resolved(BoundaryFacts("isolated")),
        magnetic=written_cell(carbon_pair_in_a_box()),
    ),
    "phonon.pinned_moment_with_smearing": lambda: _phonon(
        occupations=_smearing(2.0),
        magnetic=_spin_polarized(_IRON),
        electron_count=_electrons(16.0),
    ),
    "phonon.q_grid_breaks_symmetry": lambda: _phonon(
        q_sampling=_alpha_uranium_q_grid((4, 8, 4))
    ),
    "phonon.too_many_q_points": lambda: _phonon(
        q_sampling=_alpha_uranium_q_grid((36, 36, 36))
    ),
    "phonon.vc_relax_fft_grid_unsupported": lambda: _phonon(
        "vc-relax", fft_grid=_alpha_uranium_fft_grid()
    ),
    "phonon.fix_bottom_layers_unsupported": lambda: _phonon(
        "relax", relax=_resolved(RelaxOptions(fix_bottom_layers=1))
    ),
    "phonon.metallicity_unconfirmed": lambda: _phonon(
        occupations=_smearing(None),
        is_metal=_resolved("metal", "ml"),
        magnetic=written_cell(rutile_titanium_dioxide()),
    ),
}
"""One ``check_all`` or ``with_phonon_findings`` call per catalogued code
that returns exactly that finding."""

_OTHER_OCCURRENCES = {
    "phonon.isolated_boundary_unsupported": lambda: _phonon(
        boundary=_resolved(BoundaryFacts("periodic")),
        magnetic=written_cell(carbon_pair_in_a_box()),
    ),
}
"""A call per catalogued code that returns exactly that finding, worded for
another occurrence than its ``_TRIGGERS`` call's: a box under an isolation
other than 'isolated'."""


@pytest.mark.parametrize(
    "warning",
    (*WARNING_CATALOGUE, *OVERRIDES_WARNING_CATALOGUE),
    ids=lambda warning: warning.code,
)
def test_every_published_warning_reads_as_user_text(warning: Warning) -> None:
    """The catalogue ``/capabilities`` publishes."""
    assert _internal(warning.message) == []


_SUMMARY_LIMIT = 200
"""Characters in a finding's summary: about four lines of the Workbench's
Bundle card (#223)."""


def _summary_reads_as_user_text(summary: str) -> None:
    assert 0 < len(summary) <= _SUMMARY_LIMIT, summary
    assert _internal(summary) == []


@pytest.mark.parametrize("finding", FINDING_CATALOGUE, ids=lambda f: f.code)
def test_every_catalogued_finding_reads_as_user_text(finding) -> None:
    assert _internal(finding.message) == []
    _summary_reads_as_user_text(finding.summary)


def test_every_catalogued_finding_has_a_trigger() -> None:
    assert set(_TRIGGERS) == {finding.code for finding in FINDING_CATALOGUE}


def _reads_as_user_text(code: str, report: CheckReport) -> None:
    """``report`` holds exactly one finding, of ``code``, in user text, with
    a summary of at most ``_SUMMARY_LIMIT`` characters."""
    (finding,) = report.blocking
    assert finding.code == code
    assert _internal(finding.message) == []
    _summary_reads_as_user_text(finding.summary)


@pytest.mark.parametrize("code", list(_TRIGGERS))
def test_each_finding_the_gate_returns_reads_as_user_text(code: str) -> None:
    _reads_as_user_text(code, _TRIGGERS[code]())


@pytest.mark.parametrize("code", list(_OTHER_OCCURRENCES))
def test_other_occurrences_of_a_finding_read_as_user_text(code: str) -> None:
    _reads_as_user_text(code, _OTHER_OCCURRENCES[code]())


def test_the_isolated_heuristic_explains_itself_without_design_ids() -> None:
    """The source note of the 'isolated' default is shown with the record."""
    state = boundary(
        Resolved(
            geometry_facts("molecule", ("a", "b", "c")), Provenance(source="heuristic")
        ),
        Blocked(by="symmetry undecided"),
    )

    assert state.value.isolation == "isolated"
    assert state.provenance.source_note
    assert _internal(state.provenance.source_note) == []
