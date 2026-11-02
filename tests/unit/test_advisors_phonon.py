"""The phonon tasks' ph.x, q2r.x and matdyn.x settings and the notices of a
phonon run (#215): defaults and request values, the bounds ph.x checks, each
notice on its own condition, the acoustic-sum-rule fallback against one
task's memory, loto_2d, the phonon DOS mesh, and the dispersion path matdyn.x
reads. How matdyn.x expands that path and where it lands on Gamma are in
``tests/physics/test_phonon_dispersion.py``."""

from __future__ import annotations

import dataclasses

import pytest
from pydantic import ValidationError
from pymatgen.core import Lattice, Structure
from support import (
    INTERNAL_TEXT,
    carbon_pair_in_a_box,
    framed_magnetic_cell,
    geometry_facts,
    graphene_monolayer,
    mc3d_42058_silicon,
    phosphorene,
    rutile_titanium_dioxide,
    written_afm_nickel_oxide,
    written_boron_nitride_monolayer,
    written_cell,
    written_magnetic_cell,
    written_sodium_chloride,
)

from goldilocks_core.advisors.boundary import BoundaryFacts
from goldilocks_core.advisors.hubbard_u import HubbardU, HubbardUDecision
from goldilocks_core.advisors.k_path import KPathDecision, KPathHumanInput, k_path
from goldilocks_core.advisors.occupations import OccupationsDecision
from goldilocks_core.advisors.phonon import (
    LOOSE_FORCE_THRESHOLD_WARNING,
    NO_DISPERSION,
    PHONON_CITATIONS,
    WARNING_CATALOGUE,
    PhononDosHumanInput,
    PhononHumanInput,
    Q2rDecision,
    Q2rHumanInput,
    dispersion_path,
    phonon_dos_settings,
    phonon_notices,
    phonon_settings,
    q2r_settings,
)
from goldilocks_core.resolution import (
    Blocked,
    Provenance,
    Resolved,
    Unavailable,
    Warning,
)


def _resolved(value: object, source: str = "heuristic") -> Resolved[object]:
    return Resolved(value, Provenance(source=source))


def _occupations(occupations: str = "fixed") -> Resolved[OccupationsDecision]:
    smearing = occupations == "smearing"
    decision = OccupationsDecision(
        occupations=occupations,
        smearing_type="cold" if smearing else None,
        degauss=0.01 if smearing else None,
    )
    return Resolved(
        decision, Provenance.from_field_sources({"occupations": "heuristic"})
    )


def _notices(
    first_step: str = "relax",
    *,
    occupations: Resolved[OccupationsDecision] | None = None,
    structure: Structure | None = None,
    vacuum_axes: tuple[str, ...] = (),
    isolation: str = "periodic",
    spin_polarized: bool = False,
    spin_orbit: bool = False,
    hubbard: HubbardUDecision | None = None,
    d3: bool = False,
) -> tuple[Warning, ...]:
    """The notices of a relax-phonon run of rutile TiO2, bulk, periodic,
    non-magnetic, without +U or D3 and on fixed occupations, which raises
    none, with one condition changed."""
    magnetic = written_cell(structure or rutile_titanium_dioxide())
    magnetic = _resolved(
        dataclasses.replace(
            magnetic.value,
            spin_polarized=spin_polarized,
            spin_orbit_enabled=spin_orbit,
        )
    )
    dimensionality = "2d" if vacuum_axes else "3d"
    return phonon_notices(
        first_step,
        occupations or _occupations(),
        _resolved(geometry_facts(dimensionality, vacuum_axes)),
        _resolved(BoundaryFacts(isolation)),
        magnetic,
        _resolved(hubbard or HubbardUDecision()),
        d3=d3,
    )


def _codes(notices: tuple[Warning, ...]) -> list[str]:
    return [notice.code for notice in notices]


_NICKEL_OXIDE_WITH_U = {
    "structure": written_afm_nickel_oxide(),
    "spin_polarized": True,
    "hubbard": HubbardUDecision(
        u_values=(HubbardU("Ni", "3d", 6.2, "table"),), projectors="atomic"
    ),
}
"""AFM NiO, collinear, with the table's U on Ni and atomic projectors."""


