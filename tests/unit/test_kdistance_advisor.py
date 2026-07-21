import numpy as np
import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.advisors.kdistance_advisor import (
    default_kmesh_advisor,
    kdistance_to_selection,
    predict_kdistance_quantiles,
    qrf_kdistance_advisor,
)
from goldilocks_core.contracts import (
    CalculationHints,
    KPointAdvice,
    Provenance,
    StructureFeatureVector,
)
from goldilocks_core.kmesh import k_distance_to_mesh
from goldilocks_core.ml.model_registry import load_default_qrf_config


class FakeQRF:
    def __init__(self, lower=0.2, median=0.25, upper=0.3):
        self.quantiles = np.array([[lower], [median], [upper]])

    def predict(self, features):
        return self.quantiles


def make_features() -> StructureFeatureVector:
    return StructureFeatureVector(np.zeros(4), ["a", "b", "c", "d"])


def make_structure() -> Structure:
    return Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])


def make_advice() -> KPointAdvice:
    return KPointAdvice(
        spacing=0.2,
        explicit_grid=None,
        mesh_type="monkhorst-pack",
        provenance=Provenance(source="default", reason="test"),
    )


def patch_inference(monkeypatch, *, model=None) -> None:
    monkeypatch.setattr(
        "goldilocks_core.ml.models.load_model", lambda spec: model or FakeQRF()
    )
    monkeypatch.setattr(
        "goldilocks_core.ml.metallicity.load_metallicity_model", lambda path: object()
    )
    monkeypatch.setattr(
        "goldilocks_core.ml.kdistance_features.extract_qrf_features",
        lambda structure, model, atom_init, settings: StructureFeatureVector(
            np.zeros(483), [f"feature_{index}" for index in range(483)]
        ),
    )


def test_predict_kdistance_quantiles_applies_correction() -> None:
    assert predict_kdistance_quantiles(FakeQRF(), make_features(), 0.01) == (
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
        predict_kdistance_quantiles(model, make_features())


def test_predict_kdistance_quantiles_requires_three_values() -> None:
    model = FakeQRF()
    model.quantiles = np.array([[0.2], [0.3]])

    with pytest.raises(ValueError, match="3 QRF quantiles"):
        predict_kdistance_quantiles(model, make_features())


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


def test_explicit_hint_bypasses_model_loading(monkeypatch) -> None:
    monkeypatch.setattr(
        "goldilocks_core.ml.models.load_model",
        lambda spec: pytest.fail("model should not load"),
    )
    advisor = qrf_kdistance_advisor(load_default_qrf_config())

    selection = advisor(
        make_structure(),
        CalculationHints(k_grid=(2, 3, 4)),
        make_advice(),
    )

    assert selection.grid == (2, 3, 4)
    assert selection.provenance.source == "user_hint"


def test_qrf_advisor_loads_lazily_and_reuses_resources(monkeypatch) -> None:
    loads = 0

    def load_model(spec):
        nonlocal loads
        loads += 1
        return FakeQRF()

    patch_inference(monkeypatch)
    monkeypatch.setattr("goldilocks_core.ml.models.load_model", load_model)
    advisor = qrf_kdistance_advisor(
        load_default_qrf_config(),
        "checkpoint.ckpt",
        "atom-init.json",
    )

    first = advisor(make_structure(), CalculationHints(), make_advice())
    second = advisor(make_structure(), CalculationHints(), make_advice())

    assert first.grid == second.grid
    assert first.provenance.source == "model"
    assert loads == 1


def test_model_loading_errors_propagate(monkeypatch) -> None:
    def fail(spec):
        raise FileNotFoundError("missing model")

    monkeypatch.setattr("goldilocks_core.ml.models.load_model", fail)
    advisor = qrf_kdistance_advisor(
        load_default_qrf_config(),
        "checkpoint.ckpt",
        "atom-init.json",
    )

    with pytest.raises(FileNotFoundError, match="missing model"):
        advisor(make_structure(), CalculationHints(), make_advice())


def test_default_advisor_loads_registry_only_when_needed(monkeypatch) -> None:
    loads = 0

    def load_config(path=None):
        nonlocal loads
        loads += 1
        return load_default_qrf_config()

    monkeypatch.setattr(
        "goldilocks_core.advisors.kdistance_advisor.load_default_qrf_config",
        load_config,
    )
    patch_inference(monkeypatch)
    advisor = default_kmesh_advisor(
        metallicity_checkpoint="checkpoint.ckpt",
        metallicity_atom_init="atom-init.json",
    )

    hinted = advisor(
        make_structure(), CalculationHints(k_grid=(2, 2, 2)), make_advice()
    )
    modeled = advisor(make_structure(), CalculationHints(), make_advice())

    assert hinted.grid == (2, 2, 2)
    assert modeled.provenance.source == "model"
    assert loads == 1
