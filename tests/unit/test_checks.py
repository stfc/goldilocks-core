from __future__ import annotations

import dataclasses
from typing import get_args

import pytest
from pydantic import ValidationError
from pymatgen.core import Lattice, Structure
from support import (
    alpha_uranium,
    carbon_chain,
    carbon_pair_in_a_box,
    framed_magnetic_cell,
    graphene_monolayer,
    graphene_with_c_tilted,
    graphene_with_vacuum_along_a,
    graphene_with_vacuum_along_x,
    graphite,
    mc3d_42058_silicon,
    molybdenum_disulfide_monolayer,
    rhombohedral_bismuth_selenide,
    rock_salt,
    rotated_about_x,
    rutile_titanium_dioxide,
    uranium_nitride,
    with_vacuum_along,
    written_bcc_iron,
    written_cell,
)

from goldilocks_core.advisors.boundary import BoundaryFacts
from goldilocks_core.advisors.cutoffs import CutoffsDecision
from goldilocks_core.advisors.electron_count import ElectronCountDecision
from goldilocks_core.advisors.fft_grid import FftGridDecision, fft_grid
from goldilocks_core.advisors.hubbard_u import HubbardU, HubbardUDecision
from goldilocks_core.advisors.job_resources import JobDecision
from goldilocks_core.advisors.magnetic_config import (
    MagneticConfigFacts,
    MagneticConfigHumanInput,
    OrderingRecord,
    magnetic_cell,
    magnetic_config,
)
from goldilocks_core.advisors.nbnd import NbndDecision
from goldilocks_core.advisors.occupations import Occupations, OccupationsDecision
from goldilocks_core.advisors.parallelisation import ParallelisationDecision
from goldilocks_core.advisors.q_sampling import QSamplingHumanInput, q_sampling
from goldilocks_core.advisors.relax import RelaxOptions, VcRelaxOptions
from goldilocks_core.advisors.vdw_method import VdwFacts, VdwMethodHumanInput
from goldilocks_core.assets.pseudopotentials.registry import load_tables
from goldilocks_core.capabilities import bindings, capabilities
from goldilocks_core.checks import (
    FINDING_CATALOGUE,
    CheckReport,
    Finding,
    check_all,
    collect_blocked,
    with_phonon_findings,
)
from goldilocks_core.pw_symmetry import pw_frame
from goldilocks_core.resolution import Blocked, Provenance, Resolved, Unavailable
from goldilocks_core.set_overrides import build_overrides
from goldilocks_core.types import CalcTask

_SUMMARY = {finding.code: finding.summary for finding in FINDING_CATALOGUE}
"""Each catalogued finding's summary, which every occurrence of it keeps
unless its code words one per branch (#223)."""
_IRON = Structure(Lattice.cubic(2.87), ["Fe"], [[0.0, 0.0, 0.0]])


def _only(report: CheckReport) -> Finding:
    """The one finding of ``report``."""
    (finding,) = report.blocking
    return finding


def _blocked(*causes: str) -> tuple[Finding, ...]:
    """The findings ``collect_blocked`` gives for root causes ``causes``."""
    return tuple(
        Finding(
            code="advice.blocked", message=cause, summary=_SUMMARY["advice.blocked"]
        )
        for cause in causes
    )


def _messages(report: CheckReport) -> list[str]:
    return [finding.message for finding in report.blocking]


def _fixed(tot_magnetization: float | None = None):
    """Fixed occupations pinning ``tot_magnetization`` -- the moment the
    gate checks and the writer renders (#138)."""
    return Resolved(
        OccupationsDecision(
            occupations="fixed",
            smearing_type=None,
            degauss=None,
            tot_magnetization=tot_magnetization,
        ),
        Provenance(source="heuristic"),
    )


_FIXED = _fixed()
_SMEARING = Resolved(
    OccupationsDecision(
        occupations="smearing",
        smearing_type="cold",
        degauss=0.01,
        tot_magnetization=2.5,
    ),
    Provenance(source="heuristic"),
)


def _magnetic(
    spin_polarized: bool,
    structure: Structure = _IRON,
    *,
    spin_orbit_enabled: bool = False,
):
    angles = {"Fe": 0.0} if spin_polarized and spin_orbit_enabled else None
    facts = MagneticConfigFacts(
        cell=structure,
        ordering=OrderingRecord(
            requested=None, applied="fm" if spin_polarized else None
        ),
        spin_polarized=spin_polarized,
        magnetic_elements=("Fe",) if spin_polarized else (),
        starting_magnetization={"Fe": 0.1} if spin_polarized else None,
        compensated=False,
        tot_magnetization=None,
        spin_orbit_enabled=spin_orbit_enabled,
        angle1=angles,
        angle2=angles,
    )
    return Resolved(facts, Provenance(source="heuristic"))


def test_collect_blocked_returns_only_blocked_root_causes() -> None:
    """A blocked chain reaches the gate as 'advice.blocked', its root cause
    the message, with no setting to point at and no remedy (#151)."""
    findings = collect_blocked(
        Resolved(1, Provenance(source="heuristic")),
        Unavailable(reason="could not tell"),
        Blocked(by=Blocked(by="upstream failure")),
    )

    assert findings == _blocked("upstream failure")
    assert findings[0].fields == ()
    assert findings[0].remedies == ()


def test_check_all_with_nothing_given_is_ok() -> None:
    report = check_all()

    assert report.ok
    assert report.blocking == ()


def test_check_all_surfaces_a_blocked_field_state() -> None:
    report = check_all(Blocked(by="pseudopotential selection failed"))

    assert not report.ok
    assert report.blocking == _blocked("pseudopotential selection failed")


def test_a_report_holds_one_finding_per_root_cause() -> None:
    """#151: every field a missing table blocks repeats its root cause, and
    the gate reports it once, in first-seen order, whoever builds the
    report."""
    report = check_all(
        Blocked(by="table missing"),
        Blocked(by=Blocked(by="table missing")),
        Blocked(by="job undecided"),
        Blocked(by="table missing"),
    )
    merged = CheckReport(blocking=report.blocking + report.blocking)

    assert report.blocking == _blocked("table missing", "job undecided")
    assert merged.blocking == report.blocking


def test_findings_with_one_code_and_different_messages_are_kept() -> None:
    first, second = _blocked("table missing", "job undecided")

    assert CheckReport(blocking=(first, second, first)).blocking == (first, second)


def test_fixed_occupations_with_non_integer_moment_blocks() -> None:
    report = check_all(occupations=_fixed(2.5), magnetic=_magnetic(True), purpose="scf")

    finding = _only(report)
    assert finding.code == "occupations.fixed_needs_integer_tot_magnetization"
    assert finding.fields == ("occupations", "tot_magnetization")
    assert finding.remedies == ({"occupations": "smearing"},)
    assert "integer tot_magnetization, not 2.5." in finding.message


def test_fixed_occupations_with_missing_moment_blocks() -> None:
    """The LiFePO4 refusal of #151: the remedy is occupations=smearing;
    a tot_magnetization needs a value only the user can choose, so the
    message names it and no remedy guesses one."""
    report = check_all(occupations=_FIXED, magnetic=_magnetic(True), purpose="scf")

    assert report.blocking == (
        Finding(
            code="occupations.fixed_needs_tot_magnetization",
            summary=_SUMMARY["occupations.fixed_needs_tot_magnetization"],
            message=(
                "occupations=fixed on a collinear spin-polarized run needs an "
                "integer tot_magnetization of the electron count's parity, and "
                "none was set or derived. Set occupations=smearing, or set "
                "tot_magnetization."
            ),
            fields=("occupations", "tot_magnetization"),
            remedies=({"occupations": "smearing"},),
        ),
    )


def test_fixed_occupations_with_integer_moment_is_ok() -> None:
    report = check_all(occupations=_fixed(2.0), magnetic=_magnetic(True), purpose="scf")

    assert report.ok


def test_the_moment_rule_reads_the_occupations_decision_not_the_request() -> None:
    """#138: the occupations decision holds the moment the input pins, the
    one the writer renders: the 0 it derives for a compensated ordering
    passes, though no moment was requested."""
    derived = check_all(
        occupations=_fixed(0.0),
        magnetic=_magnetic(True),
        electron_count=_electron_count(48.0),
        purpose="scf",
    )

    assert derived.ok, _messages(derived)


def test_smearing_occupations_never_triggers_the_moment_check() -> None:
    report = check_all(occupations=_SMEARING, magnetic=_magnetic(True), purpose="scf")

    assert report.ok


def test_non_magnetic_system_never_triggers_the_moment_check() -> None:
    report = check_all(occupations=_FIXED, magnetic=_magnetic(False), purpose="scf")

    assert report.ok


def test_the_moment_check_is_scoped_to_the_scf_step_only() -> None:
    report = check_all(
        occupations=_fixed(2.5), magnetic=_magnetic(True), purpose="nscf"
    )

    assert report.ok


def test_the_moment_check_also_applies_to_relax_and_vc_relax() -> None:
    """relax/vc-relax re-run their own scf loop at every ionic step (v2
    epic 10, #10) -- unlike nscf, which reads a prior step's already
    -converged density/spin."""
    for purpose in ("relax", "vc-relax"):
        report = check_all(
            occupations=_fixed(2.5), magnetic=_magnetic(True), purpose=purpose
        )

        assert not report.ok, purpose
        assert _only(report).code == (
            "occupations.fixed_needs_integer_tot_magnetization"
        )


def test_blocked_occupations_surfaces_once_via_the_generic_scan() -> None:
    report = check_all(occupations=Blocked(by="functional undecided"), purpose="scf")

    assert report.blocking == _blocked("functional undecided")


def _electron_count(nelec: float):
    return Resolved(
        ElectronCountDecision(nelec=nelec, tot_charge=0.0),
        Provenance(source="heuristic"),
    )


def test_fixed_occupations_non_spin_polarized_odd_electron_count_blocks() -> None:
    """#70: a single boron atom (nelec=3) forced non-metal -- real repro
    that produced a silently-wrong-electron-count scf.in before this
    check existed."""
    report = check_all(
        occupations=_FIXED,
        magnetic=_magnetic(False),
        electron_count=_electron_count(3.0),
        purpose="scf",
    )

    assert report.blocking == (
        Finding(
            code="occupations.fixed_needs_even_electron_count",
            summary=_SUMMARY["occupations.fixed_needs_even_electron_count"],
            message=(
                "occupations=fixed without spin polarization needs an even "
                "electron count, but nelec=3 is odd, which leaves one band half "
                "filled. Set occupations=smearing, or spin_polarized=true with "
                "occupations=smearing for an unpaired electron."
            ),
            fields=("occupations", "spin_polarized"),
            remedies=(
                {"occupations": "smearing"},
                {"spin_polarized": True, "occupations": "smearing"},
            ),
        ),
    )


def test_fixed_occupations_non_spin_polarized_even_electron_count_is_ok() -> None:
    report = check_all(
        occupations=_FIXED,
        magnetic=_magnetic(False),
        electron_count=_electron_count(4.0),
        purpose="scf",
    )

    assert report.ok


def test_smearing_occupations_never_triggers_the_electron_count_check() -> None:
    report = check_all(
        occupations=_SMEARING,
        magnetic=_magnetic(False),
        electron_count=_electron_count(3.0),
        purpose="scf",
    )

    assert report.ok


def test_spin_polarized_system_never_triggers_the_electron_count_check() -> None:
    """An odd-electron, spin-polarized system is the sibling
    integer-moment check's territory instead."""
    report = check_all(
        occupations=_fixed(1.0),
        magnetic=_magnetic(True),
        electron_count=_electron_count(3.0),
        purpose="scf",
    )

    assert report.ok


def test_the_electron_count_check_is_scoped_to_the_scf_step_only() -> None:
    report = check_all(
        occupations=_FIXED,
        magnetic=_magnetic(False),
        electron_count=_electron_count(3.0),
        purpose="nscf",
    )

    assert report.ok


def test_the_electron_count_check_also_applies_to_relax_and_vc_relax() -> None:
    for purpose in ("relax", "vc-relax"):
        report = check_all(
            occupations=_FIXED,
            magnetic=_magnetic(False),
            electron_count=_electron_count(3.0),
            purpose=purpose,
        )

        assert not report.ok, purpose
        assert _only(report).code == "occupations.fixed_needs_even_electron_count"


def test_moment_and_electron_count_must_share_parity() -> None:
    """#70's second finding: an integer tot_magnetization alone is not
    enough -- nelup=(nelec+tot)/2 and neldw=(nelec-tot)/2 both need to
    be integers, which needs matching parity (nelec=3, tot=2 gives
    nelup=2.5/neldw=0.5)."""
    report = check_all(
        occupations=_fixed(2.0),
        magnetic=_magnetic(True),
        electron_count=_electron_count(3.0),
        purpose="scf",
    )

    finding = _only(report)
    assert finding.code == "occupations.fixed_tot_magnetization_parity"
    assert finding.fields == ("occupations", "tot_magnetization")
    assert finding.remedies == ({"occupations": "smearing"},)
    assert "tot_magnetization=2 and nelec=3 do not." in finding.message


def test_moment_and_electron_count_with_matching_parity_is_ok() -> None:
    report = check_all(
        occupations=_fixed(1.0),
        magnetic=_magnetic(True),
        electron_count=_electron_count(3.0),
        purpose="scf",
    )

    assert report.ok


def test_a_magnetic_spin_orbit_run_needs_no_moment_or_even_count() -> None:
    """#146: spin-orbit coupling runs noncollinear, where pw.x sets
    nspin=4 and lsda=.false. (QE 7.3 PW/src/input.f90:714-736). Its
    "fixed occupations and lsda need tot_magnetization" stop applies only
    with lsda (input.f90:764-781), and its fixed occupations fill
    NINT(nelec) single-electron spinor bands (degspin=1,
    PW/src/iweights.f90:105-107). With moments, time reversal is broken,
    so an odd count can fill whole bands and neither rule applies."""
    report = check_all(
        occupations=_FIXED,
        magnetic=_magnetic(True, spin_orbit_enabled=True),
        electron_count=_electron_count(3.0),
        purpose="scf",
    )

    assert report.ok, _messages(report)


def test_a_non_magnetic_spin_orbit_run_needs_an_even_count() -> None:
    """A spin-orbit run without moments keeps time reversal: every band has
    a Kramers partner degenerate with it at the time-reversal-invariant
    k-points (at every k with inversion), so an odd count half-fills a
    degenerate pair, metallic as without spin-orbit coupling. degspin=1
    removes the truncation, not the half-filled band."""
    odd = check_all(
        occupations=_FIXED,
        magnetic=_magnetic(False, spin_orbit_enabled=True),
        electron_count=_electron_count(9.0),
        purpose="scf",
    )
    even = check_all(
        occupations=_FIXED,
        magnetic=_magnetic(False, spin_orbit_enabled=True),
        electron_count=_electron_count(8.0),
        purpose="scf",
    )

    assert _only(odd).code == "occupations.fixed_needs_even_electron_count"
    assert "but nelec=9 is odd" in _only(odd).message
    assert even.ok, _messages(even)


