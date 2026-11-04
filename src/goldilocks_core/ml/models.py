from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Annotated, Any, cast, get_args

from goldilocks_core.assets.records import AssetFile, AssetSpec
from goldilocks_core.serialization import Portable
from goldilocks_core.types import ModelType, PathLike


@dataclass(slots=True)
class ModelSpec:
    name: str
    version: str
    model_type: ModelType
    target: str
    feature_set: str
    location: Annotated[str, Portable()]
    revision: str | None = None
    licence: str | None = None
    licence_text: Annotated[str | None, Portable()] = None
    citation: str | None = None


MODEL_REGISTRY_ENV = "GOLDILOCKS_MODEL_REGISTRY"
_REGISTRY_RESOURCE = "registry.toml"
_VALID_MODEL_TYPES = frozenset(get_args(ModelType))


@dataclass(frozen=True, slots=True)
class RegisteredModel:
    id: str
    role: str
    spec: ModelSpec


@dataclass(frozen=True, slots=True)
class QrfKpointsConfig:
    model: ModelSpec
    model_asset: AssetSpec | None
    model_file: str
    confidence: float
    correction: float
    metallicity_model: ModelSpec
    metallicity_asset: AssetSpec | None
    metallicity_checkpoint_file: str
    metallicity_atom_init_file: str


def load_default_qrf_config(path: PathLike | None = None) -> QrfKpointsConfig:
    data = _load_registry(path)
    kpoints = data["defaults"]["kpoints"]
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
        confidence=kpoints["interval_confidence"],
        correction=calibration["correction"],
        metallicity_model=_model_spec(metallicity, checkpoint_file),
        metallicity_asset=metallicity_asset,
        metallicity_checkpoint_file=checkpoint_file,
        metallicity_atom_init_file=atom_init_file,
    )


@dataclass(frozen=True, slots=True)
class MlClassifierConfig:
    """One standalone ML model this build can call directly (v2 epic 11,
    #11): is_metal/is_magnetic today, registered under
    ``[defaults.<name>]`` in registry.toml. Distinct from
    ``QrfKpointsConfig`` above, which is kpoints' own *embedded*
    dependency shape (a feature extractor with no decision threshold of
    its own, never called standalone) -- these are complete,
    ``goldilocks_ml.inference.load_model``-loadable releases."""

    role: str
    """``ml_target`` in ``capabilities.py``'s vocabulary (e.g.
    ``"is_metal"``) -- what ``analysis/is_metal.py`` and friends ask
    ``ml.predict.predict`` for by name."""
    model: ModelSpec
    asset: AssetSpec


ML_CLASSIFIER_ROLES: tuple[str, ...] = ("is_metal", "is_magnetic")
"""Every standalone classifier registry.toml declares under
``[defaults.<role>]`` -- the ``k_distance`` (QRF) case predates this and
stays its own ``QrfKpointsConfig`` shape above; a role added here needs
no other change than a matching registry.toml section, since
``load_ml_classifier``/``ml.predict.predict`` are both already generic
over it."""


def load_ml_classifier(role: str, path: PathLike | None = None) -> MlClassifierConfig:
    """Load one ``[defaults.<role>]`` standalone classifier section."""
    if role not in ML_CLASSIFIER_ROLES:
        raise ValueError(
            f"unknown ML classifier role {role!r}; this build knows: "
            + ", ".join(ML_CLASSIFIER_ROLES)
        )
    data = _load_registry(path)
    section = data["defaults"][role]
    asset = _asset_spec(section["asset"])
    if asset is None:
        raise ValueError(f"[defaults.{role}] must declare an [defaults.{role}.asset]")
    return MlClassifierConfig(
        role=role, model=_model_spec(section, asset.id), asset=asset
    )


def registered_ml_classifiers(
    path: PathLike | None = None,
) -> tuple[MlClassifierConfig, ...]:
    return tuple(load_ml_classifier(role, path) for role in ML_CLASSIFIER_ROLES)


