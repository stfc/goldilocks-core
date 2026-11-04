from __future__ import annotations

from dataclasses import replace

import pytest
from pymatgen.core import Lattice, Structure
from support import magnetic_decision

from goldilocks_core.advisors.electron_count import ElectronCountDecision
from goldilocks_core.advisors.magnetic_config import (
    MagneticConfigFacts,
    MagneticConfigHumanInput,
    OrderingRecord,
)
from goldilocks_core.advisors.occupations import (
    OccupationsDecision,
    OccupationsHumanInput,
    OccupationsLlmInput,
    OccupationsProtocol,
    UnpinnedMomentProtocol,
    bands_occupations,
    occupations,
    whole_spin_channels,
)
from goldilocks_core.analysis.is_magnetic import is_magnetic
from goldilocks_core.analysis.is_metal import is_metal
from goldilocks_core.resolution import Blocked, Provenance, Resolved, Unavailable
from goldilocks_core.service._step_protocol import BAND_SCF_PROTOCOL

_IRON = Structure(Lattice.cubic(2.87), ["Fe"], [[0.0, 0.0, 0.0]])
_SILICON = Structure(Lattice.cubic(5.43), ["Si", "Si"], [[0, 0, 0], [0.25, 0.25, 0.25]])
_BCC_IRON = Structure(Lattice.cubic(2.87), ["Fe", "Fe"], [[0, 0, 0], [0.5, 0.5, 0.5]])
_NON_METAL = Resolved("non_metal", Provenance(source="heuristic"))


def _electron_count(nelec: float):
    return Resolved(
        ElectronCountDecision(nelec=nelec, tot_charge=0.0),
        Provenance(source="heuristic"),
    )


def _applied_ordering(*, compensated: bool, spin_orbit: bool = False):
    """A collinear run on an applied antiferromagnetic ordering, with or
    without an operation that reverses every spin (``compensated``); a
    noncollinear one with ``spin_orbit``."""
    facts = MagneticConfigFacts(
        cell=_BCC_IRON,  # not read by occupations
        ordering=OrderingRecord(
            requested="afm",
            applied="afm-1",
            criterion="smallest_cell",
        ),
        spin_polarized=True,
        magnetic_elements=("Fe",),
        starting_magnetization={"Fe1": 0.3, "Fe2": -0.3},
        compensated=compensated,
        tot_magnetization=None,
        spin_orbit_enabled=spin_orbit,
        angle1=None,
        angle2=None,
    )
    return Resolved(facts, Provenance(source="human"))


def test_metal_gets_cold_smearing() -> None:
    state = occupations(is_metal(_IRON))

    assert state.ok
    assert state.value.occupations == "smearing"
    assert state.value.smearing_type == "cold"
    assert state.value.degauss == 0.01


def test_smearing_type_and_degauss_apply_without_also_setting_occupations() -> None:
    """Regression for #34 (v2 epic 9, #9): a human-supplied smearing_type/
    degauss with no matching occupations override used to be silently
    dropped in favor of the hardcoded 'cold'/0.01 heuristic default,
    since only the explicit-occupations branch ever read them."""
    state = occupations(
        is_metal(_IRON),
        human=OccupationsHumanInput(smearing_type="mp", degauss=0.05),
    )

    assert state.ok
    assert state.value.occupations == "smearing"
    assert state.value.smearing_type == "mp"
    assert state.value.degauss == 0.05


def test_confirmed_non_metal_gets_fixed_occupations() -> None:
    state = occupations(Resolved("non_metal", Provenance(source="heuristic")))

    assert state.value.occupations == "fixed"
    assert state.value.smearing_type is None
    assert state.value.degauss is None


def test_unavailable_metallicity_defaults_to_smearing_not_blocked() -> None:
    """Unavailable means "could not confirm either way" -- since v2's
    is_metal is more conservative than v1's classification, this bucket
    now includes cases that look metallic but are not fully confirmed, so
    it gets the safe universal default (smearing), not a guessed fixed."""
    state = occupations(Unavailable(reason="composition alone does not confirm"))

    assert state.ok
    assert state.value.occupations == "smearing"