def test_moment_parity_check_is_unaffected_when_electron_count_is_missing() -> None:
    """Existing callers that don't pass electron_count (pre-#70) keep
    exactly their previous behaviour: integer tot_magnetization alone
    is accepted."""
    report = check_all(occupations=_fixed(2.0), magnetic=_magnetic(True), purpose="scf")

    assert report.ok


def _relax(ion_dynamics: str = "bfgs"):
    return Resolved(
        RelaxOptions(ion_dynamics=ion_dynamics), Provenance(source="heuristic")
    )


def _vc_relax(ion_dynamics: str = "bfgs"):
    return Resolved(
        VcRelaxOptions(ion_dynamics=ion_dynamics), Provenance(source="heuristic")
    )


def test_vc_relax_with_bfgs_ion_dynamics_is_ok() -> None:
    report = check_all(relax=_vc_relax("bfgs"), purpose="vc-relax")

    assert report.ok


def test_vc_relax_with_non_bfgs_ion_dynamics_blocks() -> None:
    report = check_all(relax=_vc_relax("damp"), purpose="vc-relax")

    finding = _only(report)
    assert finding.code == "relax.vc_relax_needs_bfgs"
    assert finding.fields == ("ion_dynamics",)
    assert finding.remedies == ({"ion_dynamics": "bfgs"},)
    assert finding.message.startswith(
        "vc-relax is generated only with ion_dynamics=bfgs, not damp:"
    )


def test_plain_relax_with_non_bfgs_ion_dynamics_is_unaffected() -> None:
    """The bfgs-only restriction is vc-relax-specific -- QE genuinely
    supports damp/fire for a plain relax."""
    report = check_all(relax=_relax("damp"), purpose="relax")

    assert report.ok


def test_relax_blocked_field_state_surfaces_via_the_generic_scan() -> None:
    report = check_all(relax=Blocked(by="convergence undecided"), purpose="vc-relax")

    assert report.blocking == _blocked("convergence undecided")


def _boundary(isolation: str, source: str = "heuristic"):
    return Resolved(BoundaryFacts(isolation), Provenance(source=source))


def test_vc_relax_of_an_isolated_system_blocks() -> None:
    """#126: pw.x clears tstress for an isolated system (QE 7.3
    PW/src/input.f90:1361-1365), so BFGS sees a zero cell gradient and
    reports the input cell as converged."""
    report = check_all(boundary=_boundary("isolated"), purpose="vc-relax")

    finding = _only(report)
    assert finding.code == "boundary.isolated_forbids_vc_relax"
    assert finding.fields == ("isolation",)
    assert finding.remedies == ()
    assert "with isolation=isolated (Martyna-Tuckerman)" in finding.message
    assert "Use the relax task" in finding.message


def test_a_human_isolated_override_on_vc_relax_blocks_too() -> None:
    report = check_all(
        boundary=_boundary("isolated", source="human"), purpose="vc-relax"
    )

    assert _only(report).code == "boundary.isolated_forbids_vc_relax"


def test_an_isolated_system_without_a_cell_relaxation_passes() -> None:
    for purpose in ("scf", "nscf", "relax"):
        report = check_all(boundary=_boundary("isolated"), purpose=purpose)

        assert report.ok, purpose


@pytest.mark.parametrize("isolation", ["periodic", "slab"])
def test_vc_relax_with_a_boundary_that_computes_stress_passes(isolation: str) -> None:
    report = check_all(boundary=_boundary(isolation), purpose="vc-relax")

    assert report.ok


def test_blocked_boundary_surfaces_once_via_the_generic_scan() -> None:
    report = check_all(boundary=Blocked(by="geometry undecided"), purpose="vc-relax")

    assert report.blocking == _blocked("geometry undecided")


def _vc_relax_with_cell_dofree(cell_dofree: str):
    return Resolved(VcRelaxOptions(cell_dofree=cell_dofree), Provenance(source="human"))


def _isolation_findings(isolation: str, structure: Structure) -> tuple[Finding, ...]:
    return check_all(
        boundary=_boundary(isolation, source="human"),
        magnetic=written_cell(structure),
    ).blocking


@pytest.mark.parametrize(
    "build",
    [graphene_monolayer, molybdenum_disulfide_monolayer],
    ids=lambda build: build.__name__,
)
def test_a_slab_in_the_xy_frame_with_room_for_the_2d_truncation_passes(
    build,
) -> None:
    """#161: QE's assume_isolated='2D' truncates the Coulomb interaction
    beyond half the cell height along z (QE 7.3 PW/src/Coul_cut_2D.f90:77).
    A sheet in a 20 A cell meets every precondition."""
    assert _isolation_findings("slab", build()) == ()


@pytest.mark.parametrize(
    ("build", "found"),
    [
        (graphite, "no vacuum"),
        (graphene_with_vacuum_along_x, "vacuum along a"),
        (graphene_with_vacuum_along_a, "a or b out of the xy plane and vacuum along a"),
        (
            lambda: rotated_about_x(graphene_monolayer(), 30.0),
            "a or b out of the xy plane",
        ),
        (carbon_chain, "vacuum along a and b"),
        (carbon_pair_in_a_box, "vacuum along a, b and c"),
        (graphene_with_c_tilted, "c off the z axis"),
        (
            lambda: graphene_monolayer(c=11.0),
            "a height of 11.00 Å along z (at least 11.11 Å needed)",
        ),
        (
            lambda: molybdenum_disulfide_monolayer(c=12.0),
            "8.83 Å of vacuum around a slab 3.17 Å thick (at least 13.75 Å needed)",
        ),
    ],
    ids=[
        "bulk",
        "vacuum-along-a",
        "vacuum-vector-out-of-plane",
        "tilted-slab",
        "wire",
        "molecule",
        "c-off-z",
        "below-21-bohr",
        "thick-slab-in-a-short-cell",
    ],
)
def test_a_slab_isolation_without_qe_2d_preconditions_blocks(build, found: str) -> None:
    """'2D' needs the vacuum along c only and a, b in the xy plane (QE 7.3
    PW/src/Coul_cut_2D.f90:72-74), c along z, the only frame in which its
    cutoff factor is exact (Coul_cut_2D.f90:77-81), half the cell height
    above the pseudopotentials' 10 bohr radial cutoff
    (PW/src/init_vloc.f90:62-65), and vacuum 20 bohr wider than the slab
    (PW/Doc/INPUT_PW.def:1668-1675). A 11.00 A cell is below 21 bohr
    (11.11 A); the 3.17 A MoS2 sheet needs 13.75 A of vacuum."""
    (finding,) = _isolation_findings("slab", build())

    assert finding.code == "boundary.slab_unsuited_to_2d_truncation"
    assert finding.fields == ("isolation",)
    assert finding.remedies == ({"isolation": "periodic"},)
    assert finding.message.startswith("isolation=slab writes")
    assert f"the cell to be written has {found}." in finding.message
    assert finding.message.endswith("Set isolation=periodic.")


def test_the_2d_height_floor_is_21_bohr() -> None:
    """Graphene has no thickness, so 11.12 A of vacuum clears the 20 bohr
    (10.58 A) margin and isolates the height floor: 21 bohr is 11.113 A."""
    assert _isolation_findings("slab", graphene_monolayer(c=11.12)) == ()
    assert len(_isolation_findings("slab", graphene_monolayer(c=11.1))) == 1


def test_the_2d_vacuum_margin_is_20_bohr_beyond_the_slab() -> None:
    """The 3.17 A MoS2 sheet needs 3.17 + 10.58 = 13.75 A of vacuum: a
    16.93 A cell leaves 13.76 A, a 16.91 A cell 13.74 A."""
    assert _isolation_findings("slab", molybdenum_disulfide_monolayer(c=16.93)) == ()
    (finding,) = _isolation_findings("slab", molybdenum_disulfide_monolayer(c=16.91))
    assert "13.74 Å of vacuum around a slab 3.17 Å thick" in finding.message


def test_an_isolated_system_in_a_box_passes() -> None:
    assert _isolation_findings("isolated", carbon_pair_in_a_box()) == ()


@pytest.mark.parametrize(
    ("build", "found"),
    [
        (graphite, "no vacuum"),
        (graphene_monolayer, "vacuum only along c"),
        (carbon_chain, "vacuum only along a and b"),
    ],
    ids=["bulk", "slab", "wire"],
)
def test_an_isolated_boundary_on_a_periodic_cell_blocks(build, found: str) -> None:
    """#161: Martyna-Tuckerman is a correction for a molecule or cluster in
    a 3D supercell (QE 7.3 PW/Doc/INPUT_PW.def:1593-1594), and pw.x has no
    1D truncation, so a wire must stay periodic."""
    (finding,) = _isolation_findings("isolated", build())

    assert finding.code == "boundary.isolated_needs_vacuum"
    assert finding.fields == ("isolation",)
    assert finding.remedies == ({"isolation": "periodic"},)
    assert finding.message.startswith("isolation=isolated writes Martyna-Tuckerman")
    assert f"the cell to be written has {found}." in finding.message
    assert finding.message.endswith("Set isolation=periodic.")


@pytest.mark.parametrize(
    "build", [graphite, carbon_chain, carbon_pair_in_a_box], ids=lambda b: b.__name__
)
def test_a_periodic_boundary_suits_every_cell(build) -> None:
    assert _isolation_findings("periodic", build()) == ()


@pytest.mark.parametrize("isolation", ["slab", "isolated"])
def test_the_isolation_gate_is_skipped_without_the_written_cell(
    isolation: str,
) -> None:
    assert check_all(boundary=_boundary(isolation)).ok


def test_the_isolation_gate_reads_the_written_cell_whatever_the_source() -> None:
    """The heuristic decides from the input structure; an AFM cell can move
    the vacuum, and the gate judges the cell pw.x reads."""
    report = check_all(
        boundary=_boundary("isolated", source="heuristic"),
        magnetic=written_cell(graphite()),
    )

    assert _only(report).code == "boundary.isolated_needs_vacuum"


@pytest.mark.parametrize("cell_dofree", ["all", "shape", "z", "fixc", "epitaxial_ab"])
def test_vc_relax_under_the_2d_truncation_needs_a_2d_cell_constraint(
    cell_dofree: str,
) -> None:
    """Under '2D' only in-plane stresses make sense, and QE asks for
    cell_dofree='2Dxy' (QE 7.3 PW/Doc/INPUT_PW.def:1677-1678); pw.x itself
    does not check it. The periodic remedy also unsets cell_dofree: kept, an
    explicit 'all' would pass under isolation=periodic and relax the vacuum."""
    report = check_all(
        boundary=_boundary("slab", source="human"),
        relax=_vc_relax_with_cell_dofree(cell_dofree),
        magnetic=written_cell(graphene_monolayer()),
        purpose="vc-relax",
    )

    finding = _only(report)
    assert finding.code == "relax.slab_vc_relax_needs_2d_cell_dofree"
    assert finding.fields == ("cell_dofree", "isolation")
    assert finding.remedies == (
        {"cell_dofree": "2Dxy"},
        {"isolation": "periodic", "cell_dofree": None},
    )
    assert f"cannot use cell_dofree={cell_dofree}:" in finding.message
    assert finding.message.endswith(
        "Set cell_dofree=2Dxy (or 2Dshape), or isolation=periodic with "
        "cell_dofree unset."
    )


@pytest.mark.parametrize(
    "build",
    [
        graphene_with_vacuum_along_x,
        carbon_chain,
        carbon_pair_in_a_box,
        rhombohedral_bismuth_selenide,
        graphite,
    ],
    ids=lambda build: build.__name__,
)
def test_isolation_slab_outside_a_slab_in_the_xy_frame_is_left_to_the_boundary_rule(
    build,
) -> None:
    """The 2D cell constraint's remedies need a slab with its vacuum along c
    in the xy frame. Elsewhere the request needs isolation=periodic anyway,
    '2Dxy' fails the 2D-frame rule on a wire, a box or a cell out of the xy
    frame, and an unset cell_dofree gives a box 'all' and blocks a wire, so
    the boundary rule alone refuses isolation=slab, with isolation=periodic
    as its remedy."""
    report = check_all(
        boundary=_boundary("slab", source="human"),
        relax=_vc_relax_with_cell_dofree("all"),
        magnetic=written_cell(build()),
        purpose="vc-relax",
    )

    assert _only(report).code == "boundary.slab_unsuited_to_2d_truncation"


@pytest.mark.parametrize(
    "build",
    [lambda: molybdenum_disulfide_monolayer(c=12.0), graphene_with_c_tilted],
    ids=["MoS2 with too little vacuum", "graphene with c tilted"],
)
def test_a_slab_in_the_xy_frame_without_room_for_the_truncation_gets_both_findings(
    build,
) -> None:
    """Such a slab's default is '2Dxy', so isolation=periodic with
    cell_dofree unset resolves both findings and holds the vacuum fixed."""
    report = check_all(
        boundary=_boundary("slab", source="human"),
        relax=_vc_relax_with_cell_dofree("all"),
        magnetic=written_cell(build()),
        purpose="vc-relax",
    )

    assert [finding.code for finding in report.blocking] == [
        "boundary.slab_unsuited_to_2d_truncation",
        "relax.slab_vc_relax_needs_2d_cell_dofree",
    ]
    assert report.blocking[1].remedies == (
        {"cell_dofree": "2Dxy"},
        {"isolation": "periodic", "cell_dofree": None},
    )


@pytest.mark.parametrize("cell_dofree", ["2Dxy", "2Dshape"])
def test_vc_relax_under_the_2d_truncation_with_a_2d_cell_constraint_passes(
    cell_dofree: str,
) -> None:
    report = check_all(
        boundary=_boundary("slab", source="human"),
        relax=_vc_relax_with_cell_dofree(cell_dofree),
        magnetic=written_cell(graphene_monolayer()),
        purpose="vc-relax",
    )

    assert report.ok


def test_a_plain_relax_under_the_2d_truncation_needs_no_cell_constraint() -> None:
    report = check_all(
        boundary=_boundary("slab", source="human"),
        relax=Resolved(RelaxOptions(), Provenance(source="heuristic")),
        magnetic=written_cell(graphene_monolayer()),
        purpose="relax",
    )

    assert report.ok


def test_a_periodic_slab_may_relax_its_whole_cell() -> None:
    report = check_all(
        boundary=_boundary("periodic"),
        relax=_vc_relax_with_cell_dofree("all"),
        magnetic=written_cell(graphene_monolayer()),
        purpose="vc-relax",
    )

    assert report.ok


