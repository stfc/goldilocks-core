from __future__ import annotations

import hashlib
from collections.abc import Iterator

import pytest
from pymatgen.core import Structure

from goldilocks_core.examples import structure
from goldilocks_core.runtime import Service


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
    return str(structure("Si.cif"))


@pytest.fixture
def sample_structure_text(sample_structure_path: str) -> str:
    return Structure.from_file(sample_structure_path).to(fmt="cif")


@pytest.fixture
def pseudo_metadata(tmp_path) -> dict[str, object]:
    pseudo_path = tmp_path / "Si.UPF"
    content = b"<UPF version='2.0.1'>server fixture</UPF>\n"
    pseudo_path.write_bytes(content)
    return {
        "filepath": str(pseudo_path),
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
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "content_size_bytes": len(content),
        "pseudo_info": {
            "licence": "CC-BY-4.0",
            "licence_text": "Synthetic server fixture licence\n",
            "citation": "Synthetic server fixture pseudopotential.",
        },
    }


@pytest.fixture
def request_body(
    sample_structure_path: str, pseudo_metadata: dict[str, object]
) -> dict[str, object]:
    return {
        "structure": sample_structure_path,
        "hints": {"k_grid": [3, 3, 3]},
    }


@pytest.fixture
def test_service() -> Iterator[Service]:
    service = Service()
    yield service
    service.close()