def test_blocked_metallicity_propagates_as_blocked() -> None:
    state = occupations(Blocked(by="synthetic failure"))

    assert not state.ok
    assert state.status == "blocked"
    assert state.root_cause() == "synthetic failure"


def test_human_can_force_smearing_with_custom_values() -> None:
    state = occupations(
        is_metal(_SILICON),
        human=OccupationsHumanInput(
            occupations="smearing", smearing_type="gaussian", degauss=0.02
        ),
    )

    assert state.value.occupations == "smearing"
    assert state.value.smearing_type == "gaussian"
    assert state.value.degauss == 0.02
    assert state.source == "human"


def test_human_can_force_tetrahedra_opt() -> None:
    state = occupations(
        is_metal(_IRON), human=OccupationsHumanInput(occupations="tetrahedra_opt")
    )

    assert state.value.occupations == "tetrahedra_opt"
    assert state.value.smearing_type is None
    assert state.value.degauss is None


def test_llm_can_choose_fixed_over_a_metal_heuristic() -> None:
    state = occupations(is_metal(_IRON), llm=OccupationsLlmInput(occupations="fixed"))

    assert state.value.occupations == "fixed"
    assert state.source == "llm"


def test_explicit_fixed_occupations_without_a_moment_keep_fixed_and_warn() -> None:
    """#138: an explicit fixed on a collinear run with no moment to pin
    stays fixed -- the gate refuses it -- and says why."""
    magnetic = magnetic_decision(_BCC_IRON, is_magnetic(_BCC_IRON))

    state = occupations(
        _NON_METAL,
        magnetic,
        _electron_count(32.0),
        human=OccupationsHumanInput(occupations="fixed"),
    )

    assert state.value.occupations == "fixed"
    assert state.value.tot_magnetization is None
    assert [warning.code for warning in state.value.warnings] == [
        "occupations.fixed_spin_polarized_needs_integer_tot_magnetization"
    ]


@pytest.mark.parametrize(
    "human",
    [
        # noncollinear: pw.x takes no tot_magnetization there (#146)
        MagneticConfigHumanInput(spin_orbit_coupling=True),
        # collinear, with the moment the warning asks for
        MagneticConfigHumanInput(tot_magnetization=2.0),
    ],
    ids=["spin-orbit", "tot_magnetization"],
)
def test_fixed_occupations_warn_only_for_a_collinear_run_without_a_moment(
    human: MagneticConfigHumanInput,
) -> None:
    magnetic = magnetic_decision(_BCC_IRON, is_magnetic(_BCC_IRON), human=human)

    state = occupations(Resolved("non_metal", Provenance(source="heuristic")), magnetic)

    assert state.value.occupations == "fixed"
    assert state.value.warnings == ()


def test_fixed_occupations_on_a_non_magnetic_system_has_no_warning() -> None:
    magnetic = magnetic_decision(_SILICON, is_magnetic(_SILICON))

    state = occupations(Resolved("non_metal", Provenance(source="heuristic")), magnetic)

    assert state.value.warnings == ()


def test_smearing_never_gets_the_fixed_spin_warning() -> None:
    magnetic = magnetic_decision(_IRON, is_magnetic(_IRON))

    state = occupations(is_metal(_IRON), magnetic)

    assert state.value.occupations == "smearing"
    assert state.value.warnings == ()


def test_a_spin_polarized_non_metal_without_a_moment_gets_smearing() -> None:
    """#138: LiFePO4, NiO and the other magnetic insulators got fixed
    occupations on nspin=2 without the integer tot_magnetization pw.x
    needs for that (QE 7.3 PW/src/input.f90:764-778), so the gate refused
    the default. Without a known moment the default is smearing."""
    magnetic = magnetic_decision(_BCC_IRON, is_magnetic(_BCC_IRON))

    state = occupations(_NON_METAL, magnetic, _electron_count(32.0))

    assert magnetic.value.spin_mode == "collinear"
    assert state.ok
    assert state.source == "heuristic"
    assert state.value.occupations == "smearing"
    assert state.value.smearing_type == "cold"
    assert state.value.degauss == 0.01
    assert state.value.tot_magnetization is None
    assert state.value.warnings == ()