def test_a_2d_cell_constraint_on_a_tilted_bulk_cell_blocks() -> None:
    """#132: '2Dxy' moves only the x and y components of a and b (QE 7.3
    Modules/cell_base.f90:803-808), so with a and b out of the xy plane
    (rhombohedral Bi2Se3) it distorts the cell. Without vacuum, 'all' is
    the remedy."""
    report = check_all(
        relax=_vc_relax_with_cell_dofree("2Dxy"),
        magnetic=written_cell(rhombohedral_bismuth_selenide()),
        purpose="vc-relax",
    )

    finding = _only(report)
    assert finding.code == "relax.two_d_cell_dofree_needs_xy_frame"
    assert finding.fields == ("cell_dofree",)
    assert finding.remedies == ({"cell_dofree": "all"},)
    assert finding.message.startswith("cell_dofree=2Dxy moves only")
    assert finding.message.endswith("Set cell_dofree=all, or reorient the cell.")


@pytest.mark.parametrize(
    ("build", "advice"),
    [
        (
            graphene_with_vacuum_along_x,
            "has vacuum along a. Reorient the cell, or set a cell_dofree that "
            "holds the vacuum fixed: cell_dofree=all would relax the vacuum too.",
        ),
        (
            carbon_chain,
            "has vacuum along a and b. Set a cell_dofree that holds the vacuum "
            "fixed: cell_dofree=epitaxial_ab holds a and b fixed and relaxes only "
            "c, the wire's period, while cell_dofree=all would relax the vacuum "
            "too.",
        ),
        # The chain's period permuted onto a, then b: it still lies along z,
        # where 'x' or 'y' would move a component of it that is zero.
        pytest.param(
            lambda: with_vacuum_along(carbon_chain(), "a"),
            "vacuum along b and c. Set a cell_dofree that holds the vacuum fixed: "
            "cell_dofree=epitaxial_bc holds b and c fixed and relaxes only a, the "
            "wire's period, while cell_dofree=all would relax the vacuum too.",
            id="carbon_chain_with_its_period_along_a",
        ),
        pytest.param(
            lambda: with_vacuum_along(carbon_chain(), "b"),
            "vacuum along a and c. Set a cell_dofree that holds the vacuum fixed: "
            "cell_dofree=epitaxial_ac holds a and c fixed and relaxes only b, the "
            "wire's period, while cell_dofree=all would relax the vacuum too.",
            id="carbon_chain_with_its_period_along_b",
        ),
        (
            carbon_pair_in_a_box,
            "has vacuum along a, b and c. Use the relax task for a molecule or "
            "cluster in a box: every lattice vector is a vacuum vector, so a "
            "vc-relax would relax the vacuum.",
        ),
    ],
    ids=lambda value: value.__name__ if callable(value) else None,
)
def test_a_2d_cell_constraint_on_a_cell_with_vacuum_offers_no_remedy(
    build, advice: str
) -> None:
    """#132: with the vacuum along a, '2Dxy' frees the vacuum vector. 'all'
    would free every vacuum vector, which is why the relax advisor gives a
    wire or a slab outside the xy frame no default: the finding names no
    remedy, and says what holds the vacuum fixed. Only a slab can be
    reoriented to suit '2Dxy'; a wire relaxes its period alone, and a
    molecule in a box needs the relax task."""
    report = check_all(
        relax=_vc_relax_with_cell_dofree("2Dxy"),
        magnetic=written_cell(build()),
        purpose="vc-relax",
    )

    finding = _only(report)
    assert finding.code == "relax.two_d_cell_dofree_needs_xy_frame"
    assert finding.remedies == ()
    assert finding.message.endswith(advice)


@pytest.mark.parametrize(
    ("build", "found"),
    [
        (graphene_with_vacuum_along_x, "vacuum along a"),
        (rhombohedral_bismuth_selenide, "a or b out of the xy plane"),
        (carbon_chain, "vacuum along a and b"),
        (graphene_with_vacuum_along_a, "a or b out of the xy plane and vacuum along a"),
    ],
    ids=lambda value: value.__name__ if callable(value) else None,
)
def test_the_frame_reason_names_what_is_out_of_place(build, found: str) -> None:
    report = check_all(
        relax=_vc_relax_with_cell_dofree("2Dxy"),
        magnetic=written_cell(build()),
        purpose="vc-relax",
    )

    assert f"the cell to be written has {found}." in _only(report).message


@pytest.mark.parametrize("cell_dofree", ["2Dxy", "2Dshape"])
def test_every_2d_cell_constraint_is_checked_against_the_frame(
    cell_dofree: str,
) -> None:
    report = check_all(
        relax=_vc_relax_with_cell_dofree(cell_dofree),
        magnetic=written_cell(rhombohedral_bismuth_selenide()),
        purpose="vc-relax",
    )

    assert _only(report).message.startswith(f"cell_dofree={cell_dofree} moves only")


@pytest.mark.parametrize(
    "build", [graphite, graphene_monolayer], ids=lambda build: build.__name__
)
def test_a_2d_cell_constraint_in_the_xy_frame_passes(build) -> None:
    """Bulk graphite keeps an explicit '2Dxy' (in-plane relaxation at fixed
    c); the monolayer has its vacuum along c."""
    report = check_all(
        relax=_vc_relax_with_cell_dofree("2Dxy"),
        magnetic=written_cell(build()),
        purpose="vc-relax",
    )

    assert report.ok


@pytest.mark.parametrize("cell_dofree", ["all", "shape", "z"])
def test_other_cell_constraints_are_not_checked_against_the_frame(
    cell_dofree: str,
) -> None:
    report = check_all(
        relax=_vc_relax_with_cell_dofree(cell_dofree),
        magnetic=written_cell(rhombohedral_bismuth_selenide()),
        purpose="vc-relax",
    )

    assert report.ok


def test_the_frame_check_is_skipped_without_the_written_cell() -> None:
    report = check_all(relax=_vc_relax_with_cell_dofree("2Dxy"), purpose="vc-relax")

    assert report.ok


def _framed(structure: Structure):
    """The written cell of ``structure`` with the frame it was written in."""
    framed, frame = pw_frame(structure)
    facts = written_cell(framed).value
    return Resolved(
        dataclasses.replace(facts, frame=frame), Provenance(source="heuristic")
    )


@pytest.mark.parametrize(
    "cell_dofree",
    ["a", "b", "c", "x", "y", "z", "xy", "xz", "yz", "xyz"],
)
def test_a_cartesian_cell_constraint_on_a_turned_cell_blocks(cell_dofree: str) -> None:
    """#140: QE masks Cartesian components of the lattice vectors (QE 7.3
    Modules/cell_base.f90:710-830). Diamond Si's primitive cell is written
    turned into cubic axes, so 'z' would hold another component than the
    uploaded cell's z."""
    report = check_all(
        relax=_vc_relax_with_cell_dofree(cell_dofree),
        magnetic=_framed(mc3d_42058_silicon()),
        purpose="vc-relax",
    )

    finding = _only(report)
    assert finding.code == "relax.cartesian_cell_dofree_on_rotated_cell"
    assert finding.fields == ("cell_dofree",)
    assert finding.remedies == ({"cell_dofree": None},)
    assert finding.message.startswith(f"cell_dofree={cell_dofree} holds or frees")
    assert "rotated by 56.6003 degrees about [-0.7693, -0.2445, -0.5903]" in (
        finding.message
    )
    assert finding.message.endswith(
        "Unset cell_dofree for the default, or use cell_dofree=all or shape, or "
        "fixa, fixb or fixc to fix whole lattice vectors."
    )


@pytest.mark.parametrize("cell_dofree", ["all", "shape", "fixc", "epitaxial_ab"])
def test_a_constraint_of_whole_lattice_vectors_on_a_turned_cell_passes(
    cell_dofree: str,
) -> None:
    report = check_all(
        relax=_vc_relax_with_cell_dofree(cell_dofree),
        magnetic=_framed(mc3d_42058_silicon()),
        purpose="vc-relax",
    )

    assert report.ok


def test_a_cartesian_cell_constraint_on_an_unturned_cell_passes() -> None:
    """Rock salt in pymatgen's cubic cell is already in pw.x's frame."""
    sodium_chloride = Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(5.64), ["Na", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]]
    )
    cell = _framed(sodium_chloride)

    report = check_all(
        relax=_vc_relax_with_cell_dofree("z"), magnetic=cell, purpose="vc-relax"
    )

    assert not cell.value.frame.rotated
    assert report.ok


def _vdw(use_vdw: bool, source: str = "heuristic"):
    facts = VdwFacts(use_vdw=use_vdw, method="d3bj" if use_vdw else None)
    return Resolved(facts, Provenance(source=source))


def _functional(label: str):
    return Resolved(label, Provenance(source="human"))


def test_d3_dispersion_with_lda_blocks() -> None:
    """#141: pw.x hands DFT-D3 the pseudopotentials' short functional name
    (QE 7.3 PW/src/input.f90:2039-2041), and the D3(BJ) table has no LDA
    entry, so pw.x would stop with 'functional name unknown'."""
    report = check_all(vdw=_vdw(True, source="human"), functional=_functional("LDA"))

    assert report.blocking == (
        Finding(
            code="vdw.use_vdw_without_d3bj_parameters",
            summary=_SUMMARY["vdw.use_vdw_without_d3bj_parameters"],
            message=(
                "use_vdw=true adds D3(BJ) dispersion, but Quantum ESPRESSO's "
                "DFT-D3 has no parameters for functional LDA, so pw.x would stop "
                "with 'functional name unknown'. Set use_vdw=false, or choose a "
                "functional with D3(BJ) parameters (PBE, PBEsol)."
            ),
            fields=("use_vdw", "functional"),
            remedies=({"use_vdw": False},),
        ),
    )


def test_d3_dispersion_with_an_unrecognised_functional_blocks() -> None:
    report = check_all(vdw=_vdw(True, source="llm"), functional=_functional("revPBE"))

    assert "parameters for functional revPBE," in _only(report).message


def test_d3_dispersion_with_pbe_or_pbesol_passes() -> None:
    for label in ("PBE", "PBEsol"):
        report = check_all(vdw=_vdw(True), functional=_functional(label))

        assert report.ok, label


def test_no_dispersion_with_lda_passes() -> None:
    report = check_all(vdw=_vdw(False), functional=_functional("LDA"))

    assert report.ok


def test_dispersion_check_is_unaffected_when_either_side_is_missing() -> None:
    assert check_all(vdw=_vdw(True)).ok
    assert check_all(functional=_functional("LDA")).ok


def test_blocked_vdw_surfaces_once_via_the_generic_scan() -> None:
    report = check_all(
        vdw=Blocked(by="geometry undecided"), functional=_functional("LDA")
    )

    assert report.blocking == _blocked("geometry undecided")


def _relax_with_fix_bottom_layers(count: int | None):
    return Resolved(RelaxOptions(fix_bottom_layers=count), Provenance(source="human"))


def _fix_bottom_layers_findings(count: int | None, structure: Structure):
    return check_all(
        relax=_relax_with_fix_bottom_layers(count),
        magnetic=written_cell(structure),
    ).blocking


@pytest.mark.parametrize(
    "build",
    [graphene_monolayer, molybdenum_disulfide_monolayer, graphene_with_vacuum_along_x],
    ids=lambda build: build.__name__,
)
def test_fix_bottom_layers_on_a_slab_passes(build) -> None:
    """A slab is any cell with vacuum along exactly one lattice vector, in
    whatever orientation: if_pos flags do not depend on the Cartesian
    frame."""
    assert _fix_bottom_layers_findings(1, build()) == ()


@pytest.mark.parametrize(
    ("build", "found"),
    [
        (graphite, "no vacuum"),
        (carbon_chain, "vacuum along a and b"),
        (carbon_pair_in_a_box, "vacuum along a, b and c"),
    ],
    ids=["bulk-layered-crystal", "wire", "molecule"],
)
def test_fix_bottom_layers_without_exactly_one_vacuum_axis_blocks(
    build, found: str
) -> None:
    """#160: bulk graphite ranks '2d', yet it has no vacuum and so no bottom
    to count layers up from; with fix_bottom_layers=1 the rank-keyed gate
    passed and relax.in froze its z = 1/4 sheet. The gate reads the cell the
    writer renders, not the rank."""
    (finding,) = _fix_bottom_layers_findings(1, build())

    assert finding.code == "relax.fix_bottom_layers_needs_slab"
    assert finding.fields == ("fix_bottom_layers",)
    assert finding.remedies == ({"fix_bottom_layers": None},)
    assert finding.message.startswith("fix_bottom_layers freezes the bottom")
    assert f"The cell to be written has {found}." in finding.message
    assert finding.message.endswith("Unset fix_bottom_layers.")


def test_fix_bottom_layers_on_a_cell_holding_two_slabs_blocks() -> None:
    """An antiferromagnetic supercell can double a monolayer along its
    normal, putting two sheets and two vacuum gaps along c in the written
    cell. Counted up from one gap, the layers would run through one sheet
    and on into the other, so the gate refuses the cell."""
    (finding,) = _fix_bottom_layers_findings(
        1, molybdenum_disulfide_monolayer() * (1, 1, 2)
    )

    assert finding.message == (
        "fix_bottom_layers freezes the bottom atomic layers counted up from the "
        "vacuum, so it needs a slab: one vacuum gap, along exactly one lattice "
        "vector. The cell to be written has more than one vacuum gap along c, so "
        "more than one slab. Unset fix_bottom_layers."
    )


def test_fix_bottom_layers_may_fix_every_layer_of_the_slab_but_no_more() -> None:
    """D16: the MoS2 sheet has three atomic layers on the written cell (S, Mo,
    S), counted the way the writer counts them, so check() refuses a fourth
    instead of passing a count the writer cannot apply."""
    sheet = molybdenum_disulfide_monolayer()

    assert _fix_bottom_layers_findings(3, sheet) == ()
    assert _fix_bottom_layers_findings(4, sheet) == (
        Finding(
            code="relax.fix_bottom_layers_exceeds_layers",
            summary=_SUMMARY["relax.fix_bottom_layers_exceeds_layers"],
            message=(
                "fix_bottom_layers=4 exceeds the 3 atomic layers of the slab to "
                "be written. Set fix_bottom_layers to at most 3, or unset it."
            ),
            fields=("fix_bottom_layers",),
            remedies=({"fix_bottom_layers": None},),
        ),
    )


def test_fix_bottom_layers_unset_is_never_checked() -> None:
    assert _fix_bottom_layers_findings(None, graphite()) == ()


def test_the_fix_bottom_layers_gate_is_skipped_without_the_written_cell() -> None:
    assert check_all(relax=_relax_with_fix_bottom_layers(2)).ok


