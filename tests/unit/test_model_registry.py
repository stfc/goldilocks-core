from pathlib import Path

import pytest

from goldilocks_core.ml.model_registry import (
    MODEL_REGISTRY_ENV,
    load_default_qrf_config,
)


def write_registry(path: Path, *, name: str = "replacement-qrf") -> None:
    path.write_text(
        f"""[defaults.kpoints]
name = "{name}"
version = "v2"
model_type = "random_forest"
target = "k_distance"
feature_set = "qrf_comp_struct_soap_lattice_metal"
source = "local"
location = "/models/qrf.joblib"
revision = "model-revision"
interval_confidence = 0.9

[defaults.kpoints.calibration]
correction = 0.01

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
name = "test-metallicity-model"
version = "0"
model_type = "cgcnn"
target = "metallicity"
feature_set = "cgcnn_radius_graph"
source = "local"
location = "/models/metallicity"
revision = "artifact-revision"
checkpoint_file = "model.ckpt"
atom_init_file = "elements.json"
""",
        encoding="utf-8",
    )


def test_packaged_registry_loads_qrf_resources() -> None:
    config = load_default_qrf_config()

    assert config.model.name == "kpoints-goldilocks-QRF"
    assert config.feature_settings.soap_r_cut == 10.0
    assert config.confidence == 0.9
    assert config.metallicity_checkpoint_file == "is_metal.ckpt"
    assert config.metallicity_model.name == "metallicity-goldilocks-CGCNN"
    assert config.metallicity_model.model_type == "cgcnn"
    assert config.metallicity_model.target == "metallicity"
    assert config.model_asset is not None
    assert config.model_asset.id == "qrf-kpoints"
    assert {file.role for file in config.model_asset.files} == {
        "model",
        "licence",
    }
    assert config.metallicity_asset is not None
    assert {file.role for file in config.metallicity_asset.files} == {
        "checkpoint",
        "atom_init",
        "licence",
    }
    assert all(
        file.checksum is not None and file.size is not None
        for spec in (config.model_asset, config.metallicity_asset)
        for file in spec.files
    )


def test_explicit_registry_replaces_model_and_artifacts(tmp_path: Path) -> None:
    registry = tmp_path / "models.toml"
    write_registry(registry)

    config = load_default_qrf_config(registry)

    assert config.model.name == "replacement-qrf"
    assert config.model.location == "/models/qrf.joblib"
    assert config.correction == 0.01
    assert config.metallicity_model.location == "/models/metallicity"
    assert config.metallicity_model.name == "test-metallicity-model"
    assert config.metallicity_atom_init_file == "elements.json"


def test_explicit_registry_takes_precedence_over_environment(
    monkeypatch,
    tmp_path: Path,
) -> None:
    environment = tmp_path / "environment.toml"
    explicit = tmp_path / "explicit.toml"
    write_registry(environment, name="environment")
    write_registry(explicit, name="explicit")
    monkeypatch.setenv(MODEL_REGISTRY_ENV, str(environment))

    assert load_default_qrf_config(explicit).model.name == "explicit"


def test_environment_selects_registry(monkeypatch, tmp_path: Path) -> None:
    registry = tmp_path / "models.toml"
    write_registry(registry, name="environment")
    monkeypatch.setenv(MODEL_REGISTRY_ENV, str(registry))

    assert load_default_qrf_config().model.name == "environment"


def test_model_assets_reject_non_sha256_checksums(tmp_path: Path) -> None:
    registry = tmp_path / "models.toml"
    write_registry(registry)
    with registry.open("a", encoding="utf-8") as output:
        output.write(
            """

[defaults.kpoints.asset]
id = "fixture-model"
version = "1"

[[defaults.kpoints.asset.files]]
role = "model"
path = "model.pkl"
url = "https://example.invalid/model.pkl"
checksum = "md5:00000000000000000000000000000000"
size = 1

[[defaults.kpoints.asset.files]]
role = "licence"
path = "MODEL_CARD.md"
url = "https://example.invalid/MODEL_CARD.md"
checksum = "sha256:0000000000000000000000000000000000000000000000000000000000000000"
size = 1
"""
        )

    with pytest.raises(ValueError, match="checksums must use sha256: model"):
        load_default_qrf_config(registry)


def test_incomplete_registry_fails_at_missing_field(tmp_path: Path) -> None:
    registry = tmp_path / "models.toml"
    registry.write_text("[defaults.kpoints]\nname = 'incomplete'\n")

    with pytest.raises(KeyError):
        load_default_qrf_config(registry)
