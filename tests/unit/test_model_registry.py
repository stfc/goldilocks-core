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


def test_explicit_registry_replaces_model_and_artifacts(tmp_path: Path) -> None:
    registry = tmp_path / "models.toml"
    write_registry(registry)

    config = load_default_qrf_config(registry)

    assert config.model.name == "replacement-qrf"
    assert config.model.location == "/models/qrf.joblib"
    assert config.correction == 0.01
    assert config.metallicity.location == "/models/metallicity"
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


def test_incomplete_registry_fails_at_missing_field(tmp_path: Path) -> None:
    registry = tmp_path / "models.toml"
    registry.write_text("[defaults.kpoints]\nname = 'incomplete'\n")

    with pytest.raises(KeyError):
        load_default_qrf_config(registry)
