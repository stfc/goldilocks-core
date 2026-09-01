from __future__ import annotations

from collections.abc import Iterator

import pytest
from pymatgen.core import Structure

from goldilocks_core.examples import structure
from goldilocks_core.runtime import CoreService


@pytest.fixture
def sample_structure_path() -> str:
    """Return the bundled silicon structure path."""
    return str(structure("Si.cif"))


@pytest.fixture
def sample_structure_text(sample_structure_path: str) -> str:
    """Return the bundled silicon structure as inline CIF text."""
    return Structure.from_file(sample_structure_path).to(fmt="cif")


@pytest.fixture
def request_body(sample_structure_text: str) -> dict[str, object]:
    """Return a transport request body carrying only the calculation."""
    return {
        "structure": sample_structure_text,
        "hints": {"k_grid": [3, 3, 3]},
    }


@pytest.fixture
def test_service() -> Iterator[CoreService]:
    """Yield a Core service and close it after the test."""
    service = CoreService()
    yield service
    service.close()
