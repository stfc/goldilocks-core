from __future__ import annotations

from dataclasses import replace

import pytest
from pymatgen.core import Lattice, Structure
from support import magnetic_decision

from goldilocks_core.advisors.magnetic_config import (
    MagneticConfigFacts,
    MagneticConfigHumanInput,
    SpinMode,
)
from goldilocks_core.advisors.nbnd import (
    NbndHumanInput,
    NbndLlmInput,
    NbndProtocol,
    band_floors,
    nbnd,
)
from goldilocks_core.advisors.occupations import OccupationsDecision
from goldilocks_core.analysis.is_magnetic import is_magnetic
from goldilocks_core.resolution import Blocked, FieldState, Provenance, Resolved

_IRON = Structure(Lattice.cubic(2.87), ["Fe"], [[0.0, 0.0, 0.0]])
_SILICON = Structure(Lattice.cubic(5.43), ["Si", "Si"], [[0, 0, 0], [0.25, 0.25, 0.25]])

_FIXED = Resolved(
    OccupationsDecision(occupations="fixed", smearing_type=None, degauss=None),
    Provenance(source="heuristic"),
)
_SMEARING = Resolved(
    OccupationsDecision(occupations="smearing", smearing_type="cold", degauss=0.01),
    Provenance(source="heuristic"),
)


def test_insulator_gets_half_of_nelec() -> None:
    state = nbnd(20.0, _FIXED)

    assert state.ok
    assert state.value.nbnd == 10


def test_insulator_rounds_an_odd_electron_count_up() -> None:
    state = nbnd(21.0, _FIXED)

    assert state.value.nbnd == 11  # nelup = INT(22)/2 = 11, neldw = 10


def test_metal_gets_twenty_percent_more_when_that_exceeds_the_floor() -> None:
    # nelec=200 -> nelup = neldw = 100; NINT(1.2*100)=120 beats 100+4=104.
    state = nbnd(200.0, _SMEARING)

    assert state.value.nbnd == 120


def test_metal_gets_at_least_four_more_when_twenty_percent_is_smaller() -> None:
    # nelec=10 -> nelup = neldw = 5; NINT(1.2*5)=6, but 5+4=9 is the floor.
    state = nbnd(10.0, _SMEARING)

    assert state.value.nbnd == 9


def test_tetrahedra_opt_is_treated_as_metal_like() -> None:
    tetrahedra = Resolved(
        OccupationsDecision(
            occupations="tetrahedra_opt", smearing_type=None, degauss=None
        ),
        Provenance(source="human"),
    )

    state = nbnd(10.0, tetrahedra)

    assert state.value.nbnd == 9


def test_blocked_occupations_propagates_as_blocked() -> None:
    state = nbnd(20.0, Blocked(by="synthetic failure"))

    assert not state.ok
    assert state.status == "blocked"
    assert state.root_cause() == "synthetic failure"


def test_human_nbnd_overrides_everything() -> None:
    state = nbnd(20.0, Blocked(by="synthetic failure"), human=NbndHumanInput(nbnd=42))

    assert state.ok
    assert state.value.nbnd == 42
    assert state.source == "human"


def test_human_extra_bands_adds_to_the_computed_base() -> None:
    state = nbnd(20.0, _FIXED, human=NbndHumanInput(extra_bands=5))

    assert state.value.nbnd == 15
    assert state.source == "human"


def test_extra_bands_driving_the_total_non_positive_is_unavailable() -> None:
    """Regression for #35 (v2 epic 9, #9): extra_bands is a legitimately
    -signed adjustment (can't just be Field(gt=0)), but a sufficiently
    negative value used to silently drive the combined nbnd to zero or
    negative, reported as a resolved success rather than degrading."""
    state = nbnd(20.0, _FIXED, human=NbndHumanInput(extra_bands=-15))

    assert not state.ok
    assert state.status == "unavailable"