def test_a_compensated_afm_non_metal_gets_fixed_with_a_zero_moment() -> None:
    """#138: an applied ordering with a spin-reversing symmetry has no net
    moment by construction, so fixed occupations pin tot_magnetization 0."""
    state = occupations(
        _NON_METAL, _applied_ordering(compensated=True), _electron_count(48.0)
    )

    assert state.value.occupations == "fixed"
    assert state.value.tot_magnetization == 0.0
    assert state.value.smearing_type is None
    assert state.value.warnings == ()


@pytest.mark.parametrize(
    ("compensated", "nelec"),
    [(False, 48.0), (True, 49.0)],
    ids=["no-spin-flip-symmetry", "odd-electron-count"],
)
def test_no_zero_moment_is_derived_without_symmetry_or_whole_channels(
    compensated: bool, nelec: float
) -> None:
    """A ferrimagnet's moment is not zero by symmetry, whatever its spin
    counts, and a zero moment cannot split an odd count into whole spin
    channels: neither gets a derived moment, so both get smearing."""
    state = occupations(
        _NON_METAL, _applied_ordering(compensated=compensated), _electron_count(nelec)
    )

    assert state.value.occupations == "smearing"
    assert state.value.tot_magnetization is None


@pytest.mark.parametrize(
    ("nelec", "moment", "whole"),
    [
        (32.0, 4.0, True),
        (33.0, 3.0, True),
        (32.0, 3.0, False),
        (8.0, 0.0, True),
        (9.0, 0.0, False),
        (8.0 + 1e-9, 0.0, True),  # summation noise
        (3.5, 0.5, False),  # nelup 2 is whole, neldw 1.5 is not
    ],
)
def test_whole_spin_channels_needs_both_channel_counts_whole(
    nelec: float, moment: float, whole: bool
) -> None:
    assert whole_spin_channels(nelec, moment) is whole


@pytest.mark.parametrize(
    ("moment", "nelec", "expected"),
    [
        (4.0, 32.0, "fixed"),
        (3.0, 33.0, "fixed"),
        (3.0, 32.0, "smearing"),  # nelup = 17.5: no whole spin channels
        (2.5, 32.0, "smearing"),  # not an integer
    ],
)
def test_a_human_moment_decides_fixed_only_when_both_spin_channels_are_whole(
    moment: float, nelec: float, expected: str
) -> None:
    """Fixed occupations fill nelup = (nelec + tot)/2 and neldw =
    (nelec - tot)/2 bands, both whole numbers only for an integer moment of
    the electron count's parity (#70). Any other moment still reaches the
    input, on smearing."""
    magnetic = magnetic_decision(
        _BCC_IRON,
        is_magnetic(_BCC_IRON),
        human=MagneticConfigHumanInput(tot_magnetization=moment),
    )

    state = occupations(_NON_METAL, magnetic, _electron_count(nelec))

    assert state.value.occupations == expected
    assert state.value.tot_magnetization == moment
    assert state.value.warnings == ()


@pytest.mark.parametrize(("nelec", "expected"), [(9.0, "smearing"), (8.0, "fixed")])
@pytest.mark.parametrize(
    ("spin_orbit_coupling", "mode"), [(None, "none"), (True, "noncollinear")]
)
def test_an_odd_electron_count_without_spin_gets_smearing(
    nelec: float, expected: str, spin_orbit_coupling: bool | None, mode: str
) -> None:
    """With nspin=1 fixed occupations fill NINT(nelec)/2 doubly occupied
    bands (QE 7.3 PW/src/iweights.f90), which drops an odd electron, so
    the default never pairs them (#70). A spin-orbit run without moments
    fills single spinor bands, but keeps time reversal: every band has a
    degenerate Kramers partner, and an odd count half-fills a pair."""
    magnetic = magnetic_decision(
        _SILICON,
        is_magnetic(_SILICON),
        human=MagneticConfigHumanInput(spin_orbit_coupling=spin_orbit_coupling),
    )

    state = occupations(_NON_METAL, magnetic, _electron_count(nelec))

    assert magnetic.value.spin_mode == mode
    assert magnetic.value.spin_polarized is False
    assert state.value.occupations == expected
    assert state.value.tot_magnetization is None


