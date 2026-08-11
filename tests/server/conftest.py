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
def pseudo_metadata() -> dict[str, object]:
    """Return metadata sufficient to render a silicon QE input."""
    return {
        "filepath": "/pseudo/Si.UPF",
        "filename": "Si.UPF",
        "header_format": "attr",
        "library": "SSSP",
        "source_set": "efficiency",
        "element": "Si",
        "pseudo_type": "NC",
        "functional": "PBEsol",
        "relativistic": "scalar",
        "z_valence": 4.0,
        "is_sssp": True,
        "sssp_recommended_cutoff": {
            "ecutwfc_ry": 30.0,
            "ecutrho_ry": 120.0,
        },
    }


@pytest.fixture
def request_body(
    sample_structure_path: str, pseudo_metadata: dict[str, object]
) -> dict[str, object]:
    """Return a model-free transport request body."""
    return {
        "structure": sample_structure_path,
        "hints": {"k_grid": [3, 3, 3]},
        "pseudo_metadata": [pseudo_metadata],
    }


@pytest.fixture
def test_service() -> Iterator[CoreService]:
    """Yield a Core service and close it after the test."""
    service = CoreService()
    yield service
    service.close()