def test_a_blocked_written_cell_surfaces_once_via_the_generic_scan() -> None:
    report = check_all(
        relax=_relax_with_fix_bottom_layers(2),
        magnetic=Blocked(by="magnetic ordering undecided"),
    )

    assert report.blocking == _blocked("magnetic ordering undecided")


def _job(ntasks: int) -> Resolved[JobDecision]:
    decision = JobDecision(
        partition="scarf",
        nodes=1,
        ntasks=ntasks,
        ntasks_per_node=ntasks,
        walltime_h=168.0,
        max_seconds_by_step={"scf": 574560},
        memory_per_process_mb=12.5,
        memory_total_mb=900.0,
        account=None,
    )
    return Resolved(decision, Provenance(source="heuristic"))


def _parallel(
    npool: int, ndiag: int | None = None
) -> Resolved[ParallelisationDecision]:
    decision = ParallelisationDecision(npool=npool, ndiag=ndiag, kpoint_spin_pairs=64)
    return Resolved(decision, Provenance(source="human"))


def test_npool_dividing_ntasks_is_ok() -> None:
    report = check_all(job=_job(64), parallel=_parallel(8))

    assert report.ok


def test_npool_not_dividing_ntasks_blocks() -> None:
    """Regression for #52: this used to be only a warning, so a bad
    npool reached the SLURM script and failed only once compute was
    already allocated and running."""
    report = check_all(job=_job(64), parallel=_parallel(7))

    assert report.blocking == (
        Finding(
            code="parallelisation.npool_does_not_divide_ntasks",
            summary=_SUMMARY["parallelisation.npool_does_not_divide_ntasks"],
            message=(
                "npool=7 does not divide ntasks=64, and pw.x refuses that layout. "
                "Unset npool for the default, or set npool to a divisor of ntasks."
            ),
            fields=("npool", "ntasks"),
            remedies=({"npool": None},),
        ),
    )


def test_npool_check_is_unaffected_when_either_side_is_missing() -> None:
    assert check_all(job=_job(64)).ok
    assert check_all(parallel=_parallel(7)).ok
    assert check_all().ok


def test_npool_blocked_field_state_surfaces_via_the_generic_scan() -> None:
    report = check_all(parallel=Blocked(by="job resources undecided"))

    assert report.blocking == _blocked("job resources undecided")


def _bands(nbnd: int) -> Resolved[NbndDecision]:
    return Resolved(NbndDecision(nbnd=nbnd), Provenance(source="heuristic"))


@pytest.mark.parametrize(
    ("nbnd", "npool", "ndiag", "side", "largest"),
    [
        (1, 1, 4, 2, 1),  # s > nbnd: set_para_diag's startup abort
        (2, 1, 9, 3, 4),  # LiH, k_grid=[3,3,3], ndiag=9
        (2, 4, 16, 4, 4),  # LiH at the old default -npool 4 -ndiag 16
        (8, 1, 16, 4, 9),  # the C2-box layout, nbnd 8 on a 4x4 grid
        (9, 1, 16, 4, 9),  # nbnd == (s-1)^2: the last empty-column size
        (8, 1, 64, 8, 9),  # the H2O/N2 boxes: -npool 1 -ndiag 64
        (8, 4, 64, 4, 9),  # the grid is capped by 16 processes per pool
        (49, 1, 64, 8, 49),
    ],
)
def test_user_ndiag_whose_grid_cannot_distribute_the_bands_blocks(
    nbnd: int, npool: int, ndiag: int, side: int, largest: int
) -> None:
    """Regression for #133: pw.x stops at startup when the grid side s
    exceeds nbnd (set_para_diag), and leaves a process column without
    rows of a subspace matrix of size n <= (s-1)^2, which ELPA rejects
    and QE does not catch. Both used to pass check() and fail on SCARF."""
    report = check_all(
        job=_job(64), parallel=_parallel(npool, ndiag), nbnd=_bands(nbnd)
    )

    reason = _only(report).message
    assert f"ndiag={ndiag}" in reason
    assert f"{side}x{side}" in reason
    assert f"nbnd={nbnd}" in reason
    assert f"ndiag <= {largest}" in reason


def test_ndiag_reason_states_the_grid_the_bound_and_the_remedy() -> None:
    """The C2-box layout from #133: -npool 4 -ndiag 16 on 64 tasks."""
    report = check_all(job=_job(64), parallel=_parallel(4, 16), nbnd=_bands(8))

    assert report.blocking == (
        Finding(
            code="parallelisation.ndiag_grid_too_large",
            summary=_SUMMARY["parallelisation.ndiag_grid_too_large"],
            message=(
                "ndiag=16 gives a 4x4 diagonalization grid, which cannot "
                "distribute nbnd=8 bands (it needs nbnd > 9); pw.x would abort "
                "at startup or fail in the parallel eigensolver. Unset ndiag so "
                "pw.x chooses it from nbnd, or use ndiag <= 9."
            ),
            fields=("ndiag", "nbnd"),
            remedies=({"ndiag": None},),
        ),
    )


@pytest.mark.parametrize(
    ("nbnd", "npool", "ndiag"),
    [
        (2, 1, 4),  # s=2 needs nbnd > 1
        (10, 1, 16),  # s=4 needs nbnd > 9
        (50, 1, 64),  # s=8 needs nbnd > 49
        (2, 16, 64),  # 4 processes per pool: s=2
        (8, 1, 10),  # non-square ndiag runs a 3x3 grid
        (1, 1, 1),
    ],
)
def test_user_ndiag_whose_grid_distributes_the_bands_is_ok(
    nbnd: int, npool: int, ndiag: int
) -> None:
    report = check_all(
        job=_job(64), parallel=_parallel(npool, ndiag), nbnd=_bands(nbnd)
    )

    assert report.ok, _messages(report)


def test_unset_ndiag_never_blocks() -> None:
    report = check_all(job=_job(64), parallel=_parallel(1), nbnd=_bands(1))

    assert report.ok


def test_ndiag_check_needs_job_parallel_and_bands() -> None:
    assert check_all(parallel=_parallel(1, 64), nbnd=_bands(8)).ok
    assert check_all(job=_job(64), parallel=_parallel(1, 64)).ok
    assert check_all(job=_job(64), nbnd=_bands(8)).ok


def test_unresolved_bands_never_add_the_ndiag_reason() -> None:
    blocked = check_all(
        job=_job(64),
        parallel=_parallel(1, 64),
        nbnd=Blocked(by="electron count undecided"),
    )
    unavailable = check_all(
        job=_job(64),
        parallel=_parallel(1, 64),
        nbnd=Unavailable(reason="no valid band count"),
    )

    assert blocked.blocking == _blocked("electron count undecided")
    assert unavailable.ok


# #131: pw.x stops in setup when nbnd cannot hold every electron of a spin
# channel (QE 7.3 PW/src/setup.f90:349-356): nbnd >= NINT(nelec/2),
# NINT(nelup) and NINT(neldw), and NINT(nelec) for noncolin. The default
# never falls below these; a human nbnd or extra_bands can.
_TWO_SITE_IRON = Structure(
    Lattice.cubic(2.87), ["Fe", "Fe"], [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]]
)


def _band_check(
    nbnd: int,
    nelec: float,
    occupations=_FIXED,
    *,
    spin_polarized: bool = False,
    spin_orbit_enabled: bool = False,
    purpose: str = "scf",
):
    return check_all(
        occupations=occupations,
        magnetic=_magnetic(
            spin_polarized, _TWO_SITE_IRON, spin_orbit_enabled=spin_orbit_enabled
        ),
        electron_count=_electron_count(nelec),
        nbnd=_bands(nbnd),
        purpose=purpose,
    )


def test_too_few_spin_up_bands_for_the_pinned_moment_blocks() -> None:
    """The LiFePO4 deck from #131: tot_magnetization 16 on 192 electrons
    puts 104 in the spin-up channel, and 96 bands made pw.x stop with
    'too few spin up bands' after check() had passed."""
    report = _band_check(96, 192.0, _fixed(16.0), spin_polarized=True)

    assert report.blocking == (
        Finding(
            code="nbnd.too_few_bands",
            summary=_SUMMARY["nbnd.too_few_bands"],
            message=(
                "nbnd=96 cannot hold 104 spin-up electrons: pw.x stops in setup "
                "with 'too few spin up bands'. Unset nbnd and extra_bands for the "
                "default, or set nbnd to at least 104."
            ),
            fields=("nbnd", "extra_bands"),
            remedies=({"nbnd": None, "extra_bands": None},),
        ),
    )


def test_enough_bands_for_the_pinned_moment_pass() -> None:
    assert _band_check(104, 192.0, _fixed(16.0), spin_polarized=True).ok


def test_the_band_reason_names_pw_x_first_error_and_the_count_that_passes() -> None:
    """90 bands fail pw.x's first check, NINT(nelec/2) = 96, but only 104
    pass the spin-up one too."""
    report = _band_check(90, 192.0, _fixed(16.0), spin_polarized=True)

    reason = _only(report).message
    assert reason.startswith("nbnd=90 cannot hold 192 electrons, two per band")
    assert "'too few bands'" in reason
    assert "at least 104" in reason


def test_too_few_spin_down_bands_for_a_negative_moment_blocks() -> None:
    report = _band_check(6, 12.0, _fixed(-2.0), spin_polarized=True)

    reason = _only(report).message
    assert "'too few spin dw bands'" in reason
    assert "at least 7" in reason


def test_too_few_bands_for_the_electron_count_blocks() -> None:
    """nbnd=2 on 8 electrons passed check() and stopped pw.x with 'too few
    bands'."""
    report = _band_check(2, 8.0)

    reason = _only(report).message
    assert reason.startswith("nbnd=2 cannot hold")
    assert "'too few bands'" in reason
    assert "at least 4" in reason


def test_a_noncollinear_run_needs_a_band_per_electron() -> None:
    """Spinor bands hold one electron each (setup.f90:355-356)."""
    blocked = _band_check(13, 14.0, _SMEARING, spin_orbit_enabled=True)
    passed = _band_check(14, 14.0, _SMEARING, spin_orbit_enabled=True)

    reason = _only(blocked).message
    assert "'too few bands'" in reason
    assert "at least 14" in reason
    assert passed.ok


@pytest.mark.parametrize("purpose", ["scf", "relax", "vc-relax"])
def test_the_band_rule_names_pw_x_s_stop_on_a_step_with_an_scf_loop(
    purpose: str,
) -> None:
    report = _band_check(2, 8.0, purpose=purpose)

    assert _only(report).code == "nbnd.too_few_bands"
    assert "pw.x stops in setup with 'too few bands'" in _only(report).message


@pytest.mark.parametrize("purpose", ["nscf", "bands"])
def test_the_band_rule_holds_without_an_scf_loop_where_pw_x_does_not_stop(
    purpose: str,
) -> None:
    """An nscf step needs every occupied band too, to place the Fermi level,
    and a bands step to plot them, but pw.x checks the count only with lscf
    (QE 7.3 PW/src/setup.f90:349-358): the message used to say it stops."""
    report = _band_check(2, 8.0, purpose=purpose)

    assert report.blocking == (
        Finding(
            code="nbnd.too_few_bands",
            summary=_SUMMARY["nbnd.too_few_bands"],
            message=(
                "nbnd=2 cannot hold 8 electrons, two per band, so this "
                f"{purpose} step would leave occupied bands out; pw.x checks the "
                "band count only in a run with its own SCF loop. Unset nbnd and "
                "extra_bands for the default, or set nbnd to at least 4."
            ),
            fields=("nbnd", "extra_bands"),
            remedies=({"nbnd": None, "extra_bands": None},),
        ),
    )


def test_one_band_count_on_two_steps_is_one_finding_in_the_scf_step_s_words() -> None:
    """A flat nbnd sets a dos or band task's scf and later pw.x step alike:
    one count below the same floors, worded for each step, came back as two
    findings. The task's report keeps the scf step's, which names pw.x's
    stop; another count on the later step is a cause of its own."""
    scf = _band_check(2, 8.0, purpose="scf")
    same = _band_check(2, 8.0, purpose="bands")
    other = _band_check(3, 8.0, purpose="nscf")

    assert CheckReport(blocking=scf.blocking + same.blocking) == scf
    assert CheckReport(blocking=scf.blocking + other.blocking).blocking == (
        scf.blocking + other.blocking
    )


def test_a_blocked_nbnd_is_reported_once() -> None:
    report = check_all(
        occupations=_FIXED,
        magnetic=_magnetic(False, _TWO_SITE_IRON),
        electron_count=_electron_count(8.0),
        nbnd=Blocked(by="electron count undecided"),
    )

    assert report.blocking == _blocked("electron count undecided")


def test_the_band_rule_needs_occupations_and_the_electron_count() -> None:
    assert check_all(nbnd=_bands(2), electron_count=_electron_count(8.0)).ok
    assert check_all(nbnd=_bands(2), occupations=_FIXED).ok


# #118: any tot_magnetization gives a collinear run two Fermi energies (QE 7.3
# PW/src/input.f90:758), which a bands step reads from the scf's save and
# bands.x stops on (PP/src/bands.f90:114-116).


@pytest.mark.parametrize(
    ("occupations", "written"),
    [(_SMEARING, "2.5"), (_fixed(2.0), "2")],
    ids=["smearing", "fixed"],
)
def test_a_moment_on_a_collinear_bands_step_blocks(occupations, written) -> None:
    report = check_all(
        occupations=occupations, magnetic=_magnetic(True), purpose="bands"
    )

    assert report.blocking == (
        Finding(
            code="occupations.bands_x_refuses_tot_magnetization",
            summary=_SUMMARY["occupations.bands_x_refuses_tot_magnetization"],
            message=(
                f"A band task cannot pin tot_magnetization={written} on a "
                "collinear spin-polarized run: it gives the scf two Fermi "
                "energies, which the bands step inherits and bands.x stops on "
                "('The bands code with constrained magnetization has not been "
                "tested') once both pw.x steps have run. Set occupations=smearing "
                "and unset tot_magnetization."
            ),
            fields=("occupations", "tot_magnetization"),
            remedies=({"occupations": "smearing", "tot_magnetization": None},),
        ),
    )


def test_the_moment_rule_needs_a_collinear_moment_on_the_bands_step() -> None:
    """A noncollinear run takes no tot_magnetization (input.f90:761-762), a
    collinear one without a moment has one Fermi energy, and the scf step of
    the same run is not where bands.x stops."""
    unpinned = dataclasses.replace(_SMEARING.value, tot_magnetization=None)

    assert check_all(
        occupations=_SMEARING,
        magnetic=_magnetic(True, spin_orbit_enabled=True),
        purpose="bands",
    ).ok
    assert check_all(
        occupations=Resolved(unpinned, Provenance(source="heuristic")),
        magnetic=_magnetic(True),
        purpose="bands",
    ).ok
    assert check_all(occupations=_SMEARING, magnetic=_magnetic(True), purpose="scf").ok