def _load_registry(path: PathLike | None) -> dict[str, Any]:
    registry_path = path or os.environ.get(MODEL_REGISTRY_ENV)
    if registry_path is None:
        registry = resources.files("goldilocks_core.ml").joinpath(_REGISTRY_RESOURCE)
        with registry.open("rb") as registry_file:
            return tomllib.load(registry_file)
    with Path(registry_path).open("rb") as registry_file:
        return tomllib.load(registry_file)


def registered_models(path: PathLike | None = None) -> tuple[RegisteredModel, ...]:
    config = load_default_qrf_config(path)
    models = [
        RegisteredModel(
            id=config.model_asset.id if config.model_asset else config.model.name,
            role="k_point_advisor",
            spec=config.model,
        ),
        RegisteredModel(
            id=(
                config.metallicity_asset.id
                if config.metallicity_asset
                else config.metallicity_model.name
            ),
            role="metallicity_classifier",
            spec=config.metallicity_model,
        ),
    ]
    models.extend(
        RegisteredModel(
            id=classifier.asset.id, role=classifier.role, spec=classifier.model
        )
        for classifier in registered_ml_classifiers(path)
    )
    return tuple(models)


def model_asset_specs(path: PathLike | None = None) -> tuple[AssetSpec, ...]:
    config = load_default_qrf_config(path)
    specs = [
        spec
        for spec in (config.model_asset, config.metallicity_asset)
        if spec is not None
    ]
    specs.extend(classifier.asset for classifier in registered_ml_classifiers(path))
    return tuple(specs)


def _asset_spec(data: dict[str, Any] | None) -> AssetSpec | None:
    if data is None:
        return None
    files = tuple(
        AssetFile(
            role=file["role"],
            path=file["path"],
            url=file["url"],
            checksum=file.get("checksum"),
            size=file.get("size"),
        )
        for file in data["files"]
    )
    invalid_checksums = [
        file.role
        for file in files
        if file.checksum is not None and not file.checksum.startswith("sha256:")
    ]
    if invalid_checksums:
        raise ValueError(
            f"model asset {data['id']!r} checksums must use sha256: "
            + ", ".join(invalid_checksums)
        )
    if "licence" not in {file.role for file in files}:
        raise ValueError(f"model asset {data['id']!r} must include licence material")
    return AssetSpec(
        id=data["id"],
        version=str(data["version"]),
        files=files,
        preparation_revision=str(data.get("preparation_revision", "1")),
    )


def _model_spec(data: dict[str, Any], location: str) -> ModelSpec:
    identity = {
        "name": data["name"],
        "version": str(data["version"]),
        "target": data["target"],
        "feature_set": data["feature_set"],
    }
    for field, value in identity.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"model {field} must be a non-empty string; got {value!r}")
    revision = data.get("revision")
    if revision is not None and (not isinstance(revision, str) or not revision.strip()):
        raise ValueError(
            f"model revision must be a non-empty string, or absent; got {revision!r}"
        )

    model_type_value = data["model_type"]
    if model_type_value not in _VALID_MODEL_TYPES:
        valid = ", ".join(sorted(_VALID_MODEL_TYPES))
        raise ValueError(f"model type must be one of {valid}; got {model_type_value!r}")
    model_type = cast(ModelType, model_type_value)
    optional_material = {
        field: data.get(field) for field in ("licence", "licence_text", "citation")
    }
    for field, value in optional_material.items():
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(
                f"model {field} must be a non-empty string, or absent; got {value!r}"
            )

    return ModelSpec(
        name=identity["name"],
        version=identity["version"],
        model_type=model_type,
        target=identity["target"],
        feature_set=identity["feature_set"],
        location=data.get("location", location),
        revision=revision,
        **optional_material,
    )


def _role_path(spec: AssetSpec, role: str) -> str:
    try:
        return next(file.path for file in spec.files if file.role == role)
    except StopIteration as error:
        raise ValueError(
            f"asset {spec.id}@{spec.version} lacks required role {role!r}"
        ) from error