def test_the_ph_x_defaults_are_the_balanced_protocol_s_with_its_note() -> None:
    """aiida-quantumespresso's balanced ph protocol: Quantum ESPRESSO's own
    defaults are 1e-12, 0.7 and 4."""
    state = phonon_settings()

    assert state.ok
    decision = state.value
    assert (decision.tr2_ph, decision.alpha_mix, decision.nmix_ph) == (1e-18, 0.4, 8)
    assert decision.warnings == ()
    assert state.source == "heuristic"
    assert state.provenance.field_sources == {
        "tr2_ph": "heuristic",
        "alpha_mix": "heuristic",
        "nmix_ph": "heuristic",
    }
    assert "aiida-quantumespresso's ph protocol" in state.provenance.source_note
    assert state.provenance.citations == PHONON_CITATIONS
    assert PHONON_CITATIONS == (
        "S. P. Huber et al., npj Comput. Mater. 7, 136 (2021)",
        "S. Baroni et al., Rev. Mod. Phys. 73, 515 (2001)",
    )


def test_request_values_are_used_as_given_and_read_human() -> None:
    state = phonon_settings(PhononHumanInput(tr2_ph=1e-16, alpha_mix=0.7, nmix_ph=4))

    decision = state.value
    assert (decision.tr2_ph, decision.alpha_mix, decision.nmix_ph) == (1e-16, 0.7, 4)
    assert state.source == "human"
    assert set(state.provenance.field_sources.values()) == {"human"}
    assert state.provenance.source_note is None
    assert state.provenance.citations == ()


def test_one_request_value_leaves_the_others_at_the_protocol() -> None:
    state = phonon_settings(PhononHumanInput(alpha_mix=0.3))

    assert (state.value.tr2_ph, state.value.alpha_mix, state.value.nmix_ph) == (
        1e-18,
        0.3,
        8,
    )
    assert state.provenance.field_sources == {
        "tr2_ph": "heuristic",
        "alpha_mix": "human",
        "nmix_ph": "heuristic",
    }
    assert state.source == "human"
    assert state.provenance.citations == PHONON_CITATIONS


def test_the_notices_are_the_phonon_record_s_warnings() -> None:
    notices = _notices("scf", d3=True)

    assert phonon_settings(notices=notices).value.warnings == notices


@pytest.mark.parametrize(
    ("bag", "setting"),
    [
        (PhononHumanInput, {"tr2_ph": 0.0}),
        (PhononHumanInput, {"alpha_mix": 1.5}),
        (PhononHumanInput, {"alpha_mix": -0.1}),
        (PhononHumanInput, {"nmix_ph": 0}),
        (Q2rHumanInput, {"asr": "all"}),
        (PhononDosHumanInput, {"dos_q_distance": 0.0}),
    ],
)
def test_a_value_outside_a_setting_s_bounds_is_refused(bag, setting) -> None:
    """ph.x stops unless tr2_ph > 0 and 0 <= alpha_mix <= 1 (QE 7.3
    phq_readin.f90:409-416); nmix_ph mixes at least one earlier iteration,
    and of matdyn.x's acoustic sum rules these tasks offer crystal and
    simple."""
    with pytest.raises(ValidationError):
        bag(**setting)


def test_the_bounds_themselves_are_accepted() -> None:
    bag = PhononHumanInput(alpha_mix=1.0, nmix_ph=1)

    assert (bag.alpha_mix, bag.nmix_ph) == (1.0, 1)
    assert PhononHumanInput(alpha_mix=0.0).alpha_mix == 0.0


def test_a_fixed_relaxation_of_a_bulk_oxide_raises_no_notice() -> None:
    assert _notices() == ()


@pytest.mark.parametrize(
    ("first_step", "codes"),
    [
        ("scf", ["phonon.relax_first"]),
        ("relax", []),
        ("vc-relax", ["phonon.vc_relax_input_cell"]),
    ],
)
def test_the_first_step_decides_the_relaxation_notices(
    first_step: str, codes: list[str]
) -> None:
    """The phonon task computes phonons at the written geometry; the
    vc-relax-phonon task sizes its meshes on the input cell."""
    assert _codes(_notices(first_step)) == codes


