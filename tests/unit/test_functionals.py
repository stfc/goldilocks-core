from __future__ import annotations

from goldilocks_core.functionals import normalize_functional_label


def test_normalize_functional_rejects_non_string_input() -> None:
    assert normalize_functional_label(123) is None


def test_normalize_functional_rejects_empty_string() -> None:
    assert normalize_functional_label("   ") is None