def test_a_magnetic_spin_orbit_non_metal_gets_fixed_without_a_moment() -> None:
    """A spin-polarized noncollinear run takes no tot_magnetization, breaks
    time reversal and fills single-electron spinor bands (#146), so neither
    the moment nor the parity matters."""
    magnetic = magnetic_decision(
        _BCC_IRON,
        is_magnetic(_BCC_IRON),
        human=MagneticConfigHumanInput(spin_orbit_coupling=True),
    )

    state = occupations(_NON_METAL, magnetic, _electron_count(33.0))

    assert magnetic.value.spin_mode == "noncollinear"
    assert magnetic.value.spin_polarized is True
    assert state.value.occupations == "fixed"
    assert state.value.tot_magnetization is None
    assert state.value.warnings == ()


def test_explicit_fixed_on_a_compensated_cell_derives_the_zero_moment() -> None:
    state = occupations(
        _NON_METAL,
        _applied_ordering(compensated=True),
        _electron_count(48.0),
        human=OccupationsHumanInput(occupations="fixed"),
    )

    assert state.value.occupations == "fixed"
    assert state.value.tot_magnetization == 0.0
    assert state.value.warnings == ()


@pytest.mark.parametrize("choice", ["smearing", "tetrahedra_opt"])
def test_smearing_and_tetrahedra_carry_the_human_moment_never_the_derived_zero(
    choice: str,
) -> None:
    """The derived 0 holds only under fixed occupations: on smearing it
    would pin a moment nobody asked for. A human moment applies to every
    collinear run."""
    human = OccupationsHumanInput(occupations=choice)
    compensated = occupations(
        _NON_METAL, _applied_ordering(compensated=True), _electron_count(48.0), human
    )
    requested = occupations(
        _NON_METAL,
        magnetic_decision(
            _BCC_IRON,
            is_magnetic(_BCC_IRON),
            human=MagneticConfigHumanInput(tot_magnetization=2.0),
        ),
        _electron_count(32.0),
        human,
    )

    assert compensated.value.occupations == choice
    assert compensated.value.tot_magnetization is None
    assert requested.value.tot_magnetization == 2.0


def test_a_metal_carries_the_human_moment() -> None:
    magnetic = magnetic_decision(
        _BCC_IRON,
        is_magnetic(_BCC_IRON),
        human=MagneticConfigHumanInput(tot_magnetization=4.0),
    )

    state = occupations(is_metal(_BCC_IRON), magnetic, _electron_count(32.0))

    assert state.value.occupations == "smearing"
    assert state.value.tot_magnetization == 4.0


@pytest.mark.parametrize(
    "electron_count",
    [
        Unavailable(reason="pseudopotential table not installed"),
        Blocked(by="pseudopotential selection failed"),
    ],
    ids=["unavailable", "blocked"],
)
def test_an_unknown_electron_count_never_blocks_occupations(electron_count) -> None:
    """A table not installed yet is a normal preview, and nbnd and the
    writer already block on the count: occupations resolves without the
    parity test. The derived 0 needs a known even count; a human integer
    moment does not."""
    unpolarized = occupations(
        _NON_METAL, magnetic_decision(_SILICON, is_magnetic(_SILICON)), electron_count
    )
    compensated = occupations(
        _NON_METAL, _applied_ordering(compensated=True), electron_count
    )
    requested = occupations(
        _NON_METAL,
        magnetic_decision(
            _BCC_IRON,
            is_magnetic(_BCC_IRON),
            human=MagneticConfigHumanInput(tot_magnetization=4.0),
        ),
        electron_count,
    )

    assert unpolarized.ok
    assert unpolarized.value.occupations == "fixed"
    assert compensated.value.occupations == "smearing"
    assert compensated.value.tot_magnetization is None
    assert requested.value.occupations == "fixed"
    assert requested.value.tot_magnetization == 4.0