def test_llm_extra_bands_used_when_no_human_override() -> None:
    state = nbnd(20.0, _FIXED, llm=NbndLlmInput(extra_bands=3))

    assert state.value.nbnd == 13
    assert state.source == "llm"


def test_spin_polarized_system_gets_an_informational_note() -> None:
    magnetic = magnetic_decision(_IRON, is_magnetic(_IRON))

    state = nbnd(16.0, _FIXED, magnetic=magnetic)

    assert any(
        "not the number of bands" in warning.message for warning in state.value.warnings
    )


def test_non_magnetic_system_has_no_spin_note() -> None:
    magnetic = magnetic_decision(_SILICON, is_magnetic(_SILICON))

    state = nbnd(8.0, _FIXED, magnetic=magnetic)

    assert state.value.warnings == ()


def test_noncollinear_insulator_uses_the_full_electron_count_not_half() -> None:
    """QE's noncollinear bands hold one electron each (a two-component
    spinor), not two -- twice the band count of a comparable collinear
    run (v2 epic 9, #9)."""
    magnetic = magnetic_decision(
        _SILICON,
        is_magnetic(_SILICON),
        human=MagneticConfigHumanInput(spin_orbit_coupling=True),
    )

    state = nbnd(20.0, _FIXED, magnetic=magnetic)

    assert state.value.nbnd == 20


def test_noncollinear_metal_doubles_the_padded_per_spin_count() -> None:
    # nelec=200 -> nelup = neldw = 100, padded to MAX(120, 120, 120, 104)
    # = 120, then doubled (setup.f90 pads before doubling, #162).
    magnetic = magnetic_decision(
        _SILICON,
        is_magnetic(_SILICON),
        human=MagneticConfigHumanInput(spin_orbit_coupling=True),
    )

    state = nbnd(200.0, _SMEARING, magnetic=magnetic)

    assert state.value.nbnd == 240


def test_noncollinear_gets_its_own_note_not_the_nspin_two_one() -> None:
    magnetic = magnetic_decision(
        _IRON,
        is_magnetic(_IRON),
        human=MagneticConfigHumanInput(spin_orbit_coupling=True),
    )

    state = nbnd(16.0, _FIXED, magnetic=magnetic)

    assert any("one electron" in warning.message for warning in state.value.warnings)
    assert not any(
        "not the number of bands" in warning.message for warning in state.value.warnings
    )


# #162: nbnd is pw.x's own default, QE 7.3 PW/src/setup.f90:326-345, with
# nelup/neldw from Modules/electrons_base.f90:376-428 (set_nelup_neldw):
#   base = MAX(NINT(nelec/2), NINT(nelup), NINT(neldw))
#   smearing/tetrahedra: MAX(NINT(1.2*nelec/2), NINT(1.2*nelup),
#                            NINT(1.2*neldw), base + 4)
#   noncolin: doubled after the padding.
# Without tot_magnetization nelup = INT(nelec+1)/2 and neldw = nelec - nelup;
# with an integer one, nelup/neldw = (INT(nelec) +/- tot)/2. NINT rounds
# half away from zero (Python's round() rounds half to even).
_SI_PRIMITIVE = Structure(
    Lattice([[0.0, 2.715, 2.715], [2.715, 0.0, 2.715], [2.715, 2.715, 0.0]]),
    ["Si", "Si"],
    [[0.0, 0.0, 0.0], [0.25, 0.25, 0.25]],
)
_FEPT = Structure(
    Lattice.tetragonal(2.73, 3.71), ["Fe", "Pt"], [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]]
)