def test_the_relaxation_notice_asks_for_the_same_projectors() -> None:
    (notice,) = _notices("scf")

    assert "hubbard_projectors" in notice.message
    assert "relax-phonon" in notice.message
    assert notice.level == "info"


def test_the_input_cell_notice_says_where_the_path_s_vertices_move() -> None:
    """vc-relax-phonon's dispersion path is built on the input cell too:
    matdyn.x applies its vertices' crystal coordinates to the relaxed cell's
    reciprocal vectors, which keeps them special points except in the lattice
    types whose special points depend on the axis ratios and angles."""
    (notice,) = _notices("vc-relax")

    for term in (
        "dispersion path",
        "crystal coordinates",
        "matdyn.x",
        "BCT, ORCF, ORCI, ORCC, RHL, MCL and MCLC",
        "centred-rectangular or oblique layers",
        "Setyawan-Curtarolo subtypes",
    ):
        assert term in notice.message, term
    assert not INTERNAL_TEXT.findall(notice.message)


def test_a_fixed_periodic_slab_gets_the_2d_lo_to_warning() -> None:
    """Its non-analytic term would be the 3D one, which depends on the
    vacuum width."""
    notices = _notices(structure=written_boron_nitride_monolayer(), vacuum_axes=("c",))

    assert _codes(notices) == ["phonon.slab_lo_to_needs_2d_truncation"]
    assert "isolation=slab" in notices[0].message


@pytest.mark.parametrize(
    "case",
    [{"isolation": "slab"}, {"occupations": _occupations("smearing")}],
    ids=["2d-truncation", "smearing"],
)
def test_no_lo_to_warning_with_2d_truncation_or_without_fixed_occupations(
    case,
) -> None:
    notices = _notices(
        structure=written_boron_nitride_monolayer(), vacuum_axes=("c",), **case
    )

    assert notices == ()


@pytest.mark.parametrize(
    ("spin_polarized", "codes"),
    [(True, ["phonon.magnetic_noncollinear_experimental"]), (False, [])],
    ids=["magnetic", "non-magnetic"],
)
def test_only_magnetic_spin_orbit_runs_get_the_experimental_warning(
    spin_polarized: bool, codes: list[str]
) -> None:
    """Quantum ESPRESSO's PHonon examples call the magnetic spin-orbit case
    experimental; a non-magnetic one (fcc Pt) is not."""
    notices = _notices(spin_polarized=spin_polarized, spin_orbit=True)

    assert _codes(notices) == codes


def test_a_collinear_magnet_gets_no_spin_orbit_warning() -> None:
    assert _notices(spin_polarized=True) == ()


def test_a_hubbard_u_gets_the_dfpt_u_warning() -> None:
    notices = _notices(**_NICKEL_OXIDE_WITH_U)

    assert _codes(notices) == ["phonon.hubbard_experimental"]
    assert notices[0].level == "warning"


@pytest.mark.parametrize(("d3", "codes"), [(True, ["phonon.d3_two_body"]), (False, [])])
def test_only_a_d3_run_gets_the_two_body_notice(d3: bool, codes: list[str]) -> None:
    """d3hess.x's Hessian is two-body only, so the first step writes
    dftd3_threebody = .false. with D3."""
    notices = _notices(d3=d3)

    assert _codes(notices) == codes
    if d3:
        assert "dftd3_threebody = .false." in notices[0].message


def test_unresolved_facts_raise_no_notice_of_their_own() -> None:
    """A blocked record blocks the run on its own; the notices that read
    it are left out rather than guessed."""
    blocked = Blocked(by="pseudopotential table sssp is not installed")

    notices = phonon_notices(
        "scf", blocked, blocked, blocked, blocked, blocked, d3=False
    )

    assert _codes(notices) == ["phonon.relax_first"]


