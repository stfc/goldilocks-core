"""v2 epic 3 (#4): failures.py had no dedicated test file before this,
only incidental coverage through the concrete subclasses that use it.
These tests exercise ExpectedFailure itself, plus the three-way
input/dependency/local classification through real subclasses already
in the codebase -- not synthetic stand-ins."""

from __future__ import annotations

from goldilocks_core.assets.pseudopotentials.importers import PseudoImportError
from goldilocks_core.assets.store import AssetCorrupt
from goldilocks_core.failures import ExpectedFailure
from goldilocks_core.inputs.structure import StructureInputError


def test_category_defaults_to_input() -> None:
    class _Fixture(ExpectedFailure):
        kind = "fixture_failure"

    error = _Fixture("boom")

    assert error.category == "input"


def test_public_error_exposes_only_kind_and_message() -> None:
    class _Fixture(ExpectedFailure):
        kind = "fixture_failure"

    error = _Fixture("something the caller may see")

    assert error.public_error() == {
        "kind": "fixture_failure",
        "message": "something the caller may see",
    }


def test_structure_input_error_is_the_input_category() -> None:
    error = StructureInputError("bad structure")

    assert error.category == "input"
    assert error.public_error()["kind"] == "invalid_structure"


def test_asset_corrupt_is_the_dependency_category() -> None:
    error = AssetCorrupt("installed manifest is invalid")

    assert error.category == "dependency"


def test_pseudo_import_error_is_the_local_category() -> None:
    error = PseudoImportError("cutoff metadata is ambiguous")

    assert error.category == "local"