def _spin_facts(mode: SpinMode) -> FieldState[MagneticConfigFacts]:
    """A resolved magnetic decision of spin mode ``mode``: diamond Si for
    ``none``, L1_0 FePt otherwise (spin-orbit coupling on for
    ``noncollinear``)."""
    if mode == "none":
        facts = magnetic_decision(_SI_PRIMITIVE, is_magnetic(_SI_PRIMITIVE))
    else:
        human = MagneticConfigHumanInput(spin_orbit_coupling=mode == "noncollinear")
        facts = magnetic_decision(_FEPT, is_magnetic(_FEPT), human=human)
    assert facts.value.spin_mode == mode
    # No net seed: the spin channels are QE's own (#131).
    return Resolved(replace(facts.value, seeded_moment=0.0), facts.provenance)


def _occupations(
    scheme: str, tot_magnetization: float | None = None
) -> FieldState[OccupationsDecision]:
    if scheme == "fixed":
        decision = OccupationsDecision(
            occupations="fixed",
            smearing_type=None,
            degauss=None,
            tot_magnetization=tot_magnetization,
        )
    else:
        decision = OccupationsDecision(
            occupations="smearing",
            smearing_type="cold",
            degauss=0.01,
            tot_magnetization=tot_magnetization,
        )
    return Resolved(decision, Provenance(source="heuristic"))


@pytest.mark.parametrize(
    ("nelec", "scheme", "mode", "tot_magnetization", "expected"),
    [
        # Spin-orbit smearing: padded per spin channel, then doubled.
        # Pb: nelup = neldw = 7; 2 * MAX(NINT(8.4)=8, 8, 8, 7+4) = 22.
        pytest.param(14.0, "smearing", "noncollinear", None, 22, id="Pb-soc-14"),
        # Bi: nelup = neldw = 15; 2 * MAX(18, 18, 18, 15+4) = 38.
        pytest.param(30.0, "smearing", "noncollinear", None, 38, id="Bi-soc-30"),
        # FePt: nelup = neldw = 17; 2 * MAX(NINT(20.4)=20, 20, 20, 17+4) = 42.
        pytest.param(34.0, "smearing", "noncollinear", None, 42, id="FePt-soc-34"),
        # nelup = 7, neldw = 6; base MAX(NINT(6.5)=7, 7, 6) = 7;
        # 2 * MAX(NINT(7.8)=8, NINT(8.4)=8, NINT(7.2)=7, 7+4) = 22: even.
        pytest.param(13.0, "smearing", "noncollinear", None, 22, id="soc-odd-13"),
        # Collinear smearing. MoS2: nelup = neldw = 26;
        # MAX(NINT(31.2)=31, 31, 31, 26+4) = 31.
        pytest.param(52.0, "smearing", "none", None, 31, id="MoS2-52"),
        # nelup = 23, neldw = 22; base MAX(NINT(22.5)=23, 23, 22) = 23;
        # MAX(NINT(27.0)=27, NINT(27.6)=28, NINT(26.4)=26, 23+4) = 28.
        pytest.param(45.0, "smearing", "none", None, 28, id="nelup-term-45"),
        # nelup = neldw = 5; MAX(6, 6, 6, 5+4) = 9.
        pytest.param(10.0, "smearing", "none", None, 9, id="floor-10"),
        # Fixed: nelup = INT(26)/2 = 13, neldw = 12; MAX(NINT(12.5)=13, 13, 12).
        pytest.param(25.0, "fixed", "none", None, 13, id="fixed-25"),
        # nelup = 11, neldw = 10; MAX(NINT(10.5)=11, 11, 10) = 11.
        pytest.param(21.0, "fixed", "none", None, 11, id="fixed-21"),
        # Spin-orbit fixed: 2 * MAX(10, 10, 10) = 20.
        pytest.param(20.0, "fixed", "noncollinear", None, 20, id="soc-fixed-20"),
        # nspin=2 fixed: nelup = (192+16)/2 = 104, neldw = 88; MAX(96, 104, 88).
        pytest.param(192.0, "fixed", "collinear", 16.0, 104, id="LiFePO4-fixed"),
        # nelup = 7, neldw = 5; MAX(6, 7, 5) = 7.
        pytest.param(12.0, "fixed", "collinear", 2.0, 7, id="O2-fixed"),
        # nelup = 6.5, neldw = 5.5; MAX(6, NINT(6.5)=7, NINT(5.5)=6) = 7,
        # where round() gives MAX(6, 6, 6) = 6.
        pytest.param(12.0, "fixed", "collinear", 1.0, 7, id="nint-half-up-fixed"),
        # Same spin channels under smearing: base 7; MAX(NINT(7.2)=7,
        # NINT(7.8)=8, NINT(6.6)=7, 7+4) = 11, where round() gives 10.
        pytest.param(12.0, "smearing", "collinear", 1.0, 11, id="nint-half-up"),
        # nspin=2 smearing: nelup = 25, neldw = 11; base MAX(18, 25, 11) = 25;
        # MAX(NINT(21.6)=22, NINT(30.0)=30, NINT(13.2)=13, 25+4) = 30.
        pytest.param(36.0, "smearing", "collinear", 14.0, 30, id="collinear-tot-14"),
        # A negative moment makes the minority channel the larger one:
        # nelup = 11, neldw = 25; MAX(NINT(21.6)=22, NINT(13.2)=13,
        # NINT(30.0)=30, 25+4) = 30.
        pytest.param(36.0, "smearing", "collinear", -14.0, 30, id="collinear-tot--14"),
        # nelup = 5, neldw = 7; MAX(6, 5, 7) = 7.
        pytest.param(12.0, "fixed", "collinear", -2.0, 7, id="fixed-tot--2"),
        # Without tot_magnetization and with no net seed (#131) nspin=2
        # sizes like nspin=1: nelup = 7, neldw = 6, as soc-odd-13 without
        # the doubling.
        pytest.param(13.0, "smearing", "collinear", None, 11, id="collinear-13"),
    ],
)
def test_nbnd_is_pw_x_own_default(
    nelec: float,
    scheme: str,
    mode: SpinMode,
    tot_magnetization: float | None,
    expected: int,
) -> None:
    state = nbnd(
        nelec, _occupations(scheme, tot_magnetization), magnetic=_spin_facts(mode)
    )

    assert state.value.nbnd == expected
    assert state.source == "heuristic"