def _path_pairs(kpoint_spin_pairs: int) -> Resolved[ParallelisationDecision]:
    decision = ParallelisationDecision(
        npool=1, ndiag=None, kpoint_spin_pairs=kpoint_spin_pairs
    )
    return Resolved(decision, Provenance(source="heuristic"))


def test_a_bands_step_above_pw_x_s_k_point_limit_blocks() -> None:
    """pw.x holds at most npk = 40000 k-points, counted after a collinear run
    doubles its list (QE 7.3 Modules/parameters.f90:16, PW/src/setup.f90:640),
    and a bands step runs every point of its path."""
    report = check_all(parallel=_path_pairs(40001), purpose="bands")

    assert report.blocking == (
        Finding(
            code="k_path.too_many_kpoints",
            summary=_SUMMARY["k_path.too_many_kpoints"],
            message=(
                "The band path gives the bands step 40001 k-point/spin pairs, "
                "more than the 40000 pw.x accepts: it stops in setup with 'too "
                "many k points'. Unset k_path_distance for the default, or set a "
                "larger one."
            ),
            fields=("k_path_distance",),
            remedies=({"k_path_distance": None},),
        ),
    )


def test_the_k_point_limit_admits_40000_and_reads_the_bands_step_only() -> None:
    assert check_all(parallel=_path_pairs(40000), purpose="bands").ok
    assert check_all(parallel=_path_pairs(40001), purpose="scf").ok
    blocked = check_all(parallel=Blocked(by="job undecided"), purpose="bands")
    assert blocked.blocking == _blocked("job undecided")


def _hubbard(projectors: str | None) -> Resolved[HubbardUDecision]:
    """A Hubbard U on Ni written with ``projectors``, or no U for ``None``,
    as ``advisors.hubbard_u`` decides them: no projectors without a U."""
    u_values = () if projectors is None else (HubbardU("Ni", "3d", 6.2, "table"),)
    return Resolved(
        HubbardUDecision(u_values=u_values, projectors=projectors),
        Provenance(source="heuristic"),
    )


_PHONON_PURPOSES = ("scf", "relax", "vc-relax")
"""The first steps of the phonon, relax-phonon and vc-relax-phonon tasks."""


@pytest.mark.parametrize("purpose", _PHONON_PURPOSES)
def test_a_hubbard_u_on_ortho_atomic_projectors_is_refused_in_a_phonon_task(
    purpose: str,
) -> None:
    """ph.x runs DFPT+U only with atomic projectors (QE 7.3
    PHonon/PH/phq_readin.f90:766-767), whichever pw.x step it reads."""
    report = with_phonon_findings(
        CheckReport(), purpose=purpose, hubbard=_hubbard("ortho-atomic")
    )

    assert report.blocking == (
        Finding(
            code="phonon.hubbard_projectors_unsupported",
            summary=_SUMMARY["phonon.hubbard_projectors_unsupported"],
            message=(
                "The Hubbard U on Ni is written with ortho-atomic projectors, but "
                "ph.x computes phonons with a Hubbard U only for atomic ones and "
                "stops with 'The phonon code for this Hubbard projectors type is not "
                "implemented'. Set hubbard_projectors=atomic, or "
                "hubbard_needs_correlation=false for no +U. A U value is tied to the "
                "projectors it was derived with, so the same U with atomic "
                "projectors is a different correction."
            ),
            fields=("hubbard_projectors", "hubbard_needs_correlation"),
            remedies=(
                {"hubbard_projectors": "atomic"},
                {"hubbard_needs_correlation": False},
            ),
        ),
    )


def test_atomic_projectors_or_no_hubbard_u_pass_in_a_phonon_task() -> None:
    for hubbard in (_hubbard("atomic"), _hubbard(None)):
        assert with_phonon_findings(CheckReport(), purpose="scf", hubbard=hubbard).ok


@pytest.mark.parametrize(
    "spin_polarized", [True, False], ids=["with-moments", "without-moments"]
)
def test_spin_orbit_coupling_with_a_hubbard_u_is_refused_in_a_phonon_task(
    spin_polarized: bool,
) -> None:
    """ph.x's DFPT+U arrays and projections hold one spinor component (QE 7.3
    PHonon/PH/allocate_phq.f90:166-167, dnsq_scf.f90:130). QE 7.5 stops on a
    magnetic noncollinear run (phq_readin.f90:777-778), but not on one
    without moments, as is_magnetic=non_magnetic with spin_orbit_coupling
    gives, which it would get wrong."""
    report = with_phonon_findings(
        CheckReport(),
        purpose="scf",
        hubbard=_hubbard("atomic"),
        magnetic=_magnetic(spin_polarized, spin_orbit_enabled=True),
    )

    assert report.blocking == (
        Finding(
            code="phonon.noncollinear_hubbard_unsupported",
            summary=_SUMMARY["phonon.noncollinear_hubbard_unsupported"],
            message=(
                "The phonon tasks cannot combine spin_orbit_coupling with the "
                "Hubbard U on Ni: ph.x computes phonons with a Hubbard U for "
                "collinear spins only, so a noncollinear run would stop or give "
                "wrong phonons. Set spin_orbit_coupling=false, or "
                "hubbard_needs_correlation=false for no +U."
            ),
            fields=("spin_orbit_coupling", "hubbard_needs_correlation"),
            remedies=(
                {"spin_orbit_coupling": False},
                {"hubbard_needs_correlation": False},
            ),
        ),
    )


def test_a_collinear_hubbard_u_or_spin_orbit_without_one_passes() -> None:
    assert with_phonon_findings(
        CheckReport(),
        purpose="scf",
        hubbard=_hubbard("atomic"),
        magnetic=_magnetic(True),
    ).ok
    assert with_phonon_findings(
        CheckReport(),
        purpose="scf",
        hubbard=_hubbard(None),
        magnetic=_magnetic(True, spin_orbit_enabled=True),
    ).ok


def test_spin_orbit_with_an_ortho_atomic_hubbard_u_names_both_causes() -> None:
    """Atomic projectors alone leave the spin-orbit refusal; no U clears both."""
    report = with_phonon_findings(
        CheckReport(),
        purpose="scf",
        hubbard=_hubbard("ortho-atomic"),
        magnetic=_magnetic(False, spin_orbit_enabled=True),
    )

    assert [finding.code for finding in report.blocking] == [
        "phonon.hubbard_projectors_unsupported",
        "phonon.noncollinear_hubbard_unsupported",
    ]


_PHONON_ISOLATED = Finding(
    code="phonon.isolated_boundary_unsupported",
    summary=_SUMMARY["phonon.isolated_boundary_unsupported"],
    message=(
        "isolation=isolated writes Martyna-Tuckerman, which ph.x does not "
        "implement: Quantum ESPRESSO 7.3's ph.x drops it, treating the molecule or "
        "cluster in the box as a periodic array of copies, and 7.5's applies it "
        "only in part. A molecule's vibrations need a Gamma-only calculation, ph.x "
        "at Gamma and then dynmat.x with asr='zero-dim', which the phonon tasks do "
        "not do."
    ),
    fields=("isolation",),
)


@pytest.mark.parametrize("purpose", _PHONON_PURPOSES)
def test_a_molecule_in_a_box_is_refused_in_a_phonon_task(purpose: str) -> None:
    """ph.x implements no nonperiodic boundary (QE 7.3 PHonon/PH/phonon.f90:
    36-41); 7.3 restores only the 2D flag from the save
    (PW/src/pw_restart_new.f90:1341-1345). No setting gives a molecule's
    vibrations, so there is no remedy."""
    report = with_phonon_findings(
        CheckReport(),
        purpose=purpose,
        boundary=_boundary("isolated"),
        magnetic=written_cell(carbon_pair_in_a_box()),
    )

    assert report.blocking == (_PHONON_ISOLATED,)


def test_isolated_on_a_periodic_cell_is_left_to_the_vacuum_rule() -> None:
    """There isolation=periodic is the remedy, which the vacuum rule offers."""
    boundary = _boundary("isolated", source="human")
    magnetic = written_cell(mc3d_42058_silicon())

    report = with_phonon_findings(
        check_all(boundary=boundary, magnetic=magnetic),
        purpose="scf",
        boundary=boundary,
        magnetic=magnetic,
    )

    assert [finding.code for finding in report.blocking] == [
        "boundary.isolated_needs_vacuum"
    ]


def test_an_isolated_vc_relax_phonon_gives_one_finding() -> None:
    """The vc-relax rule's advice, the relax task, does not help a phonon
    run; the phonon finding replaces it."""
    boundary = _boundary("isolated")
    magnetic = written_cell(carbon_pair_in_a_box())
    first = check_all(boundary=boundary, magnetic=magnetic, purpose="vc-relax")

    report = with_phonon_findings(
        first, purpose="vc-relax", boundary=boundary, magnetic=magnetic
    )

    assert [finding.code for finding in first.blocking] == [
        "boundary.isolated_forbids_vc_relax"
    ]
    assert report.blocking == (_PHONON_ISOLATED,)


@pytest.mark.parametrize("purpose", _PHONON_PURPOSES)
def test_a_periodic_molecule_in_a_box_is_refused_in_a_phonon_task(
    purpose: str,
) -> None:
    """Under isolation=periodic ph.x would compute a periodic array of copies
    of the molecule, whose phonons include the interactions between them, and
    a molecule has no phonon dispersion: a box is refused whatever its
    isolation, with no remedy, as under 'isolated'."""
    boundary = _boundary("periodic", source="human")
    magnetic = written_cell(carbon_pair_in_a_box())

    report = with_phonon_findings(
        check_all(boundary=boundary, magnetic=magnetic, purpose=purpose),
        purpose=purpose,
        boundary=boundary,
        magnetic=magnetic,
    )

    assert report.blocking == (
        Finding(
            code="phonon.isolated_boundary_unsupported",
            summary=_SUMMARY["phonon.isolated_boundary_unsupported"],
            message=(
                "A molecule or cluster in a box (vacuum along a, b and c) has no "
                "phonon dispersion, and with isolation=periodic ph.x would compute "
                "a periodic array of copies, whose phonons include the interactions "
                "between them. A molecule's vibrations need a Gamma-only "
                "calculation, ph.x at Gamma and then dynmat.x with asr='zero-dim', "
                "which the phonon tasks do not do."
            ),
            fields=("isolation",),
        ),
    )


def test_a_slab_isolation_on_a_box_gets_only_the_phonon_finding() -> None:
    """The 2D-truncation rule's remedy, isolation=periodic, leaves the box
    refused in a phonon task, so the phonon finding replaces it."""
    boundary = _boundary("slab", source="human")
    magnetic = written_cell(carbon_pair_in_a_box())
    first = check_all(boundary=boundary, magnetic=magnetic)

    report = with_phonon_findings(
        first, purpose="scf", boundary=boundary, magnetic=magnetic
    )

    assert [finding.code for finding in first.blocking] == [
        "boundary.slab_unsuited_to_2d_truncation"
    ]
    (finding,) = report.blocking
    assert (finding.code, finding.remedies) == (
        "phonon.isolated_boundary_unsupported",
        (),
    )
    assert "and with isolation=slab ph.x would compute a periodic array" in (
        finding.message
    )


@pytest.mark.parametrize("isolation", ["periodic", "slab", "isolated"])
def test_a_2d_cell_dofree_on_a_box_gets_only_the_phonon_finding(
    isolation: str,
) -> None:
    """The 2D cell constraint's refusal on a box advises the relax task,
    which does not help a phonon run, so in vc-relax-phonon the phonon
    finding replaces it, whatever the isolation."""
    boundary = _boundary(isolation, source="human")
    magnetic = written_cell(carbon_pair_in_a_box())
    relax = _vc_relax_with_cell_dofree("2Dxy")
    first = check_all(
        boundary=boundary, magnetic=magnetic, relax=relax, purpose="vc-relax"
    )

    report = with_phonon_findings(
        first, purpose="vc-relax", boundary=boundary, magnetic=magnetic, relax=relax
    )

    assert "relax.two_d_cell_dofree_needs_xy_frame" in [
        finding.code for finding in first.blocking
    ]
    assert [finding.code for finding in report.blocking] == [
        "phonon.isolated_boundary_unsupported"
    ]


@pytest.mark.parametrize(
    "build",
    [mc3d_42058_silicon, graphene_monolayer, carbon_chain],
    ids=lambda build: build.__name__,
)
def test_a_cell_with_vacuum_along_fewer_axes_than_a_box_passes(build) -> None:
    """Bulk, a slab and a wire, periodic along at least one lattice vector:
    ph.x computes their phonons under isolation=periodic."""
    report = with_phonon_findings(
        CheckReport(),
        purpose="scf",
        boundary=_boundary("periodic"),
        magnetic=written_cell(build()),
    )

    assert report.ok


def _occupations(occupations: str, tot_magnetization: float | None):
    """``occupations`` pinning ``tot_magnetization``, as requested."""
    smearing = occupations == "smearing"
    return Resolved(
        OccupationsDecision(
            occupations=occupations,
            smearing_type="cold" if smearing else None,
            degauss=0.01 if smearing else None,
            tot_magnetization=tot_magnetization,
        ),
        Provenance(source="human"),
    )


_TWO_FERMI_ENERGIES = (
    "gives the scf two Fermi energies, which ph.x refuses on smearing or "
    "tetrahedra: it stops with 'The phonon code with two fermi energies is not "
    "available for metals'. Unset tot_magnetization"
)


@pytest.mark.parametrize("occupations", ["smearing", "tetrahedra_opt"])
def test_a_pinned_moment_on_smearing_or_tetrahedra_is_refused(occupations: str) -> None:
    """Any tot_magnetization gives the scf two Fermi energies (QE 7.3
    PW/src/input.f90:758), which ph.x refuses with smearing or tetrahedra
    (PHonon/PH/phq_readin.f90:856-858). An integer moment of the electron
    count's parity runs on fixed occupations instead."""
    report = with_phonon_findings(
        CheckReport(),
        purpose="relax",
        occupations=_occupations(occupations, 2.0),
        magnetic=_magnetic(True),
        electron_count=_electron_count(16.0),
    )

    assert report.blocking == (
        Finding(
            code="phonon.pinned_moment_with_smearing",
            summary=_SUMMARY["phonon.pinned_moment_with_smearing"],
            message=(
                f"tot_magnetization=2 with occupations={occupations} "
                f"{_TWO_FERMI_ENERGIES}, or set occupations=fixed, which this "
                "integer moment of the electron count's parity allows."
            ),
            fields=("occupations", "tot_magnetization"),
            remedies=({"tot_magnetization": None}, {"occupations": "fixed"}),
        ),
    )


