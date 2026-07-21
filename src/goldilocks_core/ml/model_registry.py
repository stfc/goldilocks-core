"""Load the configurable default QRF model and feature settings."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import cast

from goldilocks_core.contracts import ModelSource, ModelSpec, ModelType, PathLike

MODEL_REGISTRY_ENV = "GOLDILOCKS_MODEL_REGISTRY"
_REGISTRY_RESOURCE = "model_registry.toml"


@dataclass(frozen=True, slots=True)
class ArtifactSpec:
    """Location of supporting model artifacts."""

    source: ModelSource
    location: str
    revision: str | None = None


@dataclass(frozen=True, slots=True)
class QrfFeatureSettings:
    """Settings used to reproduce the QRF feature vector."""

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
    """Resources and settings required for QRF k-point inference."""

    model: ModelSpec
    feature_settings: QrfFeatureSettings
    confidence: float
    correction: float
    metallicity: ArtifactSpec
    metallicity_checkpoint_file: str
    metallicity_atom_init_file: str


def load_default_qrf_config(path: PathLike | None = None) -> QrfKpointsConfig:
    """Load QRF configuration from an explicit, environment, or packaged TOML."""
    registry_path = path or os.environ.get(MODEL_REGISTRY_ENV)
    if registry_path is None:
        registry = resources.files("goldilocks_core").joinpath(_REGISTRY_RESOURCE)
        with registry.open("rb") as registry_file:
            data = tomllib.load(registry_file)
    else:
        with Path(registry_path).open("rb") as registry_file:
            data = tomllib.load(registry_file)

    kpoints = data["defaults"]["kpoints"]
    features = kpoints["features"]
    metallicity = kpoints["metallicity"]
    calibration = kpoints["calibration"]

    return QrfKpointsConfig(
        model=ModelSpec(
            name=kpoints["name"],
            version=kpoints["version"],
            model_type=cast(ModelType, kpoints["model_type"]),
            target=kpoints["target"],
            feature_set=kpoints["feature_set"],
            source=cast(ModelSource, kpoints["source"]),
            location=kpoints["location"],
            revision=kpoints.get("revision"),
        ),
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
        metallicity=ArtifactSpec(
            source=cast(ModelSource, metallicity["source"]),
            location=metallicity["location"],
            revision=metallicity.get("revision"),
        ),
        metallicity_checkpoint_file=metallicity["checkpoint_file"],
        metallicity_atom_init_file=metallicity["atom_init_file"],
    )