def test_the_moment_counts_only_where_the_writer_renders_it() -> None:
    """``tot_magnetization`` is written for a collinear spin-polarized run
    only (nspin=2; pw.x refuses it otherwise), so nbnd sizes from it only
    there: the same decision on a run without spin polarization sizes as
    nelup = neldw = 96."""
    occupations = _occupations("fixed", 16.0)

    unpolarized = nbnd(192.0, occupations, magnetic=_spin_facts("none"))
    collinear = nbnd(192.0, occupations, magnetic=_spin_facts("collinear"))

    assert (unpolarized.value.nbnd, collinear.value.nbnd) == (96, 104)


# #131: a collinear spin-polarized run on smearing or tetrahedra without
# tot_magnetization sizes its majority channel for the seeded moment M
# (MagneticConfigFacts.seeded_moment): nelup = MAX(QE's nelup,
# (nelec + |M|)/2), neldw = nelec - nelup, then pw.x's own default. pw.x
# holds such a run's moment at 2*nbnd - nelec: hcp Gd's default 22 bands
# held it at 8 uB on SCARF instead of 15.5.
_HCP_GADOLINIUM = Structure.from_spacegroup(
    "P6_3/mmc", Lattice.hexagonal(3.642, 5.902), ["Gd"], [[1 / 3, 2 / 3, 0.25]]
)
_GD_NELEC = 36.0  # two Gd with an 18-electron pseudopotential


def _gadolinium(*, z_valence_known: bool = True) -> FieldState[MagneticConfigFacts]:
    """hcp Gd's magnetic decision: spin-polarized, seeded at 5/18 per
    site with an 18-electron pseudopotential, 10 uB per cell -- unknown
    without its z_valence."""
    return magnetic_decision(
        _HCP_GADOLINIUM,
        is_magnetic(_HCP_GADOLINIUM),
        z_valences={"Gd": 18.0} if z_valence_known else None,
    )


