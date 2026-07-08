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


def test_load_model_downloads_huggingface_artifact(tmp_path, monkeypatch) -> None:
    """Download a huggingface artifact via hf_hub_download and load it."""
    model = {"kind": "hf-rf"}
    model_path = tmp_path / "QRF95.pkl"
    joblib.dump(model, model_path)

    calls = {}

    def fake_download(*, repo_id, filename, revision):
        calls.update(repo_id=repo_id, filename=filename, revision=revision)
        return str(model_path)

    monkeypatch.setattr("huggingface_hub.hf_hub_download", fake_download)

    spec = ModelSpec(
        name="test-model",
        version="v0",
        model_type="random_forest",
        target="k_index",
        feature_set="cslr",
        source="huggingface",
        location="STFC-SCD/kpoints-goldilocks-QRF::QRF95.pkl",
        revision="main",
    )

    loaded_model = load_model(spec)

    assert loaded_model == model
    assert calls == {
        "repo_id": "STFC-SCD/kpoints-goldilocks-QRF",
        "filename": "QRF95.pkl",
        "revision": "main",
    }


def test_load_model_rejects_malformed_huggingface_location() -> None:
    """Reject a huggingface location missing the '::<filename>' part."""
    spec = ModelSpec(
        name="test-model",
        version="v0",
        model_type="random_forest",
        target="k_index",
        feature_set="cslr",
        source="huggingface",
        location="STFC-SCD/kpoints-goldilocks-QRF",
        revision=None,
    )

    with pytest.raises(ValueError, match="repo_id.*filename"):
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
