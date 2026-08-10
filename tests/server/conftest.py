from __future__ import annotations

from collections.abc import Iterator

import pytest
from pymatgen.core import Structure

from goldilocks_core.examples import structure
from goldilocks_core.runtime import CoreRuntime


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
    sample_structure_text: str, pseudo_metadata: dict[str, object]
) -> dict[str, object]:
    """Return a browser-safe transport request body (inline, path-free)."""
    return {
        "structure": {"content": sample_structure_text, "format": "cif"},
        "hints": {"k_grid": [3, 3, 3]},
        "pseudo_metadata": [pseudo_metadata],
    }


@pytest.fixture
def test_runtime() -> Iterator[CoreRuntime]:
    """Yield a runtime and close it after the test."""
    runtime = CoreRuntime()
    yield runtime
    runtime.close()