def test_a_smearing_magnet_s_majority_channel_has_room_for_its_seed() -> None:
    """nelup = (36 + 10)/2 = 23, neldw = 13; base MAX(18, 23, 13) = 23;
    MAX(NINT(21.6)=22, NINT(27.6)=28, NINT(15.6)=16, 23+4) = 28, so
    2*28 - 36 = 20 uB of room against the 10 uB seed, where pw.x's
    default 22 bands leave 8."""
    state = nbnd(_GD_NELEC, _occupations("smearing"), magnetic=_gadolinium())

    assert state.value.nbnd == 28
    assert 2 * state.value.nbnd - _GD_NELEC > 10.0
    assert state.source == "heuristic"
    assert [warning.code for warning in state.value.warnings] == [
        "nbnd.spin_channel_note"
    ]


@pytest.mark.parametrize(
    ("nelec", "seed", "expected"),
    [
        # bcc Fe, one 16-electron site seeded 5 uB: nelup = 10.5, neldw =
        # 5.5; base MAX(8, NINT(10.5)=11, NINT(5.5)=6) = 11;
        # MAX(NINT(9.6)=10, NINT(12.6)=13, NINT(6.6)=7, 11+4) = 15.
        pytest.param(16.0, 5.0, 15, id="bcc-Fe"),
        # LiFePO4's ferromagnetic seed, 4 x 5 uB on Fe plus 0.1 on every
        # Li, P and O electron: 32.8 uB. nelup = 112.4, neldw = 79.6;
        # base 112; MAX(NINT(115.2)=115, NINT(134.88)=135, 96, 116) = 135.
        pytest.param(192.0, 32.8, 135, id="LiFePO4"),
        # A negative net seed fills the minority channel the same way.
        pytest.param(16.0, -5.0, 15, id="negative-seed"),
        # A seed below QE's own nelup - neldw changes nothing: nelec 13
        # gives nelup 7, neldw 6 without it.
        pytest.param(13.0, 0.5, 11, id="seed-below-qe-split"),
    ],
)
def test_the_seed_sizes_the_majority_channel(
    nelec: float, seed: float, expected: int
) -> None:
    magnetic = _spin_facts("collinear")
    seeded = Resolved(replace(magnetic.value, seeded_moment=seed), magnetic.provenance)

    state = nbnd(nelec, _occupations("smearing"), magnetic=seeded)

    assert state.value.nbnd == expected


def test_tetrahedra_size_for_the_seed_like_smearing() -> None:
    tetrahedra = Resolved(
        OccupationsDecision(
            occupations="tetrahedra_opt", smearing_type=None, degauss=None
        ),
        Provenance(source="heuristic"),
    )

    state = nbnd(_GD_NELEC, tetrahedra, magnetic=_gadolinium())

    assert state.value.nbnd == 28


def test_a_pinned_moment_sizes_the_channels_instead_of_the_seed() -> None:
    """tot_magnetization pins the moment, so the seed no longer decides
    it: Gd with tot 2 sizes from nelup = 19, neldw = 17; base 19;
    MAX(22, NINT(22.8)=23, NINT(20.4)=20, 19+4) = 23."""
    state = nbnd(_GD_NELEC, _occupations("smearing", 2.0), magnetic=_gadolinium())

    assert state.value.nbnd == 23


def test_fixed_occupations_ignore_the_seed() -> None:
    """Fixed occupations of a collinear run fill the pinned nelup/neldw
    (the gate refuses them without a moment), so the seed adds nothing."""
    state = nbnd(_GD_NELEC, _occupations("fixed"), magnetic=_gadolinium())

    assert state.value.nbnd == 18