def test_the_catalogue_holds_every_notice_and_the_relax_warning() -> None:
    """The force-threshold warning is carried by the relax record."""
    by_code = {warning.code: warning for warning in WARNING_CATALOGUE}

    assert by_code["phonon.loose_force_threshold"] == LOOSE_FORCE_THRESHOLD_WARNING
    assert (
        LOOSE_FORCE_THRESHOLD_WARNING.level,
        LOOSE_FORCE_THRESHOLD_WARNING.category,
    ) == (
        "warning",
        "relax",
    )
    raised = [
        *_notices("scf", d3=True, **_NICKEL_OXIDE_WITH_U),
        *_notices("vc-relax"),
        *_notices(structure=written_boron_nitride_monolayer(), vacuum_axes=("c",)),
        *_notices(spin_polarized=True, spin_orbit=True),
    ]
    for notice in raised:
        catalogued = by_code[notice.code]
        assert (catalogued.level, catalogued.category) == (notice.level, "phonon")


def _q2r(isolation: str = "periodic", human: Q2rHumanInput | None = None):
    return q2r_settings(_resolved(BoundaryFacts(isolation)), human)


def test_asr_defaults_to_simple_with_its_note() -> None:
    """'simple' corrects the on-site force constants at every q, where the
    FFT-grid violation sits; 'crystal' corrects it at Gamma only, which gave
    bcc Li a spurious Gamma-N instability (#219)."""
    state = _q2r()

    assert state.ok
    assert state.value == Q2rDecision(asr="simple", loto_2d=False)
    assert state.provenance.field_sources == {"asr": "heuristic"}
    assert "Default asr 'simple'" in state.provenance.source_note
    assert state.provenance.derived_from == ("boundary",)


@pytest.mark.parametrize("asr", ["crystal", "simple"])
def test_a_request_asr_is_used_as_given(asr: str) -> None:
    state = _q2r(human=Q2rHumanInput(asr=asr))

    assert state.value.asr == asr
    assert state.provenance.field_sources == {"asr": "human"}
    assert state.provenance.source_note is None
    assert state.source == "human"


@pytest.mark.parametrize(
    ("isolation", "loto_2d"),
    [("slab", True), ("periodic", False), ("isolated", False)],
)
def test_loto_2d_follows_the_slab_boundary(isolation: str, loto_2d: bool) -> None:
    """With QE's 2D Coulomb truncation q2r.x and matdyn.x take the 2D
    non-analytic term (rigid.f90:129-137)."""
    assert _q2r(isolation).value.loto_2d is loto_2d


def test_q2r_is_blocked_by_an_unresolved_boundary() -> None:
    reason = "dimensionality classification does not support disordered structures"

    state = q2r_settings(Blocked(by=reason))

    assert isinstance(state, Blocked)
    assert state.root_cause() == reason


@pytest.mark.parametrize(
    ("cell", "mesh"),
    [
        (lambda: framed_magnetic_cell(mc3d_42058_silicon()), (21, 21, 21)),
        (lambda: framed_magnetic_cell(graphene_monolayer()), (30, 30, 1)),
    ],
    ids=["silicon", "graphene"],
)
def test_the_dos_mesh_is_0_10_per_angstrom_on_the_written_cell(cell, mesh) -> None:
    """The dos task's nscf spacing, through kmesh: one division along a
    vacuum axis."""
    state = phonon_dos_settings(cell())

    assert state.ok
    assert state.value.mesh == mesh
    assert (state.value.dos_q_distance, state.value.delta_e) == (0.1, 1.0)
    assert state.source == "heuristic"
    assert state.provenance.field_sources == {"dos_q_distance": "heuristic"}
    assert "0.10" in state.provenance.source_note


def test_a_request_dos_q_distance_is_used_as_given() -> None:
    state = phonon_dos_settings(
        framed_magnetic_cell(mc3d_42058_silicon()),
        PhononDosHumanInput(dos_q_distance=0.2),
    )

    assert state.value.mesh == (11, 11, 11)
    assert state.value.dos_q_distance == 0.2
    assert state.provenance.field_sources == {"dos_q_distance": "human"}
    assert state.provenance.source_note is None


def test_the_dos_mesh_is_blocked_by_an_unresolved_cell() -> None:
    state = phonon_dos_settings(Blocked(by="no compatible pseudopotential table"))

    assert isinstance(state, Blocked)


def _route(decision: KPathDecision) -> str:
    return " | ".join(
        "-".join(vertex.label for vertex in branch.vertices)
        for branch in decision.branches
    )


