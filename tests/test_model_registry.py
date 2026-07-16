from dataclasses import fields, replace
from pathlib import Path

import pytest

from goldilocks_core.ml.kdistance_features import (
    QRF_FEATURE_COUNT,
    QRF_FEATURE_SCHEMA,
    QRF_FEATURE_SET,
)
from goldilocks_core.ml.model_registry import (
    MODEL_REGISTRY_ENV,
    RuntimeRequirement,
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
feature_schema = "{QRF_FEATURE_SCHEMA}"
feature_count = {QRF_FEATURE_COUNT}
source = "local"
location = "/models/qrf.joblib"
revision = "model-revision"
interval_confidence = 0.9
interval_quantiles = [0.05, 0.5, 0.95]

[defaults.kpoints.calibration]
method = "symmetric_additive_bounds-v1"
correction = 0.01

[defaults.kpoints.runtime]
goldilocks-core = "0.1.0"
numpy = "2.4.4"
scikit-learn = "1.7.2"
sklearn-quantile = "0.1.1"
joblib = "1.5.3"
matminer = "0.10.1"
dscribe = "2.1.2"
pymatgen = "2026.3.23"
torch = "2.12.1"
torch-geometric = "2.8.0"

[defaults.kpoints.features]
composition_featurizers = ["ElementProperty", "Stoichiometry", "ValenceOrbital"]
element_property_preset = "magpie"
impute_nan = true
structure_featurizers = ["GlobalSymmetryFeatures", "DensityFeatures"]
global_symmetry_features = [
    "spacegroup_num", "crystal_system_int", "is_centrosymmetric",
]
density_features = ["density", "vpa", "packing fraction"]
soap_species = "X"
soap_r_cut = 10.0
soap_n_max = 8
soap_l_max = 6
soap_sigma = 1.0
soap_periodic = true
soap_sparse = false
soap_reduction = "mean"
lattice_symprec = 0.01
metallicity_graph_radius = 10.0
metallicity_max_neighbors = 12

[defaults.kpoints.metallicity]
source = "local"
location = "/models/metallicity"
revision = "artifact-revision"
checkpoint_file = "model.ckpt"
atom_init_file = "elements.json"
""",
        encoding="utf-8",
    )


def test_custom_registry_hotswaps_complete_inference_configuration(tmp_path) -> None:
    """Load the complete inference contract from a caller registry."""
    registry = tmp_path / "models.toml"
    write_registry(registry)

    config = load_default_qrf_config(registry)

    assert config.model.name == "replacement-qrf"
    assert config.model.location == "/models/qrf.joblib"
    assert config.feature_schema == QRF_FEATURE_SCHEMA
    assert config.feature_count == QRF_FEATURE_COUNT
    assert config.interval_confidence == 0.9
    assert config.interval_quantiles == (0.05, 0.5, 0.95)
    assert config.calibration.correction == 0.01
    assert {item.distribution for item in config.runtime_requirements} >= {
        "matminer",
        "dscribe",
        "pymatgen",
        "torch",
        "torch-geometric",
    }
    assert config.feature_settings.soap_r_cut == 10.0
    assert config.metallicity.location == "/models/metallicity"
    assert config.metallicity_checkpoint_file == "model.ckpt"


def test_registry_digest_is_deterministic() -> None:
    """Equivalent packaged configuration has one stable content identity."""
    first = load_default_qrf_config()
    second = load_default_qrf_config()

    assert first.digest == second.digest
    assert len(first.digest) == 64


def test_registry_digest_changes_for_each_top_level_contract_component() -> None:
    """No inference-relevant top-level configuration is omitted from hashing."""
    config = load_default_qrf_config()
    changed = [
        replace(config, model=replace(config.model, version="changed")),
        replace(config, feature_schema="changed"),
        replace(config, feature_count=config.feature_count + 1),
        replace(
            config,
            feature_settings=replace(config.feature_settings, soap_sigma=2.0),
        ),
        replace(config, interval_confidence=0.9),
        replace(config, interval_quantiles=(0.05, 0.5, 0.95)),
        replace(
            config,
            calibration=replace(config.calibration, correction=0.0),
        ),
        replace(
            config,
            runtime_requirements=(
                RuntimeRequirement("changed-runtime", "1"),
                *config.runtime_requirements[1:],
            ),
        ),
        replace(
            config,
            metallicity=replace(config.metallicity, revision="changed"),
        ),
        replace(config, metallicity_checkpoint_file="changed.ckpt"),
        replace(config, metallicity_atom_init_file="changed.json"),
    ]

    assert all(item.digest != config.digest for item in changed)


def test_registry_digest_includes_every_feature_setting() -> None:
    """Every registry-owned feature setting contributes to the digest."""
    config = load_default_qrf_config()
    settings = config.feature_settings

    for field in fields(settings):
        value = getattr(settings, field.name)
        if isinstance(value, bool):
            changed_value = not value
        elif isinstance(value, float):
            changed_value = value + 1.0
        elif isinstance(value, int):
            changed_value = value + 1
        elif isinstance(value, str):
            changed_value = f"{value}-changed"
        else:
            changed_value = (*value, "changed")
        changed = replace(
            config,
            feature_settings=replace(settings, **{field.name: changed_value}),
        )
        assert changed.digest != config.digest, field.name


def test_registry_digest_includes_every_model_and_artifact_setting() -> None:
    config = load_default_qrf_config()

    for nested_name in ("model", "metallicity", "calibration"):
        nested = getattr(config, nested_name)
        for field in fields(nested):
            value = getattr(nested, field.name)
            if value is None:
                changed_value = "changed"
            elif isinstance(value, float):
                changed_value = value + 1.0
            else:
                changed_value = f"{value}-changed"
            changed = replace(
                config,
                **{nested_name: replace(nested, **{field.name: changed_value})},
            )
            assert changed.digest != config.digest, f"{nested_name}.{field.name}"


def test_registry_digest_includes_every_runtime_version() -> None:
    config = load_default_qrf_config()

    for index, requirement in enumerate(config.runtime_requirements):
        changed_requirements = list(config.runtime_requirements)
        changed_requirements[index] = replace(requirement, version="changed")
        changed = replace(
            config,
            runtime_requirements=tuple(changed_requirements),
        )
        assert changed.digest != config.digest, requirement.distribution


def test_registry_environment_variable_selects_custom_file(
    monkeypatch, tmp_path
) -> None:
    registry = tmp_path / "models.toml"
    write_registry(registry)
    monkeypatch.setenv(MODEL_REGISTRY_ENV, str(registry))

    config = load_default_qrf_config()

    assert config.model.name == "replacement-qrf"


def test_explicit_registry_path_precedes_environment(monkeypatch, tmp_path) -> None:
    explicit = tmp_path / "explicit.toml"
    environment = tmp_path / "environment.toml"
    write_registry(explicit)
    write_registry(environment, advisor="unsupported")
    monkeypatch.setenv(MODEL_REGISTRY_ENV, str(environment))

    config = load_default_qrf_config(explicit)

    assert config.model.name == "replacement-qrf"


def test_registry_requires_immutable_huggingface_revision(tmp_path) -> None:
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


def test_registry_rejects_missing_runtime_requirement(tmp_path) -> None:
    registry = tmp_path / "models.toml"
    write_registry(registry)
    registry.write_text(
        registry.read_text(encoding="utf-8").replace('torch-geometric = "2.8.0"\n', ""),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="torch-geometric"):
        load_default_qrf_config(registry)


def test_registry_rejects_unsupported_advisor(tmp_path) -> None:
    registry = tmp_path / "models.toml"
    write_registry(registry, advisor="unknown")

    with pytest.raises(ValueError, match="qrf_kdistance"):
        load_default_qrf_config(registry)
