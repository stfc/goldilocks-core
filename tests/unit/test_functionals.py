from __future__ import annotations

import pytest

from goldilocks_core.functionals import normalize_functional_label


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
