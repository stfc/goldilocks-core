from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pymatgen.core import Lattice, Structure

if TYPE_CHECKING:
    from collections.abc import Iterator

# Explicit k-grid hint on every request keeps the QRF/metallicity model path
# off, so these tests never load a real model or touch the network.


@pytest.fixture
def si_structure() -> Structure:
    """Return a small ordered Si structure for endpoint tests."""
    return Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])


@pytest.fixture
def si_cif_path(tmp_path: Path, si_structure: Structure) -> Path:
    """Return a path to a CIF file written to tmp_path."""
    path = tmp_path / "Si.cif"
    si_structure.to(filename=str(path))
    return path


@pytest.fixture
def si_cif_text(si_structure: Structure) -> str:
    """Return inline CIF text for the Si structure."""
    return si_structure.to(fmt="cif")


@pytest.fixture
def si_pseudo_metadata() -> dict[str, object]:
    """Return a JSON-serializable pseudo metadata payload for Si."""
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
        "sssp_recommended_cutoff": {"ecutwfc_ry": 30.0, "ecutrho_ry": 120.0},
    }


@pytest.fixture
def recommend_body(si_cif_path: Path, si_pseudo_metadata: dict) -> dict:
    """Return a /recommend-shaped body with an explicit k-grid hint."""
    return {
        "structure": str(si_cif_path),
        "hints": {"k_grid": [3, 3, 3]},
        "pseudo_metadata": [si_pseudo_metadata],
    }


@pytest.fixture
def http_client(recommend_body: dict) -> Iterator[object]:
    """Yield a FastAPI TestClient against an app with an owned CoreRuntime."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from goldilocks_core.server.http import create_app

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def mcp_server() -> object:
    """Return an MCPServer with an owned CoreRuntime (no transport needed)."""
    pytest.importorskip("mcp")
    from goldilocks_core.server.mcp import create_server

    return create_server()
