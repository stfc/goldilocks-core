from __future__ import annotations

from collections.abc import Iterator

import pytest
from pymatgen.core import Structure

from goldilocks_core.assets import AssetStore
from goldilocks_core.contracts import PseudoCutoffs, PseudoMetadata
from goldilocks_core.examples import structure
from goldilocks_core.runtime import CoreRuntime, CoreService


@pytest.fixture
def installed_pseudo_metadata() -> tuple[PseudoMetadata, ...]:
    """Return metadata sufficient to render a silicon QE input."""
    return (
        PseudoMetadata(
            filepath="/pseudo/Si.UPF",
            filename="Si.UPF",
            header_format="attr",
            element="Si",
            pseudo_type="NC",
            functional="PBEsol",
            relativistic="scalar",
            z_valence=4.0,
            cutoffs=PseudoCutoffs(ecutwfc_ry=30.0, ecutrho_ry=120.0),
        ),
    )


@pytest.fixture(autouse=True)
def installed_pseudos(
    monkeypatch: pytest.MonkeyPatch, installed_pseudo_metadata
) -> None:
    """Resolve the server's installed pseudo source without a real store."""
    monkeypatch.setattr(
        "goldilocks_core.runtime.scf.source_for_request",
        lambda request, *, store, registry_path: (
            lambda structure, requirements: installed_pseudo_metadata
        ),
    )


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
def test_service(tmp_path) -> Iterator[CoreService]:
    """Yield a hermetic Core service over an empty explicit asset store."""
    runtime = CoreRuntime(asset_store=AssetStore(tmp_path / "assets"))
    service = CoreService(runtime)
    yield service
    service.close()
