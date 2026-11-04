from __future__ import annotations

from decimal import Decimal

import pytest
from support import geometry_facts

from goldilocks_core.advisors.convergence import (
    ConvergenceHumanInput,
    ConvergenceLlmInput,
    convergence,
)
from goldilocks_core.advisors.hubbard_u import HubbardU, HubbardUDecision
from goldilocks_core.resolution import Blocked, Provenance, Resolved, Unavailable

_FROZEN_NS = "convergence.mixing_fixed_ns_freezes_hubbard_occupations"


def _hubbard(*u_values: HubbardU) -> Resolved[HubbardUDecision]:
    return Resolved(HubbardUDecision(u_values=u_values), Provenance(source="heuristic"))


_NICKEL_U = _hubbard(HubbardU("Ni", "3d", 6.2, "human"))
_NO_U = _hubbard()


def test_thresholds_scale_with_nat_as_the_decimal_the_formula_names() -> None:
    """conv_thr = nat * 0.2e-9 and etot_conv_thr = nat * 1e-5, recorded as
    exactly that decimal: the float product recorded and wrote
    2.8000000000000003e-09 for nat 14 (#178)."""
    for nat in range(1, 201):
        state = convergence(nat=nat)

        assert state.ok
        assert Decimal(repr(state.value.conv_thr)) == nat * Decimal("0.2e-9"), nat
        assert Decimal(repr(state.value.etot_conv_thr)) == nat * Decimal("1e-5"), nat
    assert repr(convergence(nat=14).value.conv_thr) == "2.8e-09"
    assert repr(convergence(nat=12).value.etot_conv_thr) == "0.00012"


def test_defaults_match_v1s_flat_constants() -> None:
    state = convergence(nat=4)

    assert state.value.mixing_beta == 0.4
    assert state.value.electron_maxstep == 80


def _geometry(dimensionality: str, vacuum_axes: tuple[str, ...] = ()):
    return Resolved(
        geometry_facts(dimensionality, vacuum_axes), Provenance(source="heuristic")
    )


@pytest.mark.parametrize(
    ("dimensionality", "vacuum_axes"),
    [("2d", ("c",)), ("1d", ("a", "b")), ("molecule", ("a", "b", "c"))],
    ids=["slab", "wire", "isolated"],
)
def test_vacuum_along_any_axis_switches_mixing_mode_to_local_tf(
    dimensionality: str, vacuum_axes: tuple[str, ...]
) -> None:
    """F26: plain mixing struggles on a cell with a vacuum region, which
    local-TF's Thomas-Fermi screening handles better. A wire has a vacuum
    region too (#160)."""
    state = convergence(nat=6, geometry=_geometry(dimensionality, vacuum_axes))

    assert state.value.mixing_mode == "local-TF"


def test_vacuum_decides_local_tf_whatever_the_rank() -> None:
    """A lone atom bonded to its own images ranks '3d' in a box."""
    state = convergence(nat=1, geometry=_geometry("3d", ("a", "b", "c")))

    assert state.value.mixing_mode == "local-TF"


@pytest.mark.parametrize("dimensionality", ["3d", "2d", "1d", "molecule"])
def test_a_cell_without_vacuum_keeps_plain_mixing_whatever_its_rank(
    dimensionality: str,
) -> None:
    """#160: bulk graphite ranks '2d' and CO2 dry ice 'molecule', but neither
    has a vacuum region. On SCARF, local-TF and plain mixing gave the same
    energies and SCF iteration counts for bulk MgB2 and graphite."""
    state = convergence(nat=6, geometry=_geometry(dimensionality))

    assert state.value.mixing_mode == "plain"


def test_unavailable_geometry_keeps_plain_mixing() -> None:
    state = convergence(nat=6, geometry=Unavailable(reason="synthetic failure"))

    assert state.value.mixing_mode == "plain"


def test_mixing_fixed_ns_is_unset_by_default() -> None:
    """#127: pw.x can report convergence while mixing_fixed_ns still holds
    the Hubbard occupation matrix at its starting value, so nothing sets
    it by default; unset leaves QE's own default of 0."""
    state = convergence(nat=5)

    assert state.value.mixing_fixed_ns is None
    assert state.provenance.field_sources["mixing_fixed_ns"] == "heuristic"


def test_human_mixing_fixed_ns_is_used_as_given() -> None:
    state = convergence(nat=5, human=ConvergenceHumanInput(mixing_fixed_ns=10))

    assert state.value.mixing_fixed_ns == 10
    assert state.provenance.field_sources["mixing_fixed_ns"] == "human"


