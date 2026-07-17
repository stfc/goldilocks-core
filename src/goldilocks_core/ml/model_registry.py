"""Load configurable default model and artifact specifications."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, cast

from goldilocks_core.contracts import ModelSource, ModelSpec, ModelType, PathLike

MODEL_REGISTRY_ENV = "GOLDILOCKS_MODEL_REGISTRY"
_REGISTRY_RESOURCE = "model_registry.toml"
_HUGGINGFACE_COMMIT = re.compile(r"[0-9a-f]{40}")


@dataclass(frozen=True, slots=True)
class ArtifactSpec:
    """Location of a versioned set of supporting model artifacts."""

    source: ModelSource
    location: str
    revision: str | None = None


@dataclass(frozen=True, slots=True)
class QrfFeatureSettings:
    """Registry-owned settings that determine the QRF feature values."""

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

    def to_dict(self) -> dict[str, object]:
        """Return the settings in their canonical registry representation."""
        return {
            "composition_featurizers": list(self.composition_featurizers),
            "element_property_preset": self.element_property_preset,
            "impute_nan": self.impute_nan,
            "structure_featurizers": list(self.structure_featurizers),
            "global_symmetry_features": list(self.global_symmetry_features),
            "density_features": list(self.density_features),
            "soap_species": self.soap_species,
            "soap_r_cut": self.soap_r_cut,
            "soap_n_max": self.soap_n_max,
            "soap_l_max": self.soap_l_max,
            "soap_sigma": self.soap_sigma,
            "soap_periodic": self.soap_periodic,
            "soap_sparse": self.soap_sparse,
            "soap_reduction": self.soap_reduction,
            "lattice_symprec": self.lattice_symprec,
            "metallicity_graph_radius": self.metallicity_graph_radius,
            "metallicity_max_neighbors": self.metallicity_max_neighbors,
        }


@dataclass(frozen=True, slots=True)
class QrfCalibration:
    """Configured interval calibration applied to raw QRF quantiles."""

    method: str
    correction: float


@dataclass(frozen=True, slots=True)
class QrfKpointsConfig:
    """Registry-owned QRF Kmesh inference configuration."""

    model: ModelSpec
    feature_schema: str
    feature_count: int
    feature_settings: QrfFeatureSettings
    interval_confidence: float
    interval_quantiles: tuple[float, float, float]
    calibration: QrfCalibration
    metallicity: ArtifactSpec
    metallicity_checkpoint_file: str
    metallicity_atom_init_file: str

    def to_dict(self) -> dict[str, object]:
        """Return the inference-relevant registry values as structured data."""
        return {
            "advisor": "qrf_kdistance",
            "model": {
                "name": self.model.name,
                "version": self.model.version,
                "model_type": self.model.model_type,
                "target": self.model.target,
                "feature_set": self.model.feature_set,
                "source": self.model.source,
                "location": self.model.location,
                "revision": self.model.revision,
            },
            "feature_schema": self.feature_schema,
            "feature_count": self.feature_count,
            "feature_settings": self.feature_settings.to_dict(),
            "interval": {
                "confidence": self.interval_confidence,
                "quantiles": list(self.interval_quantiles),
            },
            "calibration": {
                "method": self.calibration.method,
                "correction": self.calibration.correction,
            },
            "metallicity": {
                "source": self.metallicity.source,
                "location": self.metallicity.location,
                "revision": self.metallicity.revision,
                "checkpoint_file": self.metallicity_checkpoint_file,
                "atom_init_file": self.metallicity_atom_init_file,
            },
        }

    @property
    def digest(self) -> str:
        """Return a deterministic SHA-256 digest of the inference configuration."""
        encoded = json.dumps(
            self.to_dict(),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def load_default_qrf_config(path: PathLike | None = None) -> QrfKpointsConfig:
    """Load the default QRF configuration from a package or custom registry.

    ``path`` takes precedence over ``GOLDILOCKS_MODEL_REGISTRY``. When neither
    is set, the registry packaged with goldilocks-core is used.
    """
    registry_path = path or os.environ.get(MODEL_REGISTRY_ENV)
    if registry_path is None:
        registry = resources.files("goldilocks_core").joinpath(_REGISTRY_RESOURCE)
        with registry.open("rb") as registry_file:
            data = tomllib.load(registry_file)
    else:
        with Path(registry_path).open("rb") as registry_file:
            data = tomllib.load(registry_file)

    try:
        kpoints = data["defaults"]["kpoints"]
        features = kpoints["features"]
        calibration = kpoints["calibration"]
        metallicity = kpoints["metallicity"]
    except (KeyError, TypeError) as error:
        raise ValueError(
            "Model registry must define defaults.kpoints plus features, "
            "calibration, and metallicity tables."
        ) from error

    _require_advisor(kpoints)
    model_source, model_revision = _require_source(kpoints, "defaults.kpoints")
    artifact_source, artifact_revision = _require_source(
        metallicity,
        "defaults.kpoints.metallicity",
    )
    confidence = _require_float(kpoints, "interval_confidence")
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(
            "defaults.kpoints.interval_confidence must be between 0 and 1."
        )
    quantiles = _require_float_tuple(kpoints, "interval_quantiles", length=3)
    if not (
        0.0 <= quantiles[0] < quantiles[1] < quantiles[2] <= 1.0
        and quantiles[1] == 0.5
        and math.isclose(quantiles[2] - quantiles[0], confidence)
    ):
        raise ValueError(
            "defaults.kpoints.interval_quantiles must be ordered lower, 0.5, "
            "upper quantiles spanning interval_confidence."
        )

    feature_settings = _load_feature_settings(features)

    return QrfKpointsConfig(
        model=ModelSpec(
            name=_require_string(kpoints, "name"),
            version=_require_string(kpoints, "version"),
            model_type=cast(ModelType, _require_string(kpoints, "model_type")),
            target=_require_string(kpoints, "target"),
            feature_set=_require_string(kpoints, "feature_set"),
            source=model_source,
            location=_require_string(kpoints, "location"),
            revision=model_revision,
        ),
        feature_schema=_require_string(kpoints, "feature_schema"),
        feature_count=_require_positive_int(kpoints, "feature_count"),
        feature_settings=feature_settings,
        interval_confidence=confidence,
        interval_quantiles=cast(tuple[float, float, float], quantiles),
        calibration=QrfCalibration(
            method=_require_string(calibration, "method"),
            correction=_require_float(calibration, "correction"),
        ),
        metallicity=ArtifactSpec(
            source=artifact_source,
            location=_require_string(metallicity, "location"),
            revision=artifact_revision,
        ),
        metallicity_checkpoint_file=_require_string(metallicity, "checkpoint_file"),
        metallicity_atom_init_file=_require_string(metallicity, "atom_init_file"),
    )


def _load_feature_settings(features: dict[str, Any]) -> QrfFeatureSettings:
    """Parse all feature-producing settings from the registry."""
    settings = QrfFeatureSettings(
        composition_featurizers=_require_string_tuple(
            features, "composition_featurizers"
        ),
        element_property_preset=_require_string(features, "element_property_preset"),
        impute_nan=_require_bool(features, "impute_nan"),
        structure_featurizers=_require_string_tuple(features, "structure_featurizers"),
        global_symmetry_features=_require_string_tuple(
            features, "global_symmetry_features"
        ),
        density_features=_require_string_tuple(features, "density_features"),
        soap_species=_require_string(features, "soap_species"),
        soap_r_cut=_require_positive_float(features, "soap_r_cut"),
        soap_n_max=_require_positive_int(features, "soap_n_max"),
        soap_l_max=_require_positive_int(features, "soap_l_max"),
        soap_sigma=_require_positive_float(features, "soap_sigma"),
        soap_periodic=_require_bool(features, "soap_periodic"),
        soap_sparse=_require_bool(features, "soap_sparse"),
        soap_reduction=_require_string(features, "soap_reduction"),
        lattice_symprec=_require_positive_float(features, "lattice_symprec"),
        metallicity_graph_radius=_require_positive_float(
            features, "metallicity_graph_radius"
        ),
        metallicity_max_neighbors=_require_positive_int(
            features, "metallicity_max_neighbors"
        ),
    )
    if settings.soap_reduction != "mean":
        raise ValueError("defaults.kpoints.features.soap_reduction must be 'mean'.")
    return settings


def _require_advisor(kpoints: dict[str, Any]) -> None:
    """Reject registry entries intended for an unsupported advisor."""
    advisor = _require_string(kpoints, "advisor")
    if advisor != "qrf_kdistance":
        raise ValueError(
            f"defaults.kpoints.advisor must be 'qrf_kdistance'; got {advisor!r}."
        )


def is_immutable_huggingface_revision(revision: str | None) -> bool:
    """Return whether a revision is a full immutable Hugging Face commit ID."""
    return revision is not None and _HUGGINGFACE_COMMIT.fullmatch(revision) is not None


def _require_source(
    table: dict[str, Any],
    table_name: str,
) -> tuple[ModelSource, str | None]:
    """Validate a model source and require immutable remote revisions."""
    source = _require_string(table, "source")
    if source not in {"huggingface", "local"}:
        raise ValueError(f"{table_name}.source is unsupported: {source!r}.")
    revision = _optional_string(table, "revision")
    if source == "huggingface" and not is_immutable_huggingface_revision(revision):
        raise ValueError(
            f"{table_name}.revision must be a full 40-character "
            "huggingface commit hash."
        )
    return cast(ModelSource, source), revision


def _require_string(table: dict[str, Any], key: str) -> str:
    """Return a required non-empty string from a registry table."""
    value = table.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Model registry field {key!r} must be a non-empty string.")
    return value


def _optional_string(table: dict[str, Any], key: str) -> str | None:
    """Return an optional string from a registry table."""
    value = table.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"Model registry field {key!r} must be a non-empty string.")
    return value


def _require_float(table: dict[str, Any], key: str) -> float:
    """Return a required finite numeric value from a registry table."""
    value = table.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"Model registry field {key!r} must be numeric.")
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError(f"Model registry field {key!r} must be finite.")
    return converted


def _require_positive_float(table: dict[str, Any], key: str) -> float:
    """Return a required finite positive floating-point setting."""
    value = _require_float(table, key)
    if value <= 0:
        raise ValueError(f"Model registry field {key!r} must be positive.")
    return value


def _require_positive_int(table: dict[str, Any], key: str) -> int:
    """Return a required positive integer setting."""
    value = table.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"Model registry field {key!r} must be a positive integer.")
    return value


def _require_bool(table: dict[str, Any], key: str) -> bool:
    """Return a required boolean setting."""
    value = table.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"Model registry field {key!r} must be a boolean.")
    return value


def _require_string_tuple(table: dict[str, Any], key: str) -> tuple[str, ...]:
    """Return a required non-empty array of non-empty strings."""
    value = table.get(key)
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item for item in value)
    ):
        raise ValueError(
            f"Model registry field {key!r} must be a non-empty string array."
        )
    return tuple(value)


def _require_float_tuple(
    table: dict[str, Any], key: str, *, length: int
) -> tuple[float, ...]:
    """Return a fixed-length array of finite numbers."""
    value = table.get(key)
    if not isinstance(value, list) or len(value) != length:
        raise ValueError(f"Model registry field {key!r} must contain {length} numbers.")
    converted = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int | float):
            raise ValueError(
                f"Model registry field {key!r} must contain {length} numbers."
            )
        number = float(item)
        if not math.isfinite(number):
            raise ValueError(f"Model registry field {key!r} must be finite.")
        converted.append(number)
    return tuple(converted)