_ML_METAL = Resolved("metal", Provenance(source="ml"))
"""is_metal as the ML classifier decided it."""


def test_a_human_degauss_on_a_metal_reads_human_and_names_is_metal() -> None:
    """#173: a human smearing width the decision applies reads 'human'; the
    smearing choice itself follows is_metal, which the record names, and
    keeps 'heuristic' whatever tier decided the fact."""
    state = occupations(_ML_METAL, human=OccupationsHumanInput(degauss=0.02))

    assert (state.value.occupations, state.value.degauss) == ("smearing", 0.02)
    assert state.source == "human"
    assert state.provenance.field_sources == {
        "occupations": "heuristic",
        "smearing_type": "heuristic",
        "degauss": "human",
    }
    assert state.provenance.derived_from == ("is_metal",)


def test_a_human_degauss_under_fixed_occupations_is_not_the_request_s() -> None:
    """#173: fixed occupations apply no smearing width, so a human degauss
    gets no entry and the record stays heuristic."""
    state = occupations(_NON_METAL, human=OccupationsHumanInput(degauss=0.02))

    assert state.value.occupations == "fixed"
    assert state.source == "heuristic"
    assert state.provenance.field_sources == {"occupations": "heuristic"}
    assert state.provenance.derived_from == ("is_metal",)


@pytest.mark.parametrize(
    ("magnetic", "electron_count", "expected", "derived_from"),
    [
        pytest.param(
            lambda: magnetic_decision(_SILICON, is_magnetic(_SILICON)),
            _electron_count(8.0),
            ("fixed", None),
            ("is_metal", "magnetic", "electron_count"),
            id="unpolarized-even-count",
        ),
        pytest.param(
            lambda: magnetic_decision(_BCC_IRON, is_magnetic(_BCC_IRON)),
            _electron_count(32.0),
            ("smearing", None),
            ("is_metal", "magnetic"),
            id="collinear-no-moment",
        ),
        pytest.param(
            lambda: _applied_ordering(compensated=True),
            _electron_count(48.0),
            ("fixed", 0.0),
            ("is_metal", "magnetic", "electron_count"),
            id="compensated-even-count",
        ),
        pytest.param(
            lambda: _applied_ordering(compensated=True),
            _electron_count(49.0),
            ("smearing", None),
            ("is_metal", "magnetic", "electron_count"),
            id="compensated-odd-count",
        ),
        pytest.param(
            lambda: _applied_ordering(compensated=True),
            Unavailable(reason="pseudopotential table not installed"),
            ("smearing", None),
            ("is_metal", "magnetic"),
            id="compensated-unknown-count",
        ),
        pytest.param(
            lambda: magnetic_decision(
                _BCC_IRON,
                is_magnetic(_BCC_IRON),
                human=MagneticConfigHumanInput(tot_magnetization=4.0),
            ),
            _electron_count(32.0),
            ("fixed", 4.0),
            ("is_metal", "magnetic", "electron_count"),
            id="integer-moment",
        ),
        pytest.param(
            lambda: magnetic_decision(
                _BCC_IRON,
                is_magnetic(_BCC_IRON),
                human=MagneticConfigHumanInput(tot_magnetization=2.5),
            ),
            _electron_count(32.0),
            ("smearing", 2.5),
            ("is_metal", "magnetic"),
            id="fractional-moment",
        ),
        pytest.param(
            lambda: magnetic_decision(
                _BCC_IRON,
                is_magnetic(_BCC_IRON),
                human=MagneticConfigHumanInput(spin_orbit_coupling=True),
            ),
            _electron_count(33.0),
            ("fixed", None),
            ("is_metal", "magnetic"),
            id="noncollinear",
        ),
        pytest.param(
            lambda: _applied_ordering(compensated=True, spin_orbit=True),
            _electron_count(49.0),
            ("fixed", None),
            ("is_metal", "magnetic"),
            id="noncollinear-compensated",
        ),
    ],
)
def test_a_non_metal_names_the_records_that_decided_whether_fixed_runs(
    magnetic, electron_count, expected: tuple, derived_from: tuple[str, ...]
) -> None:
    """#173: for a non-metal the magnetic record decides whether fixed
    occupations can run, and the electron count where its parity is tested
    (against 0 without spin polarization, or the 0 of a compensated
    ordering), so the heuristic record names them next to is_metal. A
    collinear run with no moment, or a spin-polarized spin-orbit run, never
    reads the count."""
    state = occupations(_NON_METAL, magnetic(), electron_count)

    assert (state.value.occupations, state.value.tot_magnetization) == expected
    assert state.source == "heuristic"
    assert state.provenance.derived_from == derived_from