@pytest.mark.parametrize(
    ("tot_magnetization", "electron_count"),
    [(2.0, _electron_count(15.0)), (2.5, _electron_count(16.0)), (2.0, None)],
    ids=["odd-count", "non-integer-moment", "unknown-count"],
)
def test_fixed_occupations_are_offered_only_for_a_moment_they_run_with(
    tot_magnetization: float, electron_count
) -> None:
    """Fixed occupations need an integer moment of the electron count's
    parity (rule 2 of the gate), so the remedy is offered only for one."""
    report = with_phonon_findings(
        CheckReport(),
        purpose="scf",
        occupations=_occupations("smearing", tot_magnetization),
        magnetic=_magnetic(True),
        electron_count=electron_count,
    )

    (finding,) = report.blocking
    assert finding.remedies == ({"tot_magnetization": None},)
    assert finding.message == (
        f"tot_magnetization={tot_magnetization:g} with occupations=smearing "
        f"{_TWO_FERMI_ENERGIES}."
    )


def test_a_moment_on_fixed_occupations_or_smearing_without_one_passes() -> None:
    """A noncollinear run takes no tot_magnetization (QE 7.3
    PW/src/input.f90:761-762), so its moment is never written."""
    for occupations, magnetic in (
        (_occupations("fixed", 2.0), _magnetic(True)),
        (_occupations("smearing", None), _magnetic(True)),
        (_occupations("smearing", 2.0), _magnetic(True, spin_orbit_enabled=True)),
    ):
        report = with_phonon_findings(
            CheckReport(),
            purpose="scf",
            occupations=occupations,
            magnetic=magnetic,
            electron_count=_electron_count(16.0),
        )

        assert report.ok, occupations


def _alpha_uranium_q_grid(q_grid: tuple[int, int, int]):
    """The q record of a request ``q_grid`` on alpha-U's written cell."""
    return q_sampling(
        framed_magnetic_cell(alpha_uranium()), QSamplingHumanInput(q_grid=q_grid)
    )


@pytest.mark.parametrize(
    "q_grid", [(9, 8, 5), (4, 8, 4)], ids=["not-invariant", "unequal-mixed-axes"]
)
def test_a_q_grid_that_breaks_symmetry_is_refused(q_grid: tuple[int, int, int]) -> None:
    """The q record's refusal (advisors/q_sampling.py), worded with its
    cause: alpha-U's mirror maps 9x8x5 off itself, and 4x8x4, which ph.x
    accepts, would give a raised k-mesh that it maps off itself."""
    q = _alpha_uranium_q_grid(q_grid)

    report = with_phonon_findings(CheckReport(), purpose="scf", q_sampling=q)

    assert report.blocking == (
        Finding(
            code="phonon.q_grid_breaks_symmetry",
            summary=_SUMMARY["phonon.q_grid_breaks_symmetry"],
            message=f"{q.value.refusal.cause}. Unset q_grid for the default q-mesh.",
            fields=("q_grid",),
            remedies=({"q_grid": None},),
        ),
    )


def test_a_q_mesh_beyond_q2r_x_is_refused() -> None:
    """36x36x36 on alpha-U has 6517 irreducible q-points, and q2r.x reads at
    most 1024 dynamical matrices (QE 7.3 PHonon/PH/do_q2r.f90:138-139)."""
    q = _alpha_uranium_q_grid((36, 36, 36))

    report = with_phonon_findings(CheckReport(), purpose="scf", q_sampling=q)

    assert report.blocking == (
        Finding(
            code="phonon.too_many_q_points",
            summary=_SUMMARY["phonon.too_many_q_points"],
            message=(
                f"The phonon run would stop in q2r.x: {q.value.refusal.cause}. Unset "
                "q_grid and q_distance for the default q-mesh, or set a coarser one."
            ),
            fields=("q_grid", "q_distance"),
            remedies=({"q_grid": None, "q_distance": None},),
        ),
    )
    assert "6517 irreducible q-points" in report.blocking[0].message


def test_an_accepted_q_mesh_passes() -> None:
    q = _alpha_uranium_q_grid((8, 8, 4))

    assert with_phonon_findings(CheckReport(), purpose="scf", q_sampling=q).ok


def _alpha_uranium_fft_grid(first_step: str):
    """alpha-U's FFT-grid record at 480 Ry: pw.x's 40x45x64 fails ph.x's
    test, and the mirror that mixes b with a, which no operation exchanges,
    makes the cell fragile (tests/unit/test_advisors_fft_grid.py)."""
    cutoffs = Resolved(
        CutoffsDecision(ecutwfc_ry=60.0, ecutrho_ry=480.0), Provenance(source="human")
    )
    return fft_grid(framed_magnetic_cell(alpha_uranium()), cutoffs, first_step)


_FINAL_SCF = (
    "The vc-relax's final scf rebuilds that grid for the relaxed cell, so no grid "
    "written for ph.x reaches it. Use relax-phonon, which relaxes the atoms in the "
    "written cell and keeps a grid written for ph.x, or run the vc-relax task and "
    "then the phonon task on the relaxed structure."
)


def test_a_fragile_cell_is_refused_in_vc_relax_phonon() -> None:
    """A vc-relax's final scf rebuilds pw.x's own grid for the relaxed cell
    and drops nr1-nr3 (QE 7.3 PW/src/run_pwscf.f90:404-405), so no override
    gives ph.x a grid it accepts (PHonon/PH/phq_setup.f90:211-212)."""
    report = with_phonon_findings(
        CheckReport(), purpose="vc-relax", fft_grid=_alpha_uranium_fft_grid("vc-relax")
    )

    assert report.blocking == (
        Finding(
            code="phonon.vc_relax_fft_grid_unsupported",
            summary=_SUMMARY["phonon.vc_relax_fft_grid_unsupported"],
            message=(
                "vc-relax-phonon cannot run on this cell: pw.x's own FFT grid for "
                "it, 40x45x64, is not mapped onto itself by the symmetry operations "
                "pw.x keeps, which mix lattice vectors a and b, so ph.x would stop "
                f"with 'FFT grid incompatible with symmetry'. {_FINAL_SCF}"
            ),
            fields=("cell_dofree",),
        ),
    )


def test_a_fragile_cell_whose_grid_ph_x_accepts_is_refused_too() -> None:
    """pw.x's own grid can pass on the input cell, as MnPS3's does at some
    strains, and fail on the relaxed one: the refusal tests the structure."""
    decision = FftGridDecision(
        pw_grid=(75, 75, 288),
        compatible=True,
        written=None,
        fragile_axes=(("b", "a"),),
        fragile=True,
    )

    report = with_phonon_findings(
        CheckReport(),
        purpose="vc-relax",
        fft_grid=Resolved(decision, Provenance(source="heuristic")),
    )

    assert _only(report).message == (
        "vc-relax-phonon cannot run on this cell: the symmetry operations pw.x "
        "keeps mix lattice vectors a and b, so a strained cell can give pw.x's own "
        "FFT grid counts on which ph.x stops with 'FFT grid incompatible with "
        f"symmetry'. {_FINAL_SCF}"
    )


@pytest.mark.parametrize("purpose", ["scf", "relax"])
def test_a_fragile_cell_passes_where_the_written_grid_reaches_ph_x(
    purpose: str,
) -> None:
    """The scf and the fixed-cell relaxation write nr1-nr3, and pw.x keeps
    them into the save ph.x reads."""
    fft = _alpha_uranium_fft_grid(purpose)

    assert fft.value.written == (45, 45, 64)
    assert with_phonon_findings(CheckReport(), purpose=purpose, fft_grid=fft).ok


def test_a_cell_that_is_not_fragile_passes_in_vc_relax_phonon() -> None:
    cutoffs = Resolved(
        CutoffsDecision(ecutwfc_ry=30.0, ecutrho_ry=240.0), Provenance(source="human")
    )
    fft = fft_grid(framed_magnetic_cell(mc3d_42058_silicon()), cutoffs, "vc-relax")

    assert with_phonon_findings(CheckReport(), purpose="vc-relax", fft_grid=fft).ok


_PHONON_FIX_BOTTOM_LAYERS = Finding(
    code="phonon.fix_bottom_layers_unsupported",
    summary=_SUMMARY["phonon.fix_bottom_layers_unsupported"],
    message=(
        "fix_bottom_layers=1 pins atoms in the relaxation, so they keep leftover "
        "forces, while ph.x computes the phonons as second derivatives at an "
        "equilibrium, where every force is zero. Unset fix_bottom_layers."
    ),
    fields=("fix_bottom_layers",),
    remedies=({"fix_bottom_layers": None},),
)


@pytest.mark.parametrize(
    "relax",
    [
        Resolved(RelaxOptions(fix_bottom_layers=1), Provenance(source="human")),
        Resolved(VcRelaxOptions(fix_bottom_layers=1), Provenance(source="human")),
    ],
    ids=["relax-phonon", "vc-relax-phonon"],
)
def test_fix_bottom_layers_is_refused_in_the_phonon_relaxations(relax) -> None:
    """DFPT takes second derivatives at an equilibrium, which pinned atoms
    are not at; the slab passes the slab rules."""
    purpose = "vc-relax" if isinstance(relax.value, VcRelaxOptions) else "relax"
    magnetic = written_cell(molybdenum_disulfide_monolayer())

    report = with_phonon_findings(
        check_all(relax=relax, magnetic=magnetic, purpose=purpose),
        purpose=purpose,
        relax=relax,
        magnetic=magnetic,
    )

    assert report.blocking == (_PHONON_FIX_BOTTOM_LAYERS,)


@pytest.mark.parametrize(
    ("count", "structure", "replaced"),
    [
        (1, graphite, "relax.fix_bottom_layers_needs_slab"),
        (4, molybdenum_disulfide_monolayer, "relax.fix_bottom_layers_exceeds_layers"),
    ],
    ids=["no-slab", "too-many-layers"],
)
def test_fix_bottom_layers_the_slab_rules_refuse_gives_one_finding(
    count: int, structure, replaced: str
) -> None:
    """The slab rules' remedy, unsetting fix_bottom_layers, is the phonon
    finding's, which replaces them."""
    relax = _relax_with_fix_bottom_layers(count)
    magnetic = written_cell(structure())
    first = check_all(relax=relax, magnetic=magnetic, purpose="relax")

    report = with_phonon_findings(
        first, purpose="relax", relax=relax, magnetic=magnetic
    )

    assert [finding.code for finding in first.blocking] == [replaced]
    assert [finding.code for finding in report.blocking] == [
        "phonon.fix_bottom_layers_unsupported"
    ]


def test_a_relaxation_without_fix_bottom_layers_passes() -> None:
    assert with_phonon_findings(
        CheckReport(), purpose="relax", relax=_relax_with_fix_bottom_layers(None)
    ).ok


def _first_step_occupations(
    occupations: str,
    source: str = "heuristic",
    tot_magnetization: float | None = None,
):
    """``occupations``, chosen by the is_metal rule (``heuristic``) or set by
    the request (``human``), with the request's moment, if any."""
    smearing = occupations == "smearing"
    return Resolved(
        OccupationsDecision(
            occupations=occupations,
            smearing_type="cold" if smearing else None,
            degauss=0.01 if smearing else None,
            tot_magnetization=tot_magnetization,
        ),
        Provenance.from_field_sources({"occupations": source}),
    )


def _metallicity(value: str | None, source: str = "ml"):
    """The is_metal fact, ``value`` from ``source``, or for ``None`` the
    heuristic's answer to a compound with a non-metal element."""
    if value is None:
        return Unavailable(reason="composition contains non-metal elements (O)")
    return Resolved(value, Provenance(source=source))


def _spin(
    structure: Structure,
    magnetism: str = "magnetic",
    *,
    hubbard: Resolved[HubbardUDecision] | None = None,
    **settings: object,
):
    """``structure``'s magnetic decision as the service makes it
    (``magnetic_cell``, then ``magnetic_config``): ``magnetism`` is the
    is_magnetic fact, ``hubbard`` the Hubbard decision and ``settings`` the
    request's magnetic overrides."""
    cell = magnetic_cell(
        structure,
        Resolved(magnetism, Provenance(source="heuristic")),
        MagneticConfigHumanInput(**settings),
        hubbard=hubbard,
    )
    return magnetic_config(cell)


def _metallicity_summary(chosen: str) -> str:
    """The rule-17 summary of a run on ``chosen`` occupations (#223)."""
    stake = "an insulator loses its LO-TO splitting"
    if chosen == "fixed":
        return (
            "Confirm whether this structure is a metal: the requested "
            "occupations=fixed cannot run as it stands, and a metal needs smearing "
            f"instead, where {stake}."
        )
    return (
        "Confirm whether this structure is a metal: its composition is not "
        f"all-metallic, and it runs on occupations={chosen}, where {stake}."
    )


def _metallicity_finding(report: CheckReport) -> Finding:
    """``report``'s metallicity finding, after checking that it names only
    catalogued fields and remedies and that each remedy changes only its
    fields (module docstring of checks.py)."""
    (finding,) = (
        finding
        for finding in report.blocking
        if finding.code == "phonon.metallicity_unconfirmed"
    )
    (catalogued,) = (entry for entry in FINDING_CATALOGUE if entry.code == finding.code)
    assert [field for field in catalogued.fields if field in finding.fields] == list(
        finding.fields
    )
    for remedy in finding.remedies:
        assert remedy in catalogued.remedies
        assert set(remedy) <= set(finding.fields)
    return finding


_RUTILE = written_cell(rutile_titanium_dioxide())
_RUTILE_ELECTRONS = _electron_count(48.0)
_MOS2_MONOLAYER = _spin(molybdenum_disulfide_monolayer())
_MOS2_ELECTRONS = _electron_count(26.0)
_TITANIUM_NITRIDE = written_cell(rock_salt("Ti", "N", 4.24))
_TITANIUM_NITRIDE_ELECTRONS = _electron_count(17.0)
_PH_X_ON_SMEARING = (
    "ph.x treats a run on smearing or tetrahedra as a metal: it computes the "
    "dielectric constant and the Born effective charges, which give a polar "
    "insulator its LO-TO splitting, only with fixed occupations, and at q = 0 it "
    "shifts the Fermi energy by the induced charge divided by the density of "
    "states at the Fermi energy, which with smearing is nearly zero when the Fermi "
    "energy lies in a gap, so an insulator's response can diverge at Gamma."
)
_CLASSIFIER_THRESHOLD = (
    "The metallicity classifier is tuned to miss few metals, which k-point sampling "
    "needs, so it calls many insulators metals, and composition alone cannot tell "
    "them apart."
)
_NO_MOMENT = (
    "fixed occupations on a collinear spin-polarized run need an integer "
    "tot_magnetization of the electron count's parity, and this run has none"
)
_ODD_COUNT = (
    "without spin polarization fixed occupations cannot fill its odd electron "
    "count, which leaves a band half filled, as in a metal"
)
_METAL = {"is_metal": "metal"}


