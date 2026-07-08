import joblib
import pytest

from goldilocks_core.contracts import ModelSpec
from goldilocks_core.ml.models import load_model


def test_load_model_loads_local_random_forest(tmp_path) -> None:
    """Load a local random-forest model from disk."""
    model = {"kind": "dummy-rf"}
    model_path = tmp_path / "model.joblib"
    joblib.dump(model, model_path)

    spec = ModelSpec(
        name="test-model",
        version="v0",
        model_type="random_forest",
        target="k_index",
        feature_set="cslr",
        source="local",
        location=str(model_path),
        revision=None,
    )

    loaded_model = load_model(spec)

    assert loaded_model == model


def test_load_model_rejects_unsupported_source() -> None:
    """Reject unsupported model sources."""
    spec = ModelSpec(
        name="test-model",
        version="v0",
        model_type="random_forest",
        target="k_index",
        feature_set="cslr",
        source="huggingface",
        location="junwen94/test-model",
        revision="main",
    )

    with pytest.raises(NotImplementedError, match="Model source"):
        load_model(spec)


def test_load_model_raises_for_missing_local_file(tmp_path) -> None:
    """Raise FileNotFoundError when a local model file is missing."""
    model_path = tmp_path / "missing.joblib"

    spec = ModelSpec(
        name="test-model",
        version="v0",
        model_type="random_forest",
        target="k_index",
        feature_set="cslr",
        source="local",
        location=str(model_path),
        revision=None,
    )

    with pytest.raises(FileNotFoundError, match="Model file not found"):
        load_model(spec)