def test_a_pinned_moment_names_the_magnetic_record_on_every_branch() -> None:
    """#173: the moment a decision pins is the magnetic record's admitted
    request or the 0 of its compensated ordering, which also needed an
    even count; the record names where it came from, whoever chose the
    occupations."""
    requested = magnetic_decision(
        _BCC_IRON,
        is_magnetic(_BCC_IRON),
        human=MagneticConfigHumanInput(tot_magnetization=4.0),
    )
    count = _electron_count(32.0)

    metal = occupations(_ML_METAL, requested, count)
    human = occupations(
        _ML_METAL, requested, count, OccupationsHumanInput(occupations="smearing")
    )
    llm = occupations(
        _ML_METAL, requested, count, llm=OccupationsLlmInput(occupations="fixed")
    )
    derived = occupations(
        _NON_METAL,
        _applied_ordering(compensated=True),
        _electron_count(48.0),
        OccupationsHumanInput(occupations="fixed"),
    )

    assert (metal.value.occupations, metal.value.tot_magnetization) == (
        "smearing",
        4.0,
    )
    assert metal.provenance.derived_from == ("is_metal", "magnetic")
    assert human.value.tot_magnetization == 4.0
    assert human.provenance.derived_from == ("magnetic",)
    assert (llm.value.occupations, llm.value.tot_magnetization) == ("fixed", 4.0)
    assert llm.provenance.derived_from == ("magnetic",)
    assert (derived.value.occupations, derived.value.tot_magnetization) == (
        "fixed",
        0.0,
    )
    assert derived.source == "human"
    assert derived.provenance.derived_from == ("magnetic", "electron_count")


def test_a_chosen_occupations_reads_its_tier_and_no_fact() -> None:
    human = occupations(
        _ML_METAL,
        human=OccupationsHumanInput(occupations="smearing", smearing_type="mp"),
    )
    llm = occupations(
        _ML_METAL,
        human=OccupationsHumanInput(degauss=0.02),
        llm=OccupationsLlmInput(occupations="smearing"),
    )

    assert human.provenance.field_sources == {
        "occupations": "human",
        "smearing_type": "human",
        "degauss": "heuristic",
    }
    assert human.provenance.derived_from == ()
    # The llm branch reads no human smearing value, so none reads human.
    assert llm.value.degauss == 0.01
    assert llm.source == "llm"
    assert llm.provenance.field_sources == {
        "occupations": "llm",
        "smearing_type": "heuristic",
        "degauss": "heuristic",
    }
    assert llm.provenance.derived_from == ()


_PROTOCOL = OccupationsProtocol(
    occupations="tetrahedra_opt", note="A task protocol's nscf occupations."
)
"""A step's protocol occupations, as the dos task's nscf step gets them."""


@pytest.mark.parametrize("metallicity", [_ML_METAL, _NON_METAL], ids=["metal", "non"])
def test_a_protocol_occupations_outranks_the_llm_and_the_is_metal_heuristic(
    metallicity,
) -> None:
    """#174: a step's protocol occupations rank above an llm choice and the
    is_metal rule, and read 'heuristic' with the protocol as their note, not
    'human'."""
    state = occupations(
        metallicity,
        llm=OccupationsLlmInput(occupations="smearing"),
        protocol=_PROTOCOL,
    )

    assert state.value.occupations == "tetrahedra_opt"
    assert state.value.smearing_type is None
    assert state.value.degauss is None
    assert state.provenance == Provenance(
        source="heuristic",
        source_note="A task protocol's nscf occupations.",
        field_sources={"occupations": "heuristic"},
    )