def _opening(occupations: str = "smearing") -> str:
    return (
        "The phonon tasks need this structure on fixed occupations, or confirmed as "
        f"a metal: it runs on occupations={occupations}, and its composition is not "
        f"all-metallic, so it may be an insulator. {_PH_X_ON_SMEARING}"
    )


def _keeps(occupations: str = "smearing") -> str:
    return f"; for a metal set is_metal=metal, which keeps occupations={occupations}."


def _magnetic_insulator(setting: str = "is_metal=non_metal") -> str:
    return (
        f"For a magnetic insulator set {setting} with tot_magnetization, its "
        "integer moment in Bohr magnetons per cell"
    )


def _odd_insulator(setting: str = "is_metal=non_metal") -> str:
    return (
        f"For a magnetic insulator set {setting} with spin_polarized=true and, on "
        "a collinear run, its integer moment as tot_magnetization, odd like the "
        "electron count"
    )


def _held(obstacle: str) -> dict[str, str]:
    """Why each is_metal fact leaves a run that ``obstacle`` keeps off fixed
    occupations on smearing: undecided, classified a non-metal or set to one
    by the user."""
    return {
        "undecided": (
            f"{_CLASSIFIER_THRESHOLD} Setting is_metal=non_metal alone would keep "
            f"occupations=smearing: {obstacle}."
        ),
        "classified-non-metal": (
            "It is classified as a non-metal, but it stays on occupations=smearing: "
            f"{obstacle}."
        ),
        "user-non-metal": (
            f"With is_metal=non_metal it stays on occupations=smearing: {obstacle}."
        ),
    }


_FACTS = {
    "undecided": _metallicity(None),
    "classified-non-metal": _metallicity("non_metal"),
    "user-non-metal": _metallicity("non_metal", "human"),
}
"""An is_metal fact that is not the user's metal, by the ids of ``_held``."""


@pytest.mark.parametrize("purpose", _PHONON_PURPOSES)
@pytest.mark.parametrize(
    "is_metal",
    [_metallicity(None), _metallicity("metal"), _metallicity("metal", "llm")],
    ids=["undecided", "classified-metal", "llm-metal"],
)
def test_a_composition_that_is_not_all_metallic_on_smearing_needs_an_answer(
    purpose: str, is_metal
) -> None:
    """Rutile TiO2 on smearing, which the is_metal rule gives a metal and an
    undecided structure: ph.x treats the run as a metal. It computes the
    dielectric constant and the Born effective charges only with fixed
    occupations (QE 7.3 PHonon/PH/prepare_q.f90:141-160), and at q = 0 it
    shifts the Fermi energy by the induced charge over the density of states
    at the Fermi energy (PHonon/PH/solve_linter.f90:228, :430-437;
    LR_Modules/efermi_shift.f90:98-99), nearly zero in an insulator's gap. The
    classifier calls TiO2 a metal, so no answer but the user's is taken, and
    with its even electron count is_metal=non_metal runs it on fixed
    occupations: the remedies are the two answers."""
    report = with_phonon_findings(
        CheckReport(),
        purpose=purpose,
        occupations=_first_step_occupations("smearing"),
        is_metal=is_metal,
        electron_count=_RUTILE_ELECTRONS,
        magnetic=_RUTILE,
    )

    assert report.blocking == (
        Finding(
            code="phonon.metallicity_unconfirmed",
            summary=_metallicity_summary("smearing"),
            message=(
                f"{_opening()} {_CLASSIFIER_THRESHOLD} For an insulator set "
                f"is_metal=non_metal, which runs it on fixed occupations{_keeps()}"
            ),
            fields=("is_metal",),
            remedies=({"is_metal": "non_metal"}, _METAL),
        ),
    )
    _metallicity_finding(report)


@pytest.mark.parametrize(
    ("spin", "electrons", "moment"),
    [
        (
            lambda: _spin(rock_salt("Ni", "O", 4.17), magnetic_ordering="afm"),
            48.0,
            None,
        ),
        (
            lambda: _spin(molybdenum_disulfide_monolayer(), tot_magnetization=2),
            26.0,
            2.0,
        ),
    ],
    ids=["compensated", "requested-moment"],
)
def test_a_collinear_run_with_a_moment_fixed_occupations_take_needs_is_metal_only(
    spin, electrons: float, moment: float | None
) -> None:
    """NiO on its antiferromagnetic ordering, the 4-atom AFM-II cell, which
    is compensated by symmetry, takes the 0 of fixed occupations with its even
    electron count, and a MoS2 monolayer the requested 2 Bohr magnetons of its
    count's parity, which on smearing is refused on its own: is_metal=non_metal
    puts either on fixed occupations, so the message names no moment."""
    magnetic = spin()
    report = with_phonon_findings(
        CheckReport(),
        purpose="scf",
        occupations=_first_step_occupations("smearing", tot_magnetization=moment),
        is_metal=_metallicity("metal"),
        electron_count=_electron_count(electrons),
        magnetic=magnetic,
    )

    finding = _metallicity_finding(report)
    assert magnetic.value.spin_mode == "collinear"
    assert finding.remedies == ({"is_metal": "non_metal"}, _METAL)
    assert finding.message == (
        f"{_opening()} {_CLASSIFIER_THRESHOLD} For an insulator set "
        f"is_metal=non_metal, which runs it on fixed occupations{_keeps()}"
    )


_NICKEL_OXIDE = _spin(rock_salt("Ni", "O", 4.17))


@pytest.mark.parametrize("fact", list(_FACTS))
@pytest.mark.parametrize(
    ("magnetic", "electrons", "hubbard"),
    [
        (_MOS2_MONOLAYER, _MOS2_ELECTRONS, None),
        (_NICKEL_OXIDE, _electron_count(24.0), _hubbard("atomic")),
    ],
    ids=["monolayer", "nickel-oxide-even-shell"],
)
def test_a_collinear_run_without_a_moment_needs_one_or_no_spin_polarization(
    magnetic, electrons, hubbard, fact: str
) -> None:
    """A MoS2 monolayer and ferromagnetic NiO, which the is_magnetic
    heuristic spin-polarizes (Mo4+ is d2, Ni2+ d8): a collinear
    spin-polarized run takes fixed occupations only with an integer
    tot_magnetization of the electron count's parity (QE 7.3
    PW/src/input.f90:764-781), so is_metal=non_metal, the user's or the
    classifier's, keeps the smearing, on which ph.x diverged at Gamma for
    ZnO. The message names the moment, which only the user can give, and
    offers is_magnetic=non_magnetic for a material without moments: its spin
    polarization follows that fact, NiO's U acts on an even d count, which
    leaves it so, and the 26 and 24 electrons fill whole bands without spin
    polarization."""
    report = with_phonon_findings(
        CheckReport(),
        purpose="relax",
        occupations=_first_step_occupations("smearing"),
        is_metal=_FACTS[fact],
        electron_count=electrons,
        magnetic=magnetic,
        hubbard=hubbard,
    )

    assert report.blocking == (
        Finding(
            code="phonon.metallicity_unconfirmed",
            summary=_metallicity_summary("smearing"),
            message=(
                f"{_opening()} {_held(_NO_MOMENT)[fact]} {_magnetic_insulator()}; "
                "for one without magnetic moments set is_metal=non_metal and "
                f"is_magnetic=non_magnetic{_keeps()}"
            ),
            fields=("is_metal", "is_magnetic", "tot_magnetization"),
            remedies=(
                {"is_metal": "non_metal", "is_magnetic": "non_magnetic"},
                _METAL,
            ),
        ),
    )
    _metallicity_finding(report)


_MANGANESE_U = Resolved(
    HubbardUDecision(
        u_values=(HubbardU("Mn", "3d", 3.9, "table"),), projectors="atomic"
    ),
    Provenance(source="heuristic"),
)


@pytest.mark.parametrize(
    ("magnetic", "hubbard", "electrons", "fact", "moment"),
    [
        (
            _spin(rock_salt("Mn", "O", 4.445, primitive=False)),
            _MANGANESE_U,
            84.0,
            "user-non-metal",
            None,
        ),
        (
            _spin(
                rock_salt("Mn", "O", 4.445, primitive=False),
                "non_magnetic",
                hubbard=_MANGANESE_U,
            ),
            _MANGANESE_U,
            84.0,
            "undecided",
            None,
        ),
        (
            _spin(molybdenum_disulfide_monolayer(), tot_magnetization=2.5),
            None,
            26.0,
            "classified-non-metal",
            2.5,
        ),
        (_spin(uranium_nitride()), None, 19.0, "undecided", None),
    ],
    ids=[
        "manganese-oxide-u",
        "manganese-oxide-odd-shell",
        "requested-moment",
        "odd-uranium-nitride",
    ],
)
def test_no_spin_polarization_is_offered_where_is_magnetic_would_not_give_it(
    magnetic, hubbard, electrons: float, fact: str, moment: float | None
) -> None:
    """Collinear runs on smearing that is_magnetic=non_magnetic would not put
    on fixed occupations: ferromagnetic MnO, set to a non-metal, with a U on
    its d5 shell, an odd count, which keeps a run spin-polarized whatever
    is_magnetic says, so its 84 electrons stay spin-polarized; MnO
    spin-polarized by that U over a non-magnetic answer; a MoS2 monolayer
    with a requested tot_magnetization, which the message names, whose spin
    the request decides; and UN, whose 19 electrons cannot fill whole bands
    without spin polarization. The message names the moment, and the only
    remedy is is_metal=metal."""
    report = with_phonon_findings(
        CheckReport(),
        purpose="scf",
        occupations=_first_step_occupations("smearing", tot_magnetization=moment),
        is_metal=_FACTS[fact],
        electron_count=_electron_count(electrons),
        magnetic=magnetic,
        hubbard=hubbard,
    )

    finding = _metallicity_finding(report)
    obstacle = (
        _NO_MOMENT
        if moment is None
        else _NO_MOMENT.replace(
            "and this run has none", f"which tot_magnetization={moment:g} is not"
        )
    )
    assert magnetic.value.spin_mode == "collinear"
    assert (finding.fields, finding.remedies) == (
        ("is_metal", "tot_magnetization"),
        (_METAL,),
    )
    assert finding.message == (
        f"{_opening()} {_held(obstacle)[fact]} {_magnetic_insulator()}{_keeps()}"
    )


@pytest.mark.parametrize("fact", list(_FACTS))
def test_an_odd_electron_count_without_spin_polarization_needs_a_metal(
    fact: str,
) -> None:
    """Rock-salt TiN, 17 electrons without spin polarization: fixed
    occupations fill doubly occupied bands (QE 7.3 PW/src/iweights.f90),
    which leave one half filled, so is_metal=non_metal keeps the smearing. A
    magnetic insulator would need spin polarization and its moment, which the
    message names, so the only remedy is is_metal=metal."""
    report = with_phonon_findings(
        CheckReport(),
        purpose="vc-relax",
        occupations=_first_step_occupations("smearing"),
        is_metal=_FACTS[fact],
        electron_count=_TITANIUM_NITRIDE_ELECTRONS,
        magnetic=_TITANIUM_NITRIDE,
    )

    assert report.blocking == (
        Finding(
            code="phonon.metallicity_unconfirmed",
            summary=_metallicity_summary("smearing"),
            message=(
                f"{_opening()} {_held(_ODD_COUNT)[fact]} {_odd_insulator()}{_keeps()}"
            ),
            fields=("is_metal", "spin_polarized", "tot_magnetization"),
            remedies=(_METAL,),
        ),
    )
    _metallicity_finding(report)


@pytest.mark.parametrize("non_metal", [False, True], ids=["undecided", "non-metal"])
@pytest.mark.parametrize("occupations", ["smearing", "tetrahedra_opt"])
def test_occupations_the_request_sets_need_occupations_fixed_for_an_insulator(
    occupations: str, non_metal: bool
) -> None:
    """is_metal does not change occupations the request sets, so rutile's
    insulator remedy is occupations=fixed, whose even electron count fixed
    occupations fill, whether or not the user set is_metal=non_metal."""
    report = with_phonon_findings(
        CheckReport(),
        purpose="relax",
        occupations=_first_step_occupations(occupations, source="human"),
        is_metal=_FACTS["user-non-metal" if non_metal else "undecided"],
        electron_count=_RUTILE_ELECTRONS,
        magnetic=_RUTILE,
    )

    assert report.blocking == (
        Finding(
            code="phonon.metallicity_unconfirmed",
            summary=_metallicity_summary(occupations),
            message=(
                f"{_opening(occupations)} The request sets occupations={occupations}, "
                "which is_metal does not change. For an insulator set "
                f"occupations=fixed{_keeps(occupations)}"
            ),
            fields=("is_metal", "occupations"),
            remedies=({"occupations": "fixed"}, _METAL),
        ),
    )
    _metallicity_finding(report)


_REQUESTED = {
    "monolayer": (
        "smearing",
        _MOS2_MONOLAYER,
        26.0,
        _NO_MOMENT,
        (
            f"{_magnetic_insulator('occupations=fixed')}; for one without magnetic "
            "moments set occupations=fixed and is_magnetic=non_magnetic"
        ),
        ("is_metal", "occupations", "is_magnetic", "tot_magnetization"),
        ({"occupations": "fixed", "is_magnetic": "non_magnetic"}, _METAL),
    ),
    "odd-count": (
        "tetrahedra_opt",
        _TITANIUM_NITRIDE,
        17.0,
        _ODD_COUNT,
        _odd_insulator("occupations=fixed"),
        ("is_metal", "occupations", "spin_polarized", "tot_magnetization"),
        (_METAL,),
    ),
}
"""Per case: the requested occupations, the run's spin, its electron count,
why occupations=fixed alone would be refused, what an insulator sets, and
the finding's fields and remedies."""


@pytest.mark.parametrize("case", list(_REQUESTED))
def test_requested_occupations_that_fixed_occupations_cannot_replace_say_why(
    case: str,
) -> None:
    """occupations=fixed alone would be refused on a collinear MoS2 monolayer
    without a moment, and on TiN's odd count: the message says why, and the
    insulator remedy adds is_magnetic=non_magnetic where that gives fixed
    occupations."""
    occupations, magnetic, electrons, obstacle, insulator, fields, remedies = (
        _REQUESTED[case]
    )
    report = with_phonon_findings(
        CheckReport(),
        purpose="scf",
        occupations=_first_step_occupations(occupations, source="human"),
        is_metal=_metallicity(None),
        electron_count=_electron_count(electrons),
        magnetic=magnetic,
    )

    assert report.blocking == (
        Finding(
            code="phonon.metallicity_unconfirmed",
            summary=_metallicity_summary(occupations),
            message=(
                f"{_opening(occupations)} The request sets occupations={occupations}, "
                "which is_metal does not change, and setting occupations=fixed alone "
                f"would be refused: {obstacle}. {insulator}{_keeps(occupations)}"
            ),
            fields=fields,
            remedies=remedies,
        ),
    )
    _metallicity_finding(report)


