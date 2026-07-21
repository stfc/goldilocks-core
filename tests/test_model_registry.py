from pathlib import Path

import pytest

from goldilocks_core.ml.kdistance_features import QRF_FEATURE_SET
from goldilocks_core.ml.model_registry import (
    MODEL_REGISTRY_ENV,
    load_default_qrf_config,
)


def write_registry(path: Path, *, advisor: str = "qrf_kdistance") -> None:
    path.write_text(
        f"""[defaults.kpoints]
advisor = "{advisor}"
name = "replacement-qrf"
version = "v2"
model_type = "random_forest"
target = "k_distance"
feature_set = "{QRF_FEATURE_SET}"
source = "local"
location = "/models/qrf.joblib"
revision = "model-revision"
confidence = 0.9
correction = 0.01
scikit_learn_version = "1.7.2"
sklearn_quantile_version = "0.1.1"
joblib_version = "1.5.3"

[defaults.kpoints.metallicity]
source = "local"
location = "/models/metallicity"
revision = "artifact-revision"
checkpoint_file = "model.ckpt"
atom_init_file = "elements.json"
""",
        encoding="utf-8",
    )


def test_custom_registry_hotswaps_model_and_artifact_locations(tmp_path) -> None:
    """Load all upstream metadata from a caller-supplied registry."""
    registry = tmp_path / "models.toml"
    write_registry(registry)

    config = load_default_qrf_config(registry)

    assert config.model.name == "replacement-qrf"
    assert config.model.location == "/models/qrf.joblib"
    assert config.model.revision == "model-revision"
    assert config.scikit_learn_version == "1.7.2"
    assert config.sklearn_quantile_version == "0.1.1"
    assert config.joblib_version == "1.5.3"
    assert config.metallicity.location == "/models/metallicity"
    assert config.metallicity_checkpoint_file == "model.ckpt"


def test_registry_environment_variable_selects_custom_file(
    monkeypatch, tmp_path
) -> None:
    """Allow deployment configuration to replace the packaged registry."""
    registry = tmp_path / "models.toml"
    write_registry(registry)
    monkeypatch.setenv(MODEL_REGISTRY_ENV, str(registry))

    config = load_default_qrf_config()

    assert config.model.name == "replacement-qrf"


def test_explicit_registry_path_precedes_environment(monkeypatch, tmp_path) -> None:
    """An explicit path wins over the process-wide registry setting."""
    explicit = tmp_path / "explicit.toml"
    environment = tmp_path / "environment.toml"
    write_registry(explicit)
    write_registry(environment, advisor="unsupported")
    monkeypatch.setenv(MODEL_REGISTRY_ENV, str(environment))

    config = load_default_qrf_config(explicit)

    assert config.model.name == "replacement-qrf"


def test_registry_requires_immutable_huggingface_revision(tmp_path) -> None:
    """Reject mutable remote defaults instead of silently following a branch."""
    registry = tmp_path / "models.toml"
    write_registry(registry)
    mutable_remote = registry.read_text(encoding="utf-8").replace(
        'source = "local"\nlocation = "/models/qrf.joblib"\n'
        'revision = "model-revision"',
        'source = "huggingface"\nlocation = "organization/model::model.pkl"\n'
        'revision = "main"',
        1,
    )
    registry.write_text(mutable_remote, encoding="utf-8")

    with pytest.raises(ValueError, match="40-character"):
        load_default_qrf_config(registry)


def test_registry_rejects_unsupported_advisor(tmp_path) -> None:
    """Fail clearly when the default entry names an unknown backend adapter."""
    registry = tmp_path / "models.toml"
    write_registry(registry, advisor="unknown")

    with pytest.raises(ValueError, match="qrf_kdistance"):
        load_default_qrf_config(registry)