def _q2r_record(*, loto_2d: bool = False) -> Resolved[Q2rDecision]:
    return _resolved(Q2rDecision(asr="simple", loto_2d=loto_2d))


def _nacl() -> Resolved[object]:
    return written_magnetic_cell(written_sodium_chloride())


def _dispersion(
    cell: Resolved[object] | None = None,
    occupations: str = "fixed",
    *,
    loto_2d: bool = False,
    vacuum_axes: tuple[str, ...] = (),
    distance: float | None = None,
):
    """The dispersion path of ``cell``, written NaCl by default, on fixed
    occupations without loto_2d: a run on which matdyn.x adds the
    non-analytic term."""
    return dispersion_path(
        cell or _nacl(),
        _resolved(geometry_facts("2d" if vacuum_axes else "3d", vacuum_axes)),
        _occupations(occupations),
        _q2r_record(loto_2d=loto_2d),
        KPathHumanInput(k_path_distance=distance),
    )


def test_gamma_inside_a_branch_ends_one_branch_and_starts_the_next() -> None:
    """NaCl on fixed occupations without loto_2d: its interior Gamma is
    listed twice, ending K-Gamma and starting Gamma-L, one point more than
    the band path; the 48 steps into Gamma already land on it, and the
    record keeps the band path's table, notices and citations."""
    cell = _nacl()
    band = k_path(cell)

    state = _dispersion(cell)

    decision = state.value
    assert _route(band.value) == "Gamma-X-W-K-Gamma-L-U-W-L-K | U-X"
    assert _route(decision) == "Gamma-X-W-K-Gamma | Gamma-L-U-W-L-K | U-X"
    assert [branch.steps for branch in decision.branches] == [
        (45, 23, 16, 48),
        (39, 28, 16, 32, 28),
        (16,),
    ]
    assert decision.n_kpoints == band.value.n_kpoints + 1 == 294
    unsplit = dataclasses.replace(
        decision, branches=band.value.branches, n_kpoints=band.value.n_kpoints
    )
    assert unsplit == band.value
    provenance = state.provenance
    assert provenance.derived_from == ("magnetic", "occupations", "q2r")
    assert provenance.field_sources == {"k_path_distance": "heuristic"}
    assert provenance.citations == band.provenance.citations
    assert provenance.source_note.startswith(band.provenance.source_note)
    assert "listed twice" in provenance.source_note
    assert not INTERNAL_TEXT.findall(provenance.source_note)


@pytest.mark.parametrize(
    ("cell", "settings"),
    [
        (_nacl, {"occupations": "smearing"}),
        (_nacl, {"occupations": "smearing", "distance": 0.024492}),
        (_nacl, {"occupations": "tetrahedra_opt"}),
        (
            lambda: framed_magnetic_cell(phosphorene()),
            {"loto_2d": True, "vacuum_axes": ("c",)},
        ),
    ],
    ids=["smearing", "smearing-49-steps-into-gamma", "tetrahedra", "loto_2d"],
)
def test_without_the_non_analytic_term_the_dispersion_is_the_band_path(
    cell, settings
) -> None:
    """On smearing or tetrahedra ph.x computes no effective charges (QE 7.3
    PHonon/PH/prepare_q.f90:139-162), and under loto_2d matdyn.x skips its
    q = 0 block, so an interior Gamma (NaCl's, and phosphorene's Y-Gamma-S)
    needs no second point, and a segment into Gamma keeps its count: NaCl's
    K-Gamma keeps its 49 steps at k_path_distance 0.024492."""
    written = cell()
    band = k_path(written, KPathHumanInput(k_path_distance=settings.get("distance")))

    state = _dispersion(written, **settings)

    assert "Gamma" in [
        vertex.label
        for branch in band.value.branches
        for vertex in branch.vertices[1:-1]
    ]
    assert state.value == band.value
    assert state.provenance.source_note == band.provenance.source_note
    assert state.provenance.derived_from == ("magnetic", "occupations", "q2r")