_REQUESTED_MONOLAYER_MOMENT = _spin(
    molybdenum_disulfide_monolayer(), tot_magnetization=2.5
)
_REFUSED_FIXED = {
    "monolayer": (
        _MOS2_MONOLAYER,
        26.0,
        None,
        "occupations.fixed_needs_tot_magnetization",
        _NO_MOMENT,
        (
            f"{_magnetic_insulator('occupations=fixed')}; for one without magnetic "
            "moments set occupations=fixed and is_magnetic=non_magnetic"
        ),
        "for a metal set is_metal=metal and occupations=smearing",
        ("is_metal", "occupations", "is_magnetic", "tot_magnetization"),
        (
            {"occupations": "fixed", "is_magnetic": "non_magnetic"},
            {"occupations": "smearing", "is_metal": "metal"},
        ),
    ),
    "odd-count": (
        _TITANIUM_NITRIDE,
        17.0,
        None,
        "occupations.fixed_needs_even_electron_count",
        _ODD_COUNT,
        _odd_insulator("occupations=fixed"),
        "for a metal set is_metal=metal and occupations=smearing",
        ("is_metal", "occupations", "spin_polarized", "tot_magnetization"),
        ({"occupations": "smearing", "is_metal": "metal"},),
    ),
    "requested-moment": (
        _REQUESTED_MONOLAYER_MOMENT,
        26.0,
        2.5,
        "occupations.fixed_needs_integer_tot_magnetization",
        _NO_MOMENT.replace(
            "and this run has none", "which tot_magnetization=2.5 is not"
        ),
        _magnetic_insulator("occupations=fixed"),
        (
            "for a metal set is_metal=metal and occupations=smearing, and unset "
            "tot_magnetization, which ph.x refuses on smearing"
        ),
        ("is_metal", "occupations", "tot_magnetization"),
        (
            {
                "occupations": "smearing",
                "is_metal": "metal",
                "tot_magnetization": None,
            },
        ),
    ),
}
"""Per case: the run's spin, its electron count and requested moment, the
occupations refusal the metallicity one replaces, why fixed occupations
cannot run, what an insulator and a metal set, and the finding's fields and
remedies."""


@pytest.mark.parametrize("fact", list(_FACTS))
@pytest.mark.parametrize("case", list(_REFUSED_FIXED))
def test_a_requested_fixed_the_run_cannot_take_needs_an_insulator_or_a_metal(
    case: str, fact: str
) -> None:
    """occupations=fixed on a collinear MoS2 monolayer without a moment or
    with a requested 2.5 Bohr magnetons, and on TiN's odd count, which fixed
    occupations cannot take: the occupations rule's remedy, smearing, runs a
    composition that is not all-metallic in a phonon task only as a confirmed
    metal, so the metallicity refusal replaces it, whatever is_metal says
    short of the user's metal. It says why fixed occupations cannot run and
    what an insulator sets, and the metal's remedy sets smearing too, with
    the requested moment unset, which ph.x refuses on smearing."""
    (
        magnetic,
        electrons,
        moment,
        replaced,
        obstacle,
        insulator,
        metal,
        fields,
        remedies,
    ) = _REFUSED_FIXED[case]
    occupations = _first_step_occupations(
        "fixed", source="human", tot_magnetization=moment
    )
    first = check_all(
        occupations=occupations,
        magnetic=magnetic,
        electron_count=_electron_count(electrons),
        purpose="scf",
    )

    report = with_phonon_findings(
        first,
        purpose="scf",
        occupations=occupations,
        is_metal=_FACTS[fact],
        electron_count=_electron_count(electrons),
        magnetic=magnetic,
    )

    assert [finding.code for finding in first.blocking] == [replaced]
    assert report.blocking == (
        Finding(
            code="phonon.metallicity_unconfirmed",
            summary=_metallicity_summary("fixed"),
            message=(
                "The phonon tasks need this structure on fixed occupations, or "
                "confirmed as a metal: the request sets occupations=fixed, which "
                "this run cannot take, and its composition is not all-metallic, so "
                f"it may be an insulator. {_PH_X_ON_SMEARING} Fixed occupations are "
                f"refused here: {obstacle}. {insulator}; {metal}."
            ),
            fields=fields,
            remedies=remedies,
        ),
    )
    _metallicity_finding(report)


_USER_METAL = _metallicity("metal", "human")
_UNPINNED_ON_SMEARING = (
    " A phonon task also needs tot_magnetization unset with occupations=smearing: "
    "ph.x refuses the two Fermi energies a pinned moment gives there."
)


@pytest.mark.parametrize(
    ("magnetic", "is_metal", "electrons", "moment", "code"),
    [
        (
            _spin(written_bcc_iron(), tot_magnetization=2.5),
            _metallicity("metal"),
            16.0,
            2.5,
            "occupations.fixed_needs_integer_tot_magnetization",
        ),
        (
            _spin(written_bcc_iron(), tot_magnetization=3),
            _metallicity("metal"),
            16.0,
            3.0,
            "occupations.fixed_tot_magnetization_parity",
        ),
        (
            _REQUESTED_MONOLAYER_MOMENT,
            _USER_METAL,
            26.0,
            2.5,
            "occupations.fixed_needs_integer_tot_magnetization",
        ),
    ],
    ids=["all-metallic", "all-metallic-parity", "user-metal"],
)
def test_a_moment_fixed_occupations_cannot_take_is_unset_with_smearing(
    magnetic, is_metal, electrons: float, moment: float, code: str
) -> None:
    """bcc Fe, every element a metal, with a requested 2.5 or 3 Bohr
    magnetons, which fixed occupations of its 16 electrons cannot take, and a
    MoS2 monolayer with 2.5 that the user confirms a metal: the occupations
    rule's refusal stands in a phonon task, but its remedy, smearing, would
    keep the moment, which ph.x refuses on smearing (QE 7.3
    PHonon/PH/phq_readin.f90:856-858), so there it unsets the moment too."""
    occupations = _first_step_occupations(
        "fixed", source="human", tot_magnetization=moment
    )
    first = check_all(
        occupations=occupations,
        magnetic=magnetic,
        electron_count=_electron_count(electrons),
        purpose="relax",
    )

    report = with_phonon_findings(
        first,
        purpose="relax",
        occupations=occupations,
        is_metal=is_metal,
        electron_count=_electron_count(electrons),
        magnetic=magnetic,
    )

    (refused,) = first.blocking
    assert (refused.code, refused.remedies) == (code, ({"occupations": "smearing"},))
    assert report.blocking == (
        dataclasses.replace(
            refused,
            message=f"{refused.message}{_UNPINNED_ON_SMEARING}",
            remedies=({"occupations": "smearing", "tot_magnetization": None},),
        ),
    )


def test_without_a_requested_moment_the_occupations_refusal_stands_as_it_is() -> None:
    """bcc Fe on occupations=fixed without a moment: the occupations rule's
    remedy, smearing, keeps no moment and needs no answer on a composition
    with every element a metal, so a phonon task keeps its refusal."""
    magnetic = _spin(written_bcc_iron())
    occupations = _first_step_occupations("fixed", source="human")
    first = check_all(
        occupations=occupations,
        magnetic=magnetic,
        electron_count=_electron_count(16.0),
        purpose="vc-relax",
    )

    report = with_phonon_findings(
        first,
        purpose="vc-relax",
        occupations=occupations,
        is_metal=_metallicity("metal"),
        electron_count=_electron_count(16.0),
        magnetic=magnetic,
    )

    assert [finding.code for finding in first.blocking] == [
        "occupations.fixed_needs_tot_magnetization"
    ]
    assert report.blocking == first.blocking


@pytest.mark.parametrize(
    ("occupations", "is_metal", "magnetic", "electrons"),
    [
        (_first_step_occupations("fixed"), _metallicity(None), _RUTILE, 48.0),
        (
            _first_step_occupations("smearing"),
            _metallicity("metal"),
            written_cell(written_bcc_iron()),
            16.0,
        ),
        (_first_step_occupations("smearing"), _USER_METAL, _RUTILE, 48.0),
        (_first_step_occupations("smearing"), _USER_METAL, _MOS2_MONOLAYER, 26.0),
        (_first_step_occupations("smearing"), _USER_METAL, _TITANIUM_NITRIDE, 17.0),
        (
            _first_step_occupations("tetrahedra_opt", source="human"),
            _USER_METAL,
            _RUTILE,
            48.0,
        ),
    ],
    ids=[
        "fixed-occupations",
        "all-metallic",
        "user-metal",
        "user-metal-collinear",
        "user-metal-odd-count",
        "user-metal-requested-occupations",
    ],
)
def test_fixed_occupations_an_all_metallic_composition_or_a_user_metal_pass(
    occupations, is_metal, magnetic, electrons: float
) -> None:
    """Fixed occupations give ph.x the dielectric response; bcc Fe has no
    non-metal element; and the user's is_metal=metal is taken on any run."""
    for purpose in _PHONON_PURPOSES:
        assert with_phonon_findings(
            CheckReport(),
            purpose=purpose,
            occupations=occupations,
            is_metal=is_metal,
            electron_count=_electron_count(electrons),
            magnetic=magnetic,
        ).ok, purpose


def test_a_blocked_phonon_record_surfaces_its_root_cause() -> None:
    """A blocked record of the phonon steps, given or named, reaches the
    report once, as its root cause, after the first step's findings."""
    first = check_all(job=_job(64), parallel=_parallel(7))

    report = with_phonon_findings(
        first,
        Blocked(by="no written cell"),
        purpose="scf",
        q_sampling=Blocked(by="the q-mesh is not symmetric"),
        fft_grid=Blocked(by="no written cell"),
    )

    assert report.blocking == (
        *first.blocking,
        *_blocked("no written cell", "the q-mesh is not symmetric"),
    )


def test_a_phonon_task_with_nothing_to_refuse_keeps_the_first_step_s_report() -> None:
    first = check_all(job=_job(64), parallel=_parallel(7))

    assert with_phonon_findings(first, purpose="scf").blocking == first.blocking
    assert with_phonon_findings(CheckReport(), purpose="vc-relax").ok


def test_every_finding_code_is_catalogued_once() -> None:
    codes = [finding.code for finding in FINDING_CATALOGUE]

    assert len(codes) == len(set(codes))
    assert "advice.blocked" in codes


@pytest.mark.parametrize("finding", FINDING_CATALOGUE, ids=lambda f: f.code)
def test_every_remedy_is_an_override_the_request_accepts(finding: Finding) -> None:
    """#151: a remedy is a complete override patch; a None value clears that
    override. One task reads every key of it, and every value fits its
    setting."""
    catalogue = bindings()
    for remedy in finding.remedies:
        tasks = [
            task
            for task in get_args(CalcTask)
            if all(task in catalogue[key].tasks for key in remedy)
        ]
        assert tasks, remedy
        build_overrides(remedy, task=tasks[0])


@pytest.mark.parametrize("finding", FINDING_CATALOGUE, ids=lambda f: f.code)
def test_a_finding_names_settings_and_remedies_only_change_them(
    finding: Finding,
) -> None:
    """``fields`` are capabilities keys, so the Workbench can show the finding
    at each control it concerns, and a remedy changes only those."""
    document = capabilities()
    keys = {setting["key"] for setting in document["settings"]} | {
        fact["key"] for fact in document["facts"]
    }

    assert set(finding.fields) <= keys
    for remedy in finding.remedies:
        assert set(remedy) <= set(finding.fields)
    assert bool(finding.fields) == (finding.code != "advice.blocked")


def test_a_finding_document_is_the_json_every_transport_returns() -> None:
    report = _band_check(2, 8.0)

    assert _only(report).to_document() == {
        "code": "nbnd.too_few_bands",
        "fields": ["nbnd", "extra_bands"],
        "message": _only(report).message,
        "remedies": [{"nbnd": None, "extra_bands": None}],
        "summary": _SUMMARY["nbnd.too_few_bands"],
    }


def test_a_cartesian_cell_constraint_on_a_turned_slab_is_cleared_not_set() -> None:
    """A slab turned into pw.x's frame under isolation=slab: cell_dofree=all
    would leave the 2D-truncation finding in place, so the remedy clears the
    override and the default ('2Dxy' for a slab) resolves both."""
    report = check_all(
        boundary=_boundary("slab", source="human"),
        relax=_vc_relax_with_cell_dofree("z"),
        magnetic=_framed(rotated_about_x(graphene_monolayer(), 30.0)),
        purpose="vc-relax",
    )

    assert [finding.code for finding in report.blocking] == [
        "relax.slab_vc_relax_needs_2d_cell_dofree",
        "relax.cartesian_cell_dofree_on_rotated_cell",
    ]
    assert report.blocking[1].remedies == ({"cell_dofree": None},)


def test_every_fully_relativistic_table_is_norm_conserving() -> None:
    """ph.x stops on PAW in a noncollinear magnetic run (QE 7.3
    PHonon/PH/phq_readin.f90:806-807), so the phonon tasks would need a
    refusal for it; none is reachable while spin-orbit coupling, which takes
    a fully relativistic table, only finds PseudoDojo norm-conserving ones."""
    tables = [table for table in load_tables().values() if table.relativistic == "full"]

    assert tables
    for table in tables:
        assert table.provider == "pseudodojo", table.id
        assert table.upstream_table.startswith("nc-fr-"), table.id


def test_every_table_functional_is_one_ph_x_computes_phonons_for() -> None:
    """ph.x stops on meta-GGA and hybrid functionals (QE 7.3
    PHonon/PH/phq_readin.f90:793-797). The written input sets no input_dft, so
    pw.x and ph.x take the functional of the table's pseudopotentials."""
    functionals = {table.functional for table in load_tables().values()}

    assert functionals <= {"LDA", "PBE", "PBEsol"}


def test_no_occupations_value_is_bloechl_tetrahedra() -> None:
    """ph.x stops on tetrahedra with the Bloechl correction, 'DFPT with the
    Blochl correction is not implemented' (QE 7.3
    PHonon/PH/phq_readin.f90:955-956); tetrahedra_opt runs."""
    assert "tetrahedra" not in get_args(Occupations)
    assert "tetrahedra_opt" in get_args(Occupations)


@pytest.mark.parametrize("method", ["ts", "mbd"])
def test_no_dispersion_ph_x_lacks_can_be_requested(method: str) -> None:
    """ph.x stops on Tkatchenko-Scheffler dispersion (QE 7.3
    PHonon/PH/phq_readin.f90:788-789) and has no term for many-body
    dispersion in the dynamical matrix; D3(BJ) is the one method offered."""
    with pytest.raises(ValidationError):
        VdwMethodHumanInput(method=method)