def test_a_human_occupations_outranks_the_protocol() -> None:
    state = occupations(
        _NON_METAL,
        human=OccupationsHumanInput(occupations="smearing", degauss=0.02),
        protocol=_PROTOCOL,
    )

    assert (state.value.occupations, state.value.degauss) == ("smearing", 0.02)
    assert state.provenance == Provenance(
        source="human",
        field_sources={
            "occupations": "human",
            "smearing_type": "heuristic",
            "degauss": "human",
        },
    )


def test_a_human_degauss_is_not_applied_under_the_protocol_s_tetrahedra() -> None:
    """#174: a smearing width alone does not displace the protocol's
    occupations; tetrahedra_opt applies no width, so it gets no entry."""
    state = occupations(
        _ML_METAL,
        human=OccupationsHumanInput(smearing_type="mp", degauss=0.02),
        protocol=_PROTOCOL,
    )

    assert state.value.occupations == "tetrahedra_opt"
    assert state.value.degauss is None
    assert state.source == "heuristic"
    assert state.provenance.field_sources == {"occupations": "heuristic"}


def test_a_smearing_protocol_applies_the_human_smearing_width() -> None:
    protocol = OccupationsProtocol(occupations="smearing", note="Smearing protocol.")

    state = occupations(
        _NON_METAL, human=OccupationsHumanInput(degauss=0.02), protocol=protocol
    )

    assert (state.value.occupations, state.value.smearing_type) == ("smearing", "cold")
    assert state.value.degauss == 0.02
    assert state.provenance == Provenance(
        source="human",
        source_note="Smearing protocol.",
        field_sources={
            "occupations": "heuristic",
            "smearing_type": "heuristic",
            "degauss": "human",
        },
    )


# #118: bands.x stops on the two Fermi energies any tot_magnetization writes
# (QE 7.3 PP/src/bands.f90:114-116), so the band task's scf derives no moment,
# and its bands step takes the scf step's occupations.
_UNPINNED = UnpinnedMomentProtocol(note="A task protocol that pins no moment.")


def test_an_unpinned_moment_protocol_gives_a_compensated_afm_smearing() -> None:
    """Under the protocol a compensated AFM non-metal derives no 0, so it
    takes the smearing fallback, and the record's note says why; without the
    protocol it keeps fixed occupations with a 0 moment (#138)."""
    magnetic = _applied_ordering(compensated=True)
    count = _electron_count(48.0)

    unpinned = occupations(_NON_METAL, magnetic, count, unpinned=_UNPINNED)
    pinned = occupations(_NON_METAL, magnetic, count)

    assert unpinned.value == OccupationsDecision(
        occupations="smearing", smearing_type="cold", degauss=0.01
    )
    assert unpinned.provenance == Provenance(
        source="heuristic",
        source_note="A task protocol that pins no moment.",
        field_sources={
            "occupations": "heuristic",
            "smearing_type": "heuristic",
            "degauss": "heuristic",
        },
        derived_from=("is_metal", "magnetic"),
    )
    assert (pinned.value.occupations, pinned.value.tot_magnetization) == ("fixed", 0.0)
    assert pinned.provenance.source_note is None


@pytest.mark.parametrize(
    ("metallicity", "magnetic", "human", "expected", "note"),
    [
        pytest.param(
            _NON_METAL,
            lambda: magnetic_decision(
                _BCC_IRON,
                is_magnetic(_BCC_IRON),
                human=MagneticConfigHumanInput(tot_magnetization=4.0),
            ),
            None,
            ("fixed", 4.0),
            None,
            id="human-moment",
        ),
        pytest.param(
            _ML_METAL,
            lambda: _applied_ordering(compensated=True),
            None,
            ("smearing", None),
            None,
            id="compensated-metal",
        ),
        pytest.param(
            _NON_METAL,
            lambda: _applied_ordering(compensated=True),
            OccupationsHumanInput(occupations="fixed"),
            ("fixed", None),
            "A task protocol that pins no moment.",
            id="explicit-fixed",
        ),
    ],
)
def test_the_unpinned_note_appears_where_the_protocol_changed_the_decision(
    metallicity, magnetic, human, expected: tuple, note: str | None
) -> None:
    """A human moment is still carried, and a metal gets smearing either way,
    so neither names the protocol; an explicit fixed loses the derived 0,
    which the gate then refuses, and the note says why."""
    state = occupations(
        metallicity, magnetic(), _electron_count(48.0), human, unpinned=_UNPINNED
    )

    assert (state.value.occupations, state.value.tot_magnetization) == expected
    assert state.provenance.source_note == note


