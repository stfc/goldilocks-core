from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, cast

from goldilocks_core.assets import AssetFile, AssetSpec
from goldilocks_core.contracts import ModelSource, ModelSpec, ModelType, PathLike

MODEL_REGISTRY_ENV = "GOLDILOCKS_MODEL_REGISTRY"
_REGISTRY_RESOURCE = "registry.toml"


@dataclass(frozen=True, slots=True)
class QrfFeatureSettings:
    composition_featurizers: tuple[str, ...]
    element_property_preset: str
    impute_nan: bool
    structure_featurizers: tuple[str, ...]
    global_symmetry_features: tuple[str, ...]
    density_features: tuple[str, ...]
    soap_species: str
    soap_r_cut: float
    soap_n_max: int
    soap_l_max: int
    soap_sigma: float
    soap_periodic: bool
    soap_sparse: bool
    soap_reduction: str
    lattice_symprec: float
    metallicity_graph_radius: float
    metallicity_max_neighbors: int


@dataclass(frozen=True, slots=True)
class QrfKpointsConfig:
    model: ModelSpec
    model_asset: AssetSpec | None
    model_file: str
    feature_settings: QrfFeatureSettings
    confidence: float
    correction: float
    metallicity_model: ModelSpec
    metallicity_asset: AssetSpec | None
    metallicity_checkpoint_file: str
    metallicity_atom_init_file: str


@dataclass(frozen=True, slots=True)
class ElectronicCharacterConfig:
    """Where to find the goldilocks-ml model that answers is-this-a-metal
    directly, distinct from the checkpoint QRF consumes as a feature block."""

    target_contract: str
    asset: AssetSpec


def _load_registry_data(path: PathLike | None) -> dict[str, Any]:
    registry_path = path or os.environ.get(MODEL_REGISTRY_ENV)
    if registry_path is None:
        registry = resources.files("goldilocks_core.ml").joinpath(_REGISTRY_RESOURCE)
        with registry.open("rb") as registry_file:
            return tomllib.load(registry_file)
    with Path(registry_path).open("rb") as registry_file:
        return tomllib.load(registry_file)


def load_default_electronic_character_config(
    path: PathLike | None = None,
) -> ElectronicCharacterConfig:
    section = _load_registry_data(path)["defaults"]["electronic_character"]
    return ElectronicCharacterConfig(
        target_contract=section["target_contract"],
        asset=_asset_spec(section["asset"]),
    )


def load_default_qrf_config(path: PathLike | None = None) -> QrfKpointsConfig:
    data = _load_registry_data(path)
    kpoints = data["defaults"]["kpoints"]
    features = kpoints["features"]
    metallicity = kpoints["metallicity"]
    calibration = kpoints["calibration"]
    model_asset = _asset_spec(kpoints.get("asset"))
    metallicity_asset = _asset_spec(metallicity.get("asset"))
    model_file = (
        _role_path(model_asset, "model") if model_asset else kpoints["location"]
    )
    checkpoint_file = metallicity["checkpoint_file"]
    atom_init_file = metallicity["atom_init_file"]

    return QrfKpointsConfig(
        model=_model_spec(kpoints, model_file),
        model_asset=model_asset,
        model_file=model_file,
        feature_settings=QrfFeatureSettings(
            composition_featurizers=tuple(features["composition_featurizers"]),
            element_property_preset=features["element_property_preset"],
            impute_nan=features["impute_nan"],
            structure_featurizers=tuple(features["structure_featurizers"]),
            global_symmetry_features=tuple(features["global_symmetry_features"]),
            density_features=tuple(features["density_features"]),
            soap_species=features["soap_species"],
            soap_r_cut=features["soap_r_cut"],
            soap_n_max=features["soap_n_max"],
            soap_l_max=features["soap_l_max"],
            soap_sigma=features["soap_sigma"],
            soap_periodic=features["soap_periodic"],
            soap_sparse=features["soap_sparse"],
            soap_reduction=features["soap_reduction"],
            lattice_symprec=features["lattice_symprec"],
            metallicity_graph_radius=features["metallicity_graph_radius"],
            metallicity_max_neighbors=features["metallicity_max_neighbors"],
        ),
        confidence=kpoints["interval_confidence"],
        correction=calibration["correction"],
        metallicity_model=_model_spec(metallicity, checkpoint_file),
        metallicity_asset=metallicity_asset,
        metallicity_checkpoint_file=checkpoint_file,
        metallicity_atom_init_file=atom_init_file,
    )


def model_asset_specs(path: PathLike | None = None) -> tuple[AssetSpec, ...]:
    config = load_default_qrf_config(path)
    electronic_character = load_default_electronic_character_config(path)
    return tuple(
        spec
        for spec in (
            config.model_asset,
            config.metallicity_asset,
            electronic_character.asset,
        )
        if spec is not None
    )


def _asset_spec(data: dict[str, Any] | None) -> AssetSpec | None:
    if data is None:
        return None
    return AssetSpec(
        id=data["id"],
        version=str(data["version"]),
        files=tuple(
            AssetFile(
                role=file["role"],
                path=file["path"],
                url=file["url"],
                checksum=file.get("checksum"),
                size=file.get("size"),
            )
            for file in data["files"]
        ),
    )


def _model_spec(data: dict[str, Any], location: str) -> ModelSpec:
    source = cast(ModelSource, data.get("source", "local"))
    return ModelSpec(
        name=data["name"],
        version=str(data["version"]),
        model_type=cast(ModelType, data["model_type"]),
        target=data["target"],
        feature_set=data["feature_set"],
        source=source,
        location=data.get("location", location),
        revision=data.get("revision"),
    )


def _role_path(spec: AssetSpec, role: str) -> str:
    try:
        return next(file.path for file in spec.files if file.role == role)
    except StopIteration as error:
        raise ValueError(
            f"asset {spec.id}@{spec.version} lacks required role {role!r}"
        ) from error
