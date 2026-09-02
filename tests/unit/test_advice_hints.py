from goldilocks_core.advice._hints import has_hint
from goldilocks_core.calculation import (
    ConvergenceHints,
    PseudoHints,
    SmearingHints,
    SpinHints,
)


def test_has_hint_is_false_for_an_empty_view() -> None:
    assert has_hint(SmearingHints()) is False
    assert has_hint(ConvergenceHints()) is False
    assert has_hint(PseudoHints()) is False
    assert has_hint(SpinHints()) is False


def test_has_hint_is_true_when_any_field_is_set() -> None:
    assert has_hint(SmearingHints(smearing_type="cold", smearing_width_ry=0.01)) is True
    assert has_hint(ConvergenceHints(conv_thr=1e-8)) is True
    assert has_hint(PseudoHints(pseudo_type="NC")) is True
    assert has_hint(SpinHints(spin_orbit_coupling=True)) is True