@pytest.mark.parametrize(
    ("human", "expected"),
    [
        pytest.param(None, ("smearing", None), id="heuristic"),
        pytest.param(
            OccupationsHumanInput(occupations="fixed"),
            ("fixed", None),
            id="explicit-fixed",
        ),
    ],
)
def test_the_band_task_s_note_holds_for_either_outcome(human, expected: tuple) -> None:
    """The band task's scf note is the source_note of both the smearing a
    compensated AFM non-metal falls back to and an explicit fixed left with
    no moment, which the gate refuses, so it gives the reason and claims
    neither scheme."""
    unpinned = BAND_SCF_PROTOCOL.unpinned_moment
    magnetic = _applied_ordering(compensated=True)

    state = occupations(
        _NON_METAL, magnetic, _electron_count(48.0), human, unpinned=unpinned
    )

    assert (state.value.occupations, state.value.tot_magnetization) == expected
    assert state.provenance.source_note == unpinned.note
    assert "smearing" not in unpinned.note


@pytest.mark.parametrize(
    "scf",
    [
        pytest.param(
            lambda: occupations(
                _ML_METAL,
                human=OccupationsHumanInput(occupations="smearing", degauss=0.02),
            ),
            id="human-smearing",
        ),
        pytest.param(
            lambda: occupations(
                _NON_METAL,
                magnetic_decision(_BCC_IRON, is_magnetic(_BCC_IRON)),
                _electron_count(32.0),
                OccupationsHumanInput(occupations="fixed"),
            ),
            id="fixed-without-a-moment",
        ),
    ],
)
def test_bands_occupations_are_the_scf_step_s(scf) -> None:
    """The bands step follows the scf step's decision, the record it was
    derived from, so it reads heuristic; the scf record keeps its own
    warnings."""
    scf_state = scf()

    state = bands_occupations(scf_state)

    assert state.value == replace(scf_state.value, warnings=())
    assert state.source == "heuristic"
    assert set(state.provenance.field_sources.values()) == {"heuristic"}
    assert state.provenance.derived_from == ("occupations",)
    assert state.provenance.source_note is None


def test_bands_occupations_write_a_tetrahedra_scf_as_cold_smearing() -> None:
    """pw.x stops on tetrahedra along a k-point path (QE 7.3
    PW/src/setup.f90:598), while a bands run only weights its bands at the
    scf's Fermi energy (PW/src/non_scf.f90:104-105): the bands step gets
    cold smearing at 0.01 Ry, with the moment carried for the gate."""
    magnetic = magnetic_decision(
        _BCC_IRON,
        is_magnetic(_BCC_IRON),
        human=MagneticConfigHumanInput(tot_magnetization=4.0),
    )
    scf = occupations(
        _ML_METAL,
        magnetic,
        _electron_count(32.0),
        OccupationsHumanInput(occupations="tetrahedra_opt"),
    )

    state = bands_occupations(scf)

    assert state.value == OccupationsDecision(
        occupations="smearing",
        smearing_type="cold",
        degauss=0.01,
        tot_magnetization=4.0,
    )
    assert state.provenance.field_sources == {
        "occupations": "heuristic",
        "smearing_type": "heuristic",
        "degauss": "heuristic",
    }
    assert state.provenance.derived_from == ("occupations",)
    note = state.provenance.source_note
    assert "setup.f90:598" in note
    assert "non_scf.f90:104-105" in note


def test_bands_occupations_stay_blocked_with_the_scf_step() -> None:
    state = bands_occupations(occupations(Blocked(by="synthetic failure")))

    assert isinstance(state, Blocked)
    assert state.root_cause() == "synthetic failure"
