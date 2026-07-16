from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.jobs import CoreRuntime, Pipeline
from goldilocks_core.kmesh import resolve_kpoints_from_advice

if TYPE_CHECKING:
    from collections.abc import Iterator

# Explicit k-grid hint on every request keeps the QRF/metallicity model path
# off, so these tests never load a real model or touch the network.


@pytest.fixture
def si_structure() -> Structure:
    """Return a small ordered Si structure for endpoint tests."""
    return Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])


@pytest.fixture
def si_cif(si_structure: Structure) -> str:
    """Return inline CIF text for the Si structure."""
    return si_structure.to(fmt="cif")


@pytest.fixture
def si_poscar(si_structure: Structure) -> str:
    """Return inline POSCAR text for the Si structure."""
    return si_structure.to(fmt="poscar")


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
        "functional": "PBE",
        "relativistic": "scalar",
        "z_valence": 4.0,
        "is_sssp": True,
        "sssp_recommended_cutoff": {"ecutwfc_ry": 30.0, "ecutrho_ry": 120.0},
    }


@pytest.fixture
def heuristic_runtime() -> CoreRuntime:
    """Return a runtime with advice-based k-point resolution (no model load)."""
    return CoreRuntime(pipeline=Pipeline(kmesh=resolve_kpoints_from_advice))


@pytest.fixture
def bundle_root(tmp_path: Path) -> Path:
    """Return a per-test bundle root directory."""
    root = tmp_path / "bundles"
    root.mkdir()
    return root


@pytest.fixture
def structure_root(tmp_path: Path, si_cif: str) -> Path:
    """Return a structure root containing an allowlisted Si.cif file."""
    root = tmp_path / "structures"
    root.mkdir()
    (root / "Si.cif").write_text(si_cif)
    return root


@pytest.fixture
def client(
    heuristic_runtime: CoreRuntime,
    bundle_root: Path,
    structure_root: Path,
) -> Iterator[object]:
    """Yield a TestClient against an app with a heuristic runtime and tmp roots."""
    from fastapi.testclient import TestClient

    from goldilocks_core.server.http import create_app

    app = create_app(
        runtime=heuristic_runtime,
        bundle_root=bundle_root,
        structure_root=structure_root,
    )
    with TestClient(app) as test_client:
        yield test_client
