from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.pseudo.pp_metadata import PseudoMetadata


@pytest.fixture
def silicon_structure() -> Structure:
    """Return a small ordered elemental structure for portable tests."""
    return Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])


@pytest.fixture
def sodium_chloride_structure() -> Structure:
    """Return a small ordered binary structure for cross-element tests."""
    return Structure(
        Lattice.cubic(5.64),
        ["Na", "Cl"],
        [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
    )


@pytest.fixture
def pseudo_metadata_factory() -> Callable[..., PseudoMetadata]:
    """Return a factory for synthetic, network-free pseudopotential metadata."""

    def make_metadata(
        element: str,
        *,
        ecutwfc_ry: float = 30.0,
        ecutrho_ry: float = 120.0,
        functional: str = "PBE",
        pseudo_type: str = "NC",
        relativistic: str = "scalar",
        root: Path = Path("/pseudo"),
    ) -> PseudoMetadata:
        filename = f"{element}.UPF"
        return PseudoMetadata(
            filepath=str(root / filename),
            filename=filename,
            header_format="attr",
            library="synthetic-test-library",
            element=element,
            pseudo_type=pseudo_type,
            functional=functional,
            relativistic=relativistic,
            sssp_recommended_cutoff={
                "ecutwfc_ry": ecutwfc_ry,
                "ecutrho_ry": ecutrho_ry,
            },
        )

    return make_metadata


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark tests by architectural layer based on their containing directory."""
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
