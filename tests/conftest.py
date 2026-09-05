from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.contracts import PseudoCutoffs, PseudoMetadata

_STUB_ELECTRONIC_CHARACTER_MODEL_DIR = "<stub electronic-character model>"


@pytest.fixture(autouse=True)
def _stub_electronic_character_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Runtime() resolves a real metallicity model by default (#174): give
    every test a deterministic, offline stand-in so the suite stays hermetic.

    A test that cares about a specific electronic character -- or wants to
    exercise real asset resolution, e.g. to check AssetNotInstalled -- can
    monkeypatch goldilocks_ml.inference.load_model or
    goldilocks_core.assets.AssetStore.resolve again itself; a later
    monkeypatch call in the same test wins over this one.
    """
    from goldilocks_ml import inference

    from goldilocks_core.assets import AssetStore

    real_resolve = AssetStore.resolve

    def fake_resolve(self: AssetStore, asset_id: str, version: str) -> Any:
        if asset_id == "models/metallicity-is-metal":
            from types import SimpleNamespace

            return SimpleNamespace(root=_STUB_ELECTRONIC_CHARACTER_MODEL_DIR)
        return real_resolve(self, asset_id, version)

    monkeypatch.setattr(AssetStore, "resolve", fake_resolve)

    real_load_model = inference.load_model

    def fake_load_model(model_dir: Any, **kwargs: Any) -> Any:
        if model_dir == _STUB_ELECTRONIC_CHARACTER_MODEL_DIR:
            return _StubElectronicCharacterModel()
        return real_load_model(model_dir, **kwargs)

    monkeypatch.setattr(inference, "load_model", fake_load_model)


class _StubElectronicCharacterModel:
    """Deterministic, offline stand-in: agrees with the composition
    heuristic on whether every element is metallic, but -- like the real
    model, and unlike the heuristic -- commits to metal/insulator rather
    than hedging with likely_metal/unknown."""

    def predict(self, structure: Structure) -> Any:
        from goldilocks_ml.inference import ModelPrediction

        from goldilocks_core.analysis import heuristic_metallicity

        is_metal = heuristic_metallicity(structure) == "likely_metal"
        return ModelPrediction(
            parameter="metallicity",
            quantity="is_metal",
            value=is_metal,
            target_contract="goldilocks.is_metal.dft_band_gap_zero.v1",
            model_id="test-stub",
            details={"score": 1.0 if is_metal else 0.0},
        )


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
    ) -> PseudoMetadata:
        filename = f"{element}.UPF"
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
