from __future__ import annotations

import pytest

from goldilocks_core.functionals import (
    has_d3bj_parameters,
    normalize_functional_label,
)


def test_normalize_functional_rejects_non_string_input() -> None:
    assert normalize_functional_label(123) is None


def test_normalize_functional_rejects_empty_string() -> None:
    assert normalize_functional_label("   ") is None


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("SLA PW NOGX NOGC", "LDA"),
        ("SLA PW PBE PBE PBE", "PBE"),
        ("SLA PW PBX PBC PBE", "PBE"),
        ("SLA PW PSX PSC", "PBEsol"),
        ("SLA PW PSX PSC PBEsol", "PBEsol"),
    ],
)
def test_normalize_functional_recognizes_upstream_component_labels(
    label: str, expected: str
) -> None:
    assert normalize_functional_label(label) == expected


@pytest.mark.parametrize(
    ("functional", "expected"),
    [
        ("PBE", True),
        ("PBEsol", True),
        ("LDA", False),
        ("hybrid", False),
        ("revPBE", False),
    ],
)
def test_only_pbe_and_pbesol_have_d3bj_parameters(
    functional: str, expected: bool
) -> None:
    """#141: QE 7.3's D3(BJ) table (dft-d3/core.f90:286-531) has pbe and
    pbesol but neither LDA short name (pz, pw). A label Goldilocks does not
    recognise counts as unparameterised, even one dft-d3 knows (revPBE)."""
    assert has_d3bj_parameters(functional) is expected
