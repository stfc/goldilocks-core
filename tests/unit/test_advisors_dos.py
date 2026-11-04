from __future__ import annotations

import pytest
from pydantic import ValidationError

from goldilocks_core.advisors.dos import (
    DEFAULT_DELTA_E,
    DEFAULT_NGAUSS,
    DosHumanInput,
    DosLlmInput,
    dos_settings,
)
from goldilocks_core.advisors.occupations import OccupationsDecision
from goldilocks_core.resolution import Blocked, Provenance, Resolved

_SMEARING = Resolved(
    OccupationsDecision(occupations="smearing", smearing_type="cold", degauss=0.02),
    Provenance(source="heuristic"),
)
_TETRAHEDRA = Resolved(
    OccupationsDecision(occupations="tetrahedra_opt", smearing_type=None, degauss=None),
    Provenance(source="heuristic"),
)
_FIXED = Resolved(
    OccupationsDecision(occupations="fixed", smearing_type=None, degauss=None),
    Provenance(source="heuristic"),
)


def test_defaults_match_qe_and_aiida_documented_values() -> None:
    state = dos_settings(_TETRAHEDRA)

    assert state.ok
    assert state.value.delta_e == DEFAULT_DELTA_E
    assert state.value.ngauss == DEFAULT_NGAUSS
    assert state.value.emin is None
    assert state.value.emax is None
    assert state.source == "heuristic"


def test_broadening_inherits_the_nscf_steps_own_smearing_width() -> None:
    state = dos_settings(_SMEARING)

    assert state.value.broadening == 0.02


def test_broadening_stays_none_when_nscf_used_a_tetrahedron_method() -> None:
    """No smearing width exists for a tetrahedron-method nscf step --
    dos.x's own bz_sum default already switches to tetrahedron
    integration whenever degauss is unset, so leaving it None here is
    correct, not a gap."""
    state = dos_settings(_TETRAHEDRA)

    assert state.value.broadening is None


def test_human_overrides_every_field() -> None:
    state = dos_settings(
        _SMEARING,
        human=DosHumanInput(
            emin=-5.0, emax=5.0, delta_e=0.005, broadening=0.01, ngauss=1
        ),
    )

    assert state.value.emin == -5.0
    assert state.value.emax == 5.0
    assert state.value.delta_e == 0.005
    assert state.value.broadening == 0.01
    assert state.value.ngauss == 1
    assert state.source == "human"


def test_llm_delta_e_used_when_no_human_override() -> None:
    state = dos_settings(_SMEARING, llm=DosLlmInput(delta_e=0.02))

    assert state.value.delta_e == 0.02
    assert state.source == "llm"


def test_blocked_nscf_occupations_propagates_as_blocked() -> None:
    state = dos_settings(Blocked(by="synthetic failure"))

    assert not state.ok
    assert state.root_cause() == "synthetic failure"


class TestDosHumanInputValidation:
    """#154: dos.x's settings became reachable from a request, so they are
    validated where every other request value is: dos.x accepts ngauss -99
    (Fermi-Dirac), -1 (cold) and 0..10 (Methfessel-Paxton order) and stops
    on any other (QE 7.3 Modules/w0gauss.f90:43-61); DeltaE and degauss are
    widths, and Emin/Emax a window."""

    @pytest.mark.parametrize("ngauss", [-99, -1, 0, 2, 10])
    def test_dos_x_smearing_orders_are_accepted(self, ngauss: int) -> None:
        assert DosHumanInput(ngauss=ngauss).ngauss == ngauss

    @pytest.mark.parametrize("ngauss", [11, -2, -98])
    def test_other_smearing_orders_are_refused(self, ngauss: int) -> None:
        with pytest.raises(ValidationError, match="ngauss"):
            DosHumanInput(ngauss=ngauss)

    @pytest.mark.parametrize("field", ["delta_e", "broadening"])
    @pytest.mark.parametrize("value", [0.0, -0.01])
    def test_widths_must_be_positive(self, field: str, value: float) -> None:
        with pytest.raises(ValidationError, match=field):
            DosHumanInput(**{field: value})

    def test_llm_delta_e_must_be_positive(self) -> None:
        with pytest.raises(ValidationError, match="delta_e"):
            DosLlmInput(delta_e=0.0)

    @pytest.mark.parametrize(("emin", "emax"), [(5.0, 5.0), (6.0, -6.0)])
    def test_an_empty_or_inverted_window_is_refused(
        self, emin: float, emax: float
    ) -> None:
        with pytest.raises(ValidationError, match="emin"):
            DosHumanInput(emin=emin, emax=emax)

    def test_one_window_edge_alone_is_accepted(self) -> None:
        assert DosHumanInput(emax=-20.0).emax == -20.0


class TestDosProvenance:
    """#154: the record's source followed delta_e only, so a requested
    ngauss read 'heuristic'."""

    def test_a_requested_ngauss_reads_human_in_field_sources(self) -> None:
        state = dos_settings(_SMEARING, human=DosHumanInput(ngauss=1))

        assert state.provenance == Provenance(
            source="human",
            field_sources={
                "emin": "heuristic",
                "emax": "heuristic",
                "delta_e": "heuristic",
                "broadening": "heuristic",
                "ngauss": "human",
            },
        )

    def test_an_llm_delta_e_reads_llm_beside_the_heuristic_rest(self) -> None:
        state = dos_settings(_TETRAHEDRA, llm=DosLlmInput(delta_e=0.02))

        assert state.provenance.source == "llm"
        assert state.provenance.field_sources["delta_e"] == "llm"
        assert state.provenance.field_sources["ngauss"] == "heuristic"


class TestNgaussNeedsABroadeningWidth:
    """dos.x reads the ngauss of its input only beside a degauss there (QE
    7.3 PP/src/dos.f90:161-163): after a tetrahedron nscf step it integrates
    with tetrahedra (:129), after fixed occupations it broadens with a plain
    Gaussian of width DeltaE (:172-174). A requested ngauss with no width
    was written, recorded as the request's and ignored."""

    @pytest.mark.parametrize(
        ("nscf", "occupations"),
        [(_TETRAHEDRA, "tetrahedra_opt"), (_FIXED, "fixed")],
    )
    def test_without_a_width_a_requested_ngauss_blocks_the_record(
        self, nscf, occupations: str
    ) -> None:
        state = dos_settings(nscf, human=DosHumanInput(ngauss=1))

        assert isinstance(state, Blocked)
        assert state.root_cause() == (
            "ngauss=1 would have no effect: dos.x reads ngauss only with a "
            f"broadening width, and the nscf step's {occupations} occupations "
            "give none; set broadening as well, or drop ngauss."
        )

    def test_a_requested_broadening_carries_it_after_tetrahedra(self) -> None:
        state = dos_settings(
            _TETRAHEDRA, human=DosHumanInput(ngauss=1, broadening=0.01)
        )

        assert (state.value.ngauss, state.value.broadening) == (1, 0.01)
        assert state.provenance.field_sources["ngauss"] == "human"

    def test_the_nscf_smearing_width_carries_it(self) -> None:
        state = dos_settings(_SMEARING, human=DosHumanInput(ngauss=-1))

        assert (state.value.ngauss, state.value.broadening) == (-1, 0.02)

    def test_the_default_ngauss_needs_no_width(self) -> None:
        assert dos_settings(_FIXED).value.ngauss == DEFAULT_NGAUSS
