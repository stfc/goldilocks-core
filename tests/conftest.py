from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.pseudo.metadata import PseudoCutoffs, PseudoMetadata


@pytest.fixture(autouse=True)
def isolated_default_asset_root(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GOLDILOCKS_ASSET_ROOT", str(tmp_path / "default-assets"))


@pytest.fixture
def silicon_structure() -> Structure:
    return Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])


@pytest.fixture
def sodium_chloride_structure() -> Structure:
    return Structure(
        Lattice.cubic(5.64),
        ["Na", "Cl"],
        [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
    )


@pytest.fixture
def pseudo_metadata_factory() -> Callable[..., PseudoMetadata]:

    def make_metadata(
        element: str,
        *,
        ecutwfc_ry: float = 30.0,
        ecutrho_ry: float = 120.0,
        functional: str = "PBEsol",
        pseudo_type: str = "NC",
        relativistic: str = "scalar",
        accuracy: str | None = "efficiency",
        root: Path = Path("/pseudo"),
        materialize: bool = False,
    ) -> PseudoMetadata:
        filename = f"{element}.UPF"
        content = f"<UPF version='2.0.1'>{element} fixture</UPF>\n".encode()
        if materialize:
            root.mkdir(parents=True, exist_ok=True)
            (root / filename).write_bytes(content)
        return PseudoMetadata(
            filepath=str(root / filename),
            filename=filename,
            header_format="attr",
            provider="synthetic-test",
            accuracy=accuracy,
            element=element,
            pseudo_type=pseudo_type,
            functional=functional,
            relativistic=relativistic,
            cutoffs=PseudoCutoffs(
                ecutwfc_ry=ecutwfc_ry,
                ecutrho_ry=ecutrho_ry,
            ),
            source_identifier=f"synthetic/{filename}",
            content_sha256=(
                hashlib.sha256(content).hexdigest() if materialize else None
            ),
            content_size_bytes=len(content) if materialize else None,
            pseudo_info={
                "licence": "CC-BY-4.0",
                "licence_text": "Synthetic test pseudopotential licence\n",
                "citation": "Synthetic test pseudopotentials.",
            },
        )

    return make_metadata


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    layer_markers = {
        "unit": pytest.mark.unit,
        "integration": pytest.mark.integration,
        "physics": pytest.mark.physics,
    }
    for item in items:
        for parent in item.path.parents:
            marker = layer_markers.get(parent.name)
            if marker is not None:
                item.add_marker(marker)
                break
