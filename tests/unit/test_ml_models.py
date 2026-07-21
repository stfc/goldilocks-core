import joblib
import pytest

from goldilocks_core.contracts import ModelSpec
from goldilocks_core.ml.model_registry import ArtifactSpec
from goldilocks_core.ml.models import load_model, resolve_artifact


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


def test_model_spec_remains_mutable_before_load_time_validation(tmp_path) -> None:
    """Permit metadata updates; validate a local location only when loading."""
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
        location=str(tmp_path / "missing.joblib"),
    )

    with pytest.raises(FileNotFoundError, match="Model file not found"):
        load_model(spec)

    spec.location = str(model_path)

    assert load_model(spec) == model


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
        location="organization/model-repo::model.pkl",
        revision="main",
    )

    loaded_model = load_model(spec)

    assert loaded_model == model
    assert calls == {
        "repo_id": "organization/model-repo",
        "filename": "model.pkl",
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
        location="organization/model-repo",
        revision=None,
    )

    with pytest.raises(ValueError, match="repo_id.*filename"):
        load_model(spec)


def test_resolve_artifact_uses_configured_local_directory(tmp_path) -> None:
    """Resolve a supporting artifact without embedding its location in code."""
    artifact_path = tmp_path / "checkpoint.bin"
    artifact_path.write_text("fixture", encoding="utf-8")
    spec = ArtifactSpec(source="local", location=str(tmp_path))

    resolved = resolve_artifact(spec, "checkpoint.bin")

    assert resolved == str(artifact_path)


def test_resolve_artifact_uses_configured_huggingface_revision(
    monkeypatch,
) -> None:
    """Pass registry-provided remote metadata to the Hub resolver."""
    calls = {}

    def fake_download(*, repo_id, filename, revision):
        calls.update(repo_id=repo_id, filename=filename, revision=revision)
        return "/cache/checkpoint.bin"

    monkeypatch.setattr("huggingface_hub.hf_hub_download", fake_download)
    spec = ArtifactSpec(
        source="huggingface",
        location="organization/artifacts",
        revision="revision-id",
    )

    resolved = resolve_artifact(spec, "checkpoint.bin")

    assert resolved == "/cache/checkpoint.bin"
    assert calls == {
        "repo_id": "organization/artifacts",
        "filename": "checkpoint.bin",
        "revision": "revision-id",
    }


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