def test_a_noncollinear_magnet_ignores_the_seed() -> None:
    """A spinor band holds one electron of any spin direction, so there is
    no majority channel to cap: SOC FePt keeps pw.x's doubled default
    (nelup = neldw = 17; 2 * MAX(20, 20, 20, 21) = 42), seeded or not."""
    human = MagneticConfigHumanInput(spin_orbit_coupling=True)
    magnetic = magnetic_decision(
        _FEPT, is_magnetic(_FEPT), z_valences={"Fe": 16.0, "Pt": 10.0}, human=human
    )
    assert magnetic.value.seeded_moment == pytest.approx(10.0)

    state = nbnd(34.0, _occupations("smearing"), magnetic=magnetic)

    assert state.value.nbnd == 42


def test_a_smearing_magnet_without_a_seeded_moment_is_blocked() -> None:
    """Without z_valences the seed has no size in Bohr magnetons, so the
    majority channel cannot be sized; nbnd says why instead of guessing."""
    magnetic = _gadolinium(z_valence_known=False)

    state = nbnd(_GD_NELEC, _occupations("smearing"), magnetic=magnetic)

    assert isinstance(state, Blocked)
    assert isinstance(state.by, str)
    assert "seeded moment" in state.root_cause()
    assert "z_valence" in state.root_cause()


def test_a_human_nbnd_that_holds_the_moment_below_its_seed_is_warned() -> None:
    """pw.x accepts 22 bands for Gd but holds the moment at 2*22 - 36 = 8
    uB, below the 10 uB seed, without an error: the human value stands,
    with a warning naming both (and no note on how the default is
    sized)."""
    state = nbnd(
        _GD_NELEC,
        _occupations("smearing"),
        magnetic=_gadolinium(),
        human=NbndHumanInput(nbnd=22),
    )

    assert state.value.nbnd == 22
    assert state.source == "human"
    (capped,) = state.value.warnings
    assert capped.code == "nbnd.moment_capped"
    assert capped.level == "warning"
    assert capped.message == (
        "nbnd=22 leaves room for at most 2*nbnd - nelec = 8 Bohr magnetons per "
        "cell in this collinear smearing run, below the 10 its starting "
        "magnetization seeds; pw.x holds the moment there without an error. "
        "Use nbnd >= 28, the default for this seed, or unset nbnd and "
        "extra_bands."
    )


def test_an_llm_extra_bands_that_caps_the_moment_is_warned() -> None:
    state = nbnd(
        _GD_NELEC,
        _occupations("smearing"),
        magnetic=_gadolinium(),
        llm=NbndLlmInput(extra_bands=-6),
    )

    assert state.value.nbnd == 22
    assert state.source == "llm"
    assert "nbnd.moment_capped" in [w.code for w in state.value.warnings]


def test_a_human_nbnd_with_room_for_the_seed_is_not_warned() -> None:
    """2*23 - 36 = 10 uB holds the 10 uB seed exactly."""
    state = nbnd(
        _GD_NELEC,
        _occupations("smearing"),
        magnetic=_gadolinium(),
        human=NbndHumanInput(nbnd=23),
    )

    assert "nbnd.moment_capped" not in [w.code for w in state.value.warnings]


