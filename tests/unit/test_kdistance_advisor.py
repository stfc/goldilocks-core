from dataclasses import replace

import numpy as np
import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.advice.kdistance import (
    QrfBackend,
    kdistance_to_selection,
)
from goldilocks_core.contracts import StructureFeatureVector
from goldilocks_core.kmesh.math import k_distance_to_mesh
from goldilocks_core.ml.model_registry import load_default_qrf_config
from goldilocks_core.ml.qrf.inference import _predict_kdistance_quantiles


class FakeQRF:
    def __init__(self, lower=0.2, median=0.25, upper=0.3):
        self.quantiles = np.array([[lower], [median], [upper]])

    def predict(self, features):
        return self.quantiles


def make_features() -> StructureFeatureVector:
    return StructureFeatureVector(np.zeros(4), ["a", "b", "c", "d"])


def make_structure() -> Structure:
    return Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])


def local_config():
    """Return packaged behavior with explicit local resource paths."""
    config = load_default_qrf_config()
    return replace(
        config,
        model=replace(config.model, source="local", location="model.pkl"),
        model_asset=None,
    )


def patch_inference(monkeypatch, *, model=None) -> None:
    monkeypatch.setattr(
        "goldilocks_core.ml.models.load_model", lambda spec: model or FakeQRF()
    )
    monkeypatch.setattr(
        "goldilocks_core.ml.qrf.metallicity.load_metallicity_model",
        lambda path: object(),
    )
    monkeypatch.setattr(
        "goldilocks_core.ml.qrf.features.extract_qrf_features",
        lambda structure, model, atom_init, settings: StructureFeatureVector(
            np.zeros(483), [f"feature_{index}" for index in range(483)]
        ),
    )


def test_predict_kdistance_quantiles_applies_correction() -> None:
    assert _predict_kdistance_quantiles(FakeQRF(), make_features(), 0.01) == (
        0.25,
        0.19,
        0.31,
    )


@pytest.mark.parametrize(
    "model",
    [
        FakeQRF(np.nan, 0.25, 0.3),
        FakeQRF(-0.2, 0.25, 0.3),
        FakeQRF(0.3, 0.25, 0.2),
    ],
)
def test_predict_kdistance_quantiles_rejects_unusable_output(model) -> None:
    with pytest.raises(ValueError):
        _predict_kdistance_quantiles(model, make_features())


def test_predict_kdistance_quantiles_requires_three_values() -> None:
    model = FakeQRF()
    model.quantiles = np.array([[0.2], [0.3]])

    with pytest.raises(ValueError, match="3 QRF quantiles"):
        _predict_kdistance_quantiles(model, make_features())


def test_kdistance_selection_records_model_provenance() -> None:
    structure = make_structure()
    selection = kdistance_to_selection(
        structure,
        0.25,
        0.2,
        0.3,
        data_source="qrf@revision",
        confidence=0.9,
    )

    assert selection.grid == k_distance_to_mesh(structure, 0.25)
    assert selection.provenance.source == "model"
    assert selection.provenance.data_source == "qrf@revision"
    assert selection.provenance.confidence == 0.9


def test_qrf_backend_loads_lazily_and_reuses_resources(monkeypatch) -> None:
    loads = 0

    def load_model(spec):
        nonlocal loads
        loads += 1
        return FakeQRF()

    patch_inference(monkeypatch)
    monkeypatch.setattr("goldilocks_core.ml.models.load_model", load_model)
    backend = QrfBackend(
        config=local_config(),
        metallicity_checkpoint="checkpoint.ckpt",
        metallicity_atom_init="atom-init.json",
    )

    first = backend(make_structure())
    second = backend(make_structure())

    assert first.grid == second.grid
    assert first.provenance.source == "model"
    assert loads == 1


def test_qrf_backend_model_loading_errors_propagate(monkeypatch) -> None:
    def fail(spec):
        raise FileNotFoundError("missing model")

    monkeypatch.setattr("goldilocks_core.ml.models.load_model", fail)
    backend = QrfBackend(
        config=local_config(),
        metallicity_checkpoint="checkpoint.ckpt",
        metallicity_atom_init="atom-init.json",
    )

    with pytest.raises(FileNotFoundError, match="missing model"):
        backend(make_structure())


def test_qrf_backend_loads_registry_config_on_first_model_call(monkeypatch) -> None:
    loads = 0

    def load_config(path=None):
        nonlocal loads
        loads += 1
        return local_config()

    monkeypatch.setattr(
        "goldilocks_core.advice.kdistance.load_default_qrf_config",
        load_config,
    )
    patch_inference(monkeypatch)
    backend = QrfBackend(
        metallicity_checkpoint="checkpoint.ckpt",
        metallicity_atom_init="atom-init.json",
    )

    first = backend(make_structure())
    second = backend(make_structure())

    assert first.provenance.source == "model"
    assert first.grid == second.grid
    assert loads == 1
