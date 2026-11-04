from __future__ import annotations

from support import geometry_facts

from goldilocks_core.advisors.vdw_method import (
    WARNING_CATALOGUE,
    VdwMethodHumanInput,
    VdwMethodLlmInput,
    vdw_method,
)
from goldilocks_core.resolution import Blocked, Provenance, Resolved


def _geometry(dimensionality: str):
    return Resolved(geometry_facts(dimensionality), Provenance(source="heuristic"))


def test_bulk_3d_gets_no_vdw_correction() -> None:
    state = vdw_method(_geometry("3d"), "PBEsol")

    assert state.ok
    assert state.value.use_vdw is False
    assert state.value.method is None


def test_low_dimensional_structure_defaults_to_d3bj() -> None:
    state = vdw_method(_geometry("2d"), "PBEsol")

    assert state.value.use_vdw is True
    assert state.value.method == "d3bj"
    assert state.value.warnings == ()


def test_pbe_molecular_crystal_defaults_to_d3bj() -> None:
    state = vdw_method(_geometry("molecule"), "PBE")

    assert state.value.use_vdw is True
    assert state.value.method == "d3bj"
    assert state.value.warnings == ()


def test_lda_on_a_low_dimensional_structure_gets_no_d3_and_a_warning() -> None:
    """#141: QE's DFT-D3 has no D3(BJ) parameters for LDA, so pw.x would
    stop with 'functional name unknown'."""
    state = vdw_method(_geometry("2d"), "LDA")

    assert state.ok
    assert state.source == "heuristic"
    assert state.value.use_vdw is False
    assert state.value.method is None
    (warning,) = state.value.warnings
    assert warning.code == "vdw.d3bj_unavailable_for_functional"
    assert warning.level == "warning"
    assert warning.category == "vdw"
    assert "'LDA'" in warning.message


def test_the_d3bj_warning_is_catalogued_with_its_level() -> None:
    (warning,) = vdw_method(_geometry("1d"), "LDA").value.warnings
    catalogued = {entry.code: entry for entry in WARNING_CATALOGUE}

    assert catalogued[warning.code].level == warning.level
    assert catalogued[warning.code].category == warning.category


def test_lda_on_a_3d_structure_gets_no_d3_and_no_warning() -> None:
    state = vdw_method(_geometry("3d"), "LDA")

    assert state.value.use_vdw is False
    assert state.value.warnings == ()


def test_a_human_use_vdw_with_lda_resolves_as_requested() -> None:
    """Refusing the pairing is ``checks.check_all``'s job, not this
    advisor's."""
    state = vdw_method(_geometry("2d"), "LDA", human=VdwMethodHumanInput(use_vdw=True))

    assert state.source == "human"
    assert state.value.use_vdw is True
    assert state.value.method == "d3bj"
    assert state.value.warnings == ()


def test_vdw_inclusive_functional_skips_the_correction_even_when_low_dimensional() -> (
    None
):
    state = vdw_method(_geometry("2d"), "vdW-DF")

    assert state.value.use_vdw is False
    assert state.value.method is None
    assert state.value.warnings == ()


def test_vdw_inclusive_functional_warns_if_a_method_was_explicitly_requested() -> None:
    state = vdw_method(
        _geometry("2d"),
        "vdW-DF",
        human=VdwMethodHumanInput(method="d3bj"),
    )

    # human.use_vdw is still None here, so the vdw-inclusive-functional guard
    # runs -- but human.method being set should still surface a warning.
    assert state.value.use_vdw is False
    assert len(state.value.warnings) == 1
    assert "double-counting" in state.value.warnings[0].message
    assert state.value.warnings[0].code == "vdw.double_counting_avoided"


def test_human_override_wins_over_heuristic() -> None:
    state = vdw_method(
        _geometry("3d"), "PBEsol", human=VdwMethodHumanInput(use_vdw=True)
    )

    assert state.value.use_vdw is True
    assert state.value.method == "d3bj"
    assert state.source == "human"


def test_llm_override_is_used_when_no_human_override_is_given() -> None:
    state = vdw_method(_geometry("2d"), "PBEsol", llm=VdwMethodLlmInput(use_vdw=False))

    assert state.value.use_vdw is False
    assert state.source == "llm"


def test_blocked_geometry_propagates() -> None:
    state = vdw_method(Blocked(by="synthetic failure"), "PBEsol")

    assert not state.ok
    assert state.status == "blocked"
    assert state.root_cause() == "synthetic failure"
