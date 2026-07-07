import numpy as np
from pymatgen.core import Lattice, Structure

from goldilocks_core.advisors.kdistance_advisor import (
    DEFAULT_KPOINTS_MODEL,
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


class FakeQRF:
    """Minimal QRF stub returning fixed (lower, median, upper) quantiles."""

    def __init__(self, lower, median, upper):
        self._quantiles = np.array([[lower], [median], [upper]])

    def predict(self, X):
        return self._quantiles


def make_features() -> StructureFeatureVector:
    return StructureFeatureVector(
        values=np.zeros(4), feature_names=["a", "b", "c", "d"]
    )


def make_structure() -> Structure:
    return Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])


def test_predict_kdistance_quantiles_returns_median_and_corrected_interval() -> None:
    """Median passes through; correction widens the interval bounds."""
    model = FakeQRF(lower=0.20, median=0.25, upper=0.30)

    median, lower, upper = predict_kdistance_quantiles(
        model, make_features(), correction=0.01
    )

    assert median == 0.25
    assert lower == 0.20 - 0.01
    assert upper == 0.30 + 0.01


def test_predict_kdistance_quantiles_rejects_wrong_quantile_count() -> None:
    """Reject a prediction that is not three quantiles."""

    class TwoQuantiles:
        def predict(self, X):
            return np.array([[0.2], [0.3]])

    try:
        predict_kdistance_quantiles(TwoQuantiles(), make_features())
    except ValueError as error:
        assert "3 quantiles" in str(error)
    else:
        raise AssertionError("expected ValueError for wrong quantile count")


def test_kdistance_to_selection_builds_grid_with_model_provenance() -> None:
    """Median distance sets the mesh; provenance records model + confidence."""
    selection = kdistance_to_selection(
        make_structure(),
        median=0.25,
        lower=0.19,
        upper=0.31,
        data_source="kpoints-goldilocks-QRF",
        confidence=0.95,
    )

    assert selection.grid == (7, 7, 7)
    assert selection.provenance.source == "model"
    assert selection.provenance.confidence == 0.95
    assert selection.provenance.data_source == "kpoints-goldilocks-QRF"


def test_default_kpoints_model_targets_hf_qrf95() -> None:
    """The built-in default resolves the QRF95 artifact from Hugging Face."""
    assert DEFAULT_KPOINTS_MODEL.source == "huggingface"
    assert DEFAULT_KPOINTS_MODEL.location.endswith("::QRF95.pkl")
    assert DEFAULT_KPOINTS_MODEL.target == "k_distance"


def _make_advice() -> KPointAdvice:
    return KPointAdvice(
        spacing=0.2,
        explicit_grid=None,
        mesh_type="monkhorst-pack",
        provenance=Provenance(source="default", reason="baseline"),
    )


def _patch_models(monkeypatch, qrf: FakeQRF) -> None:
    monkeypatch.setattr("goldilocks_core.ml.models.load_model", lambda spec: qrf)
    monkeypatch.setattr(
        "goldilocks_core.ml.metallicity.load_metallicity_model", lambda path: object()
    )
    monkeypatch.setattr(
        "goldilocks_core.ml.kdistance_features.extract_qrf_features",
        lambda structure, model, atom_init: StructureFeatureVector(
            values=np.zeros(483), feature_names=[]
        ),
    )


def test_qrf_kdistance_advisor_predicts_with_model_provenance(monkeypatch) -> None:
    """No hint: assemble features, run the QRF, and record model provenance."""
    _patch_models(monkeypatch, FakeQRF(lower=0.20, median=0.25, upper=0.30))
    advisor = qrf_kdistance_advisor("ckpt.pkl", "atom.json", correction=0.0)

    structure = make_structure()
    selection = advisor(structure, CalculationHints(), _make_advice())

    assert selection.grid == k_distance_to_mesh(structure, 0.25)
    assert selection.provenance.source == "model"
    assert selection.provenance.confidence == 0.95


def test_qrf_kdistance_advisor_respects_grid_hint(monkeypatch) -> None:
    """An explicit k-grid hint bypasses the model and wins."""
    _patch_models(monkeypatch, FakeQRF(lower=0.20, median=0.25, upper=0.30))
    advisor = qrf_kdistance_advisor("ckpt.pkl", "atom.json")

    selection = advisor(
        make_structure(), CalculationHints(k_grid=(2, 2, 2)), _make_advice()
    )

    assert selection.grid == (2, 2, 2)
    assert selection.provenance.source == "user_hint"
