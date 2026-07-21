import numpy as np
import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.ml.features import extract_cslr_features, extract_l_features
from goldilocks_core.ml.inference import predict


class DummyModel:
    """Minimal sklearn-like model for testing inference flow."""

    def predict(self, X):
        return [float(X.shape[1])]


class EmptyPredictionModel:
    """Model returning an empty prediction vector."""

    def predict(self, X):
        return []


class MissingPredictModel:
    """Object without a predict method."""


def make_si_structure() -> Structure:
    """Build a minimal silicon structure for tests."""
    return Structure(
        lattice=Lattice.cubic(3.5),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )


def test_predict_runs_on_cslr_features() -> None:
    """Run end-to-end prediction from structure features."""
    structure = make_si_structure()

    features = extract_cslr_features(structure)
    result = predict(DummyModel(), features)

    assert isinstance(result, float)
    assert result == float(len(features.values))


@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf])
def test_predict_rejects_mutated_non_finite_features_before_calling_model(
    value,
) -> None:
    """Mutation after construction cannot send non-finite values to a model."""

    class PredictSpy:
        called = False

        def predict(self, X):
            self.called = True
            return [1.0]

    features = extract_l_features(make_si_structure())
    features.values[0] = value
    model = PredictSpy()

    with pytest.raises(ValueError, match="features.*finite"):
        predict(model, features)

    assert model.called is False


def test_predict_raises_when_model_has_no_predict_method() -> None:
    """Reject model objects that do not expose a predict method."""
    features = extract_l_features(make_si_structure())

    with pytest.raises(AttributeError, match="predict"):
        predict(MissingPredictModel(), features)


def test_predict_raises_when_model_returns_no_values() -> None:
    """Reject models that return an empty prediction vector."""
    features = extract_l_features(make_si_structure())

    with pytest.raises(ValueError, match="no values"):
        predict(EmptyPredictionModel(), features)