@pytest.mark.parametrize(
    ("purpose", "nelec", "seed", "bands", "fill", "count"),
    [
        # hcp Gd: (36 + 10)/2 = 23 electrons in the seeded majority channel.
        pytest.param("bands", 36.0, 10.0, 22, "23", 23, id="bands-Gd"),
        # bcc Fe: (16 + 5)/2 = 10.5 electrons need 11 bands.
        pytest.param("nscf", 16.0, 5.0, 10, "10.5", 11, id="nscf-Fe"),
    ],
)
def test_a_non_scf_step_below_the_seeded_majority_count_says_bands_are_missing(
    purpose: str, nelec: float, seed: float, bands: int, fill: str, count: int
) -> None:
    """An nscf or bands step runs no SCF loop, so too few bands do not cap
    its moment the way an SCF step's do: they leave occupied bands of the
    majority channel out if the scf's moment reaches its seed, a maximal
    target (#118). The warning says so and names the fewest bands that hold
    them, the seeded majority count rounded up."""
    magnetic = _spin_facts("collinear")
    seeded = Resolved(replace(magnetic.value, seeded_moment=seed), magnetic.provenance)

    state = nbnd(
        nelec,
        _occupations("smearing"),
        purpose,
        seeded,
        NbndHumanInput(nbnd=bands),
    )

    (capped,) = state.value.warnings
    assert capped.code == "nbnd.moment_capped"
    assert capped.level == "warning"
    assert capped.message == (
        f"nbnd={bands} holds fewer than the (nelec + |M|)/2 = {fill} electrons "
        f"the majority spin channel fills at the {seed:g} Bohr magnetons the "
        "starting magnetization seeds: if the scf's moment reaches that seed, "
        f"this {purpose} step leaves occupied majority bands out. Use nbnd >= "
        f"{count}, or unset nbnd and extra_bands."
    )


@pytest.mark.parametrize("purpose", ["relax", "vc-relax"])
def test_a_relaxation_step_s_moment_warning_is_the_scf_one(purpose: str) -> None:
    """relax and vc-relax run an SCF loop at every ionic step, so too few
    bands cap their moment as they cap an scf step's."""
    scf, relaxation = (
        nbnd(
            _GD_NELEC,
            _occupations("smearing"),
            step,
            _gadolinium(),
            NbndHumanInput(nbnd=22),
        )
        for step in ("scf", purpose)
    )

    assert relaxation.value.warnings == scf.value.warnings


@pytest.mark.parametrize(
    ("nelec", "scheme", "mode", "tot_magnetization", "floors"),
    [
        # setup.f90:349-356: NINT(nelec/2), NINT(nelup), NINT(neldw), in
        # that order, and NINT(nelec) for noncolin.
        pytest.param(
            192.0,
            "fixed",
            "collinear",
            16.0,
            (
                (96, "too few bands"),
                (104, "too few spin up bands"),
                (88, "too few spin dw bands"),
            ),
            id="LiFePO4-tot-16",
        ),
        pytest.param(
            12.0,
            "fixed",
            "collinear",
            -2.0,
            (
                (6, "too few bands"),
                (5, "too few spin up bands"),
                (7, "too few spin dw bands"),
            ),
            id="O2-tot--2",
        ),
        # Without a moment nelup = INT(nelec+1)/2: 4 and 4 for nelec 8.
        pytest.param(
            8.0,
            "fixed",
            "none",
            None,
            (
                (4, "too few bands"),
                (4, "too few spin up bands"),
                (4, "too few spin dw bands"),
            ),
            id="Si-8",
        ),
        # Under smearing the floors are unpadded; the moment is not seeded.
        pytest.param(
            36.0,
            "smearing",
            "collinear",
            None,
            (
                (18, "too few bands"),
                (18, "too few spin up bands"),
                (18, "too few spin dw bands"),
            ),
            id="Gd-smearing",
        ),
        pytest.param(
            14.0,
            "smearing",
            "noncollinear",
            None,
            (
                (7, "too few bands"),
                (7, "too few spin up bands"),
                (7, "too few spin dw bands"),
                (14, "too few bands"),
            ),
            id="Pb-soc-14",
        ),
    ],
)
def test_band_floors_are_pw_x_own_checks(
    nelec: float,
    scheme: str,
    mode: SpinMode,
    tot_magnetization: float | None,
    floors: tuple[tuple[int, str], ...],
) -> None:
    found = band_floors(
        nelec, _occupations(scheme, tot_magnetization).value, _spin_facts(mode)
    )

    assert tuple((floor.bands, floor.error) for floor in found) == floors