@pytest.mark.parametrize(
    ("human", "llm", "value"),
    [
        pytest.param(ConvergenceHumanInput(mixing_fixed_ns=50), None, 50, id="human"),
        pytest.param(None, ConvergenceLlmInput(mixing_fixed_ns=1), 1, id="llm"),
    ],
)
def test_a_nonzero_mixing_fixed_ns_with_an_applied_u_is_flagged(
    human: ConvergenceHumanInput | None, llm: ConvergenceLlmInput | None, value: int
) -> None:
    """#166: the +U-specific part of the decision keys on the resolved
    Hubbard decision. pw.x holds the occupation matrix for the first
    mixing_fixed_ns iterations and can report convergence inside that
    window, so the value is kept as given and flagged."""
    state = convergence(nat=2, hubbard=_NICKEL_U, human=human, llm=llm)

    assert state.value.mixing_fixed_ns == value
    (warning,) = state.value.warnings
    assert (warning.code, warning.level, warning.category) == (
        _FROZEN_NS,
        "warning",
        "convergence",
    )
    assert f"mixing_fixed_ns = {value} holds the Hubbard occupation" in warning.message
    assert f"first {value} SCF iterations" in warning.message
    assert "not self-consistent DFT+U results" in warning.message


def test_mixing_fixed_ns_without_an_applied_u_is_kept_unflagged() -> None:
    """pw.x reads mixing_fixed_ns only under lda_plus_u (QE 7.3
    PW/src/electrons.f90:748-815), so with no U the value is inert: kept
    as given, with no frozen-occupation warning."""
    state = convergence(
        nat=2, hubbard=_NO_U, human=ConvergenceHumanInput(mixing_fixed_ns=50)
    )

    assert state.value.mixing_fixed_ns == 50
    assert state.value.warnings == ()


@pytest.mark.parametrize(
    "hubbard",
    [
        pytest.param(None, id="not-supplied"),
        pytest.param(_NO_U, id="no-u"),
        pytest.param(_NICKEL_U, id="u"),
        pytest.param(Blocked(by="synthetic failure"), id="blocked"),
        pytest.param(Unavailable(reason="synthetic failure"), id="unavailable"),
    ],
)
def test_no_override_sets_nothing_and_warns_about_nothing(hubbard) -> None:
    state = convergence(nat=2, hubbard=hubbard)

    assert state.value.mixing_fixed_ns is None
    assert state.value.warnings == ()


def test_an_explicit_zero_freezes_nothing_so_carries_no_warning() -> None:
    """0 is QE's own default: the occupation matrix is free from the first
    iteration."""
    state = convergence(
        nat=2, hubbard=_NICKEL_U, human=ConvergenceHumanInput(mixing_fixed_ns=0)
    )

    assert state.value.mixing_fixed_ns == 0
    assert state.value.warnings == ()


@pytest.mark.parametrize(
    "hubbard",
    [
        pytest.param(Blocked(by="synthetic failure"), id="blocked"),
        pytest.param(Unavailable(reason="synthetic failure"), id="unavailable"),
    ],
)
def test_an_unresolved_hubbard_decision_neither_blocks_nor_warns(hubbard) -> None:
    state = convergence(
        nat=2, hubbard=hubbard, human=ConvergenceHumanInput(mixing_fixed_ns=50)
    )

    assert state.ok
    assert state.value.mixing_fixed_ns == 50
    assert state.value.warnings == ()


def test_human_conv_thr_override_is_used_directly_not_scaled() -> None:
    state = convergence(nat=100, human=ConvergenceHumanInput(conv_thr=1e-8))

    assert state.value.conv_thr == 1e-8
    assert state.source == "human"


def test_human_can_override_a_single_field_others_keep_their_default() -> None:
    state = convergence(nat=10, human=ConvergenceHumanInput(mixing_beta=0.2))

    assert state.value.mixing_beta == 0.2
    assert state.value.conv_thr == 2e-9
    assert state.source == "human"


def test_llm_can_adjust_mixing_knobs_but_not_conv_thr() -> None:
    state = convergence(
        nat=10, llm=ConvergenceLlmInput(mixing_fixed_ns=80, electron_maxstep=120)
    )

    assert state.value.mixing_fixed_ns == 80
    assert state.value.electron_maxstep == 120
    assert state.value.conv_thr == 2e-9
    assert state.source == "llm"


def test_no_overrides_gives_heuristic_source() -> None:
    state = convergence(nat=10)

    assert state.source == "heuristic"


def test_every_convergence_field_reads_the_tier_that_set_it() -> None:
    """#173: one entry per applied field; the record's source is the
    highest of them."""
    state = convergence(
        nat=10,
        human=ConvergenceHumanInput(mixing_beta=0.3),
        llm=ConvergenceLlmInput(mixing_beta=0.2, electron_maxstep=120),
    )

    assert state.source == "human"
    assert state.provenance.field_sources == {
        "conv_thr": "heuristic",
        "etot_conv_thr": "heuristic",
        "mixing_beta": "human",
        "electron_maxstep": "llm",
        "mixing_mode": "heuristic",
        "mixing_fixed_ns": "heuristic",
    }
    assert state.provenance.derived_from == ()
