import numpy as np
from pymatgen.core import Lattice, Structure

from goldilocks_core.advisors.kspacing_advisor import (
    DEFAULT_KPOINTS_MODEL,
    kspacing_to_selection,
    predict_kspacing_quantiles,
)
from goldilocks_core.contracts import StructureFeatureVector


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


def test_predict_kspacing_quantiles_returns_median_and_corrected_interval() -> None:
    """Median passes through; correction widens the interval bounds."""
    model = FakeQRF(lower=0.20, median=0.25, upper=0.30)

    median, lower, upper = predict_kspacing_quantiles(
        model, make_features(), correction=0.01
    )

    assert median == 0.25
    assert lower == 0.20 - 0.01
    assert upper == 0.30 + 0.01


def test_predict_kspacing_quantiles_rejects_wrong_quantile_count() -> None:
    """Reject a prediction that is not three quantiles."""

    class TwoQuantiles:
        def predict(self, X):
            return np.array([[0.2], [0.3]])

    try:
        predict_kspacing_quantiles(TwoQuantiles(), make_features())
    except ValueError as error:
        assert "3 quantiles" in str(error)
    else:
        raise AssertionError("expected ValueError for wrong quantile count")


def test_kspacing_to_selection_builds_grid_with_model_provenance() -> None:
    """Median spacing sets the mesh; provenance records model + confidence."""
    selection = kspacing_to_selection(
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
    assert DEFAULT_KPOINTS_MODEL.target == "k_spacing"
