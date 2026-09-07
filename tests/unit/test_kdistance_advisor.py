from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier, Event
from types import SimpleNamespace

import numpy as np
import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.advice.kdistance import QrfBackend
from goldilocks_core.contracts import StructureFeatureVector
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


def test_qrf_backend_lazy_loading_reuse_reset_and_close(monkeypatch) -> None:
    models = []
    configs = []
    config = local_config()

    def load_model(spec):
        model = FakeQRF() if not models else FakeQRF(0.35, 0.4, 0.45)
        models.append(model)
        return model

    def load_config(path=None):
        configs.append(config)
        return config

    patch_inference(monkeypatch)
    monkeypatch.setattr("goldilocks_core.ml.models.load_model", load_model)
    monkeypatch.setattr(
        "goldilocks_core.advice.kdistance.load_default_qrf_config", load_config
    )
    backend = QrfBackend(
        metallicity_checkpoint="checkpoint.ckpt",
        metallicity_atom_init="atom-init.json",
    )
    assert not models and not configs
    first = backend(make_structure())
    assert backend(make_structure()) == first
    assert len(models) == len(configs) == 1
    assert first.provenance.source == "model"
    assert first.provenance.data_source == (
        f"{config.model.name}@{config.model.revision or config.model.version}"
    )
    assert first.provenance.confidence == config.confidence
    backend.reset()
    assert backend(make_structure()).grid != first.grid
    assert len(models) == 2
    assert len(configs) == 1
    backend.close()
    backend.reset()
    with pytest.raises(RuntimeError):
        backend(make_structure())


def test_qrf_backend_loads_once_for_concurrent_first_calls(monkeypatch) -> None:
    backend = QrfBackend(config=local_config())
    resources = object()
    load_started = Event()
    release_load = Event()
    inference = Barrier(2)
    loads = []

    def load_resources(*args, **kwargs):
        loads.append(resources)
        load_started.set()
        assert release_load.wait(timeout=2)
        return resources

    def predict(structure, config, actual_resources):
        del structure, config
        assert actual_resources is resources
        inference.wait(timeout=2)
        return SimpleNamespace(
            median=0.25,
            lower=0.2,
            upper=0.3,
            data_source="test",
            confidence=0.9,
        )

    monkeypatch.setattr(
        "goldilocks_core.advice.kdistance.load_qrf_resources", load_resources
    )
    monkeypatch.setattr(
        "goldilocks_core.advice.kdistance.predict_kdistance_with_resources",
        predict,
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(backend, make_structure())
        try:
            assert load_started.wait(timeout=2)
            second = pool.submit(backend, make_structure())
            with pytest.raises(TimeoutError):
                second.result(timeout=0.1)
        finally:
            release_load.set()
        first_selection = first.result(timeout=2)
        second_selection = second.result(timeout=2)
    assert first_selection == second_selection
    assert len(loads) == 1


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
