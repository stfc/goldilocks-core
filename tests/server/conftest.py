from __future__ import annotations

from collections.abc import Iterator

import pytest
from pymatgen.core import Structure

from goldilocks_core.examples import structure
from goldilocks_core.runtime import Service


@pytest.fixture
def sample_structure_path() -> str:
    return str(structure("Si.cif"))


@pytest.fixture
def sample_structure_text(sample_structure_path: str) -> str:
    return Structure.from_file(sample_structure_path).to(fmt="cif")


@pytest.fixture
def pseudo_metadata() -> dict[str, object]:
    return {
        "filepath": "/pseudo/Si.UPF",
        "filename": "Si.UPF",
        "header_format": "attr",
        "provider": "sssp",
        "accuracy": "efficiency",
        "element": "Si",
        "pseudo_type": "NC",
        "functional": "PBEsol",
        "relativistic": "scalar",
        "z_valence": 4.0,
        "cutoffs": {
            "ecutwfc_ry": 30.0,
            "ecutrho_ry": 120.0,
        },
        "source_identifier": "synthetic/Si.UPF",
    }


@pytest.fixture
def request_body(
    sample_structure_path: str, pseudo_metadata: dict[str, object]
) -> dict[str, object]:
    return {
        "structure": sample_structure_path,
        "hints": {"k_grid": [3, 3, 3]},
        "pseudo_metadata": [pseudo_metadata],
    }


@pytest.fixture
def test_service() -> Iterator[Service]:
    service = Service()
    yield service
    service.close()