def test_band_floors_name_the_electrons_each_one_holds() -> None:
    found = band_floors(
        192.0, _occupations("fixed", 16.0).value, _spin_facts("collinear")
    )

    assert [(floor.electrons, floor.held) for floor in found] == [
        (192.0, "electrons, two per band"),
        (104.0, "spin-up electrons"),
        (88.0, "spin-down electrons"),
    ]


# #118: a task protocol sizes a step's bands (NbndProtocol): the band task's
# bands step asks for aiida-quantumespresso's PwBandsWorkChain count, the
# largest of pw.x's default for the run, int(nelec/epb*factor) and
# int(nelec/epb) + 4, epb being one electron per band for a noncollinear
# run and two otherwise.
_BAND_NOTE = "A band protocol's band count."


def _silicon(*, spin_orbit_coupling: bool | None = None):
    return magnetic_decision(
        _SI_PRIMITIVE,
        is_magnetic(_SI_PRIMITIVE),
        human=MagneticConfigHumanInput(spin_orbit_coupling=spin_orbit_coupling),
    )


@pytest.mark.parametrize(
    ("nelec", "scheme", "magnetic", "factor", "expected"),
    [
        # Si: MAX(pw.x's 4, int(8/2*3) = 12, 4 + 4 = 8) = 12.
        pytest.param(8.0, "fixed", _silicon, 3.0, 12, id="Si"),
        # hcp Gd, per spin channel: MAX(the seeded 28, int(36/2*3) = 54,
        # 18 + 4 = 22) = 54.
        pytest.param(_GD_NELEC, "smearing", _gadolinium, 3.0, 54, id="Gd"),
        # Si with spin-orbit coupling, one electron per spinor band:
        # MAX(2*4 = 8, int(8*3) = 24, 8 + 4 = 12) = 24.
        pytest.param(
            8.0,
            "fixed",
            lambda: _silicon(spin_orbit_coupling=True),
            3.0,
            24,
            id="Si-soc",
        ),
        # pw.x's default wins over a small factor: MAX(28, 18, 22) = 28.
        pytest.param(_GD_NELEC, "smearing", _gadolinium, 1.0, 28, id="Gd-factor-1"),
        # Four more than the occupied bands win for few electrons:
        # MAX(1, int(2/2*3) = 3, 1 + 4 = 5) = 5.
        pytest.param(2.0, "fixed", lambda: None, 3.0, 5, id="two-electrons"),
    ],
)
def test_a_band_protocol_asks_for_factor_times_the_occupied_bands(
    nelec: float, scheme: str, magnetic, factor: float, expected: int
) -> None:
    protocol = NbndProtocol(factor=factor, note=_BAND_NOTE)

    state = nbnd(nelec, _occupations(scheme), "bands", magnetic(), protocol=protocol)

    assert state.value.nbnd == expected
    assert state.provenance == Provenance(source="heuristic", source_note=_BAND_NOTE)
    assert "nbnd.moment_capped" not in [w.code for w in state.value.warnings]


def test_extra_bands_add_to_a_band_protocol_and_a_human_nbnd_replaces_it() -> None:
    protocol = NbndProtocol(factor=3.0, note=_BAND_NOTE)
    occupations = _occupations("fixed")

    human_extra, llm_extra, chosen = (
        nbnd(8.0, occupations, "bands", _silicon(), human, llm, protocol=protocol)
        for human, llm in (
            (NbndHumanInput(extra_bands=2), None),
            (None, NbndLlmInput(extra_bands=-2)),
            (NbndHumanInput(nbnd=6), None),
        )
    )

    assert human_extra.value.nbnd == 14
    assert human_extra.provenance == Provenance(source="human", source_note=_BAND_NOTE)
    assert (llm_extra.value.nbnd, llm_extra.source) == (10, "llm")
    assert chosen.value.nbnd == 6
    assert chosen.provenance == Provenance(source="human")