def test_a_segment_into_gamma_takes_the_fewest_steps_that_land_on_it() -> None:
    """At k_path_distance 0.024492 NaCl's K-Gamma takes 49 steps, and
    fl(fl(1/49) 49) < 1 leaves its last point about 1e-16 off Gamma: the
    dispersion takes 50, the fewest from 49 that land on Gamma, and splits
    there as before."""
    band = k_path(_nacl(), KPathHumanInput(k_path_distance=0.024492)).value

    state = _dispersion(distance=0.024492)

    assert band.branches[0].steps == (46, 23, 17, 49, 40, 29, 17, 33, 29)
    assert [branch.steps for branch in state.value.branches] == [
        (46, 23, 17, 50),
        (40, 29, 17, 33, 29),
        (17,),
    ]
    assert state.value.n_kpoints == band.n_kpoints + 2 == 304
    assert state.value.k_path_distance == 0.024492
    assert state.provenance.field_sources == {"k_path_distance": "human"}
    assert "lands on Gamma exactly" in state.provenance.source_note
    assert "bands.yaml" not in state.provenance.source_note


def test_raising_a_count_alone_changes_the_record_and_its_note() -> None:
    """The hBN monolayer's path ends at Gamma, so nothing splits, but at
    k_path_distance 0.034422 its K-Gamma takes 49 steps: the dispersion
    raises them to 50 and says so."""
    cell = written_magnetic_cell(written_boron_nitride_monolayer())
    band = k_path(cell, KPathHumanInput(k_path_distance=0.034422)).value

    state = _dispersion(cell, vacuum_axes=("c",), distance=0.034422)

    (branch,) = state.value.branches
    assert band.branches[0].steps == (42, 25, 49)
    assert branch.vertices == band.branches[0].vertices
    assert branch.steps == (42, 25, 50)
    assert (state.value.n_kpoints, band.n_kpoints) == (118, 117)
    assert "lands on Gamma exactly" in state.provenance.source_note


def test_a_molecule_in_a_box_has_no_dispersion() -> None:
    """Vacuum along a, b and c: the record is unavailable, not blocked by
    the band path's own refusal of a box."""
    state = dispersion_path(
        framed_magnetic_cell(carbon_pair_in_a_box()),
        _resolved(geometry_facts("molecule", ("a", "b", "c"))),
        _occupations(),
        _q2r_record(),
    )

    assert isinstance(state, Unavailable)
    assert state.reason == NO_DISPERSION


@pytest.mark.parametrize("unresolved", ["cell", "occupations", "q2r"])
def test_an_unresolved_input_blocks_the_dispersion(unresolved: str) -> None:
    blocked = Blocked(by="pseudopotential table sssp is not installed")
    inputs = {
        "cell": _nacl(),
        "geometry": _resolved(geometry_facts("3d")),
        "occupations": _occupations(),
        "q2r": _q2r_record(),
        unresolved: blocked,
    }

    state = dispersion_path(**inputs)

    assert isinstance(state, Blocked)
    assert state.root_cause() == blocked.root_cause()


def test_an_unresolved_geometry_is_not_read() -> None:
    """Only the box test reads the written cell's vacuum facts; the path
    takes the vacuum from the cell itself."""
    state = dispersion_path(
        _nacl(),
        Unavailable(reason="dimensionality classification failed"),
        _occupations(),
        _q2r_record(),
    )

    assert state.ok
    assert state.value.n_kpoints == 294


def test_a_disordered_cell_is_blocked_by_q2r_before_its_path() -> None:
    """An unresolved q2r record blocks the dispersion before the path is
    read, so a disordered written cell keeps q2r's root cause, the
    boundary's, which waits on the cell's unavailable geometry. With q2r
    resolved, the path's own reason blocks it."""
    alloy = Structure(
        Lattice.cubic(3.6), [{"Cu": 0.5, "Au": 0.5}], [[0, 0, 0]]
    ).make_supercell([2, 2, 2])
    cell = framed_magnetic_cell(alloy)
    geometry = Unavailable(
        reason="dimensionality classification does not support disordered structures"
    )

    by_q2r = dispersion_path(
        cell, geometry, _occupations(), Blocked(by=geometry.reason)
    )
    by_path = dispersion_path(cell, geometry, _occupations(), _q2r_record())

    assert isinstance(by_q2r, Blocked)
    assert by_q2r.root_cause() == geometry.reason
    assert isinstance(by_path, Blocked)
    assert by_path.root_cause() == k_path(cell).reason
