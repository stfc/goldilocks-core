"""Load configurable default model and artifact specifications."""

from __future__ import annotations

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
class QrfKpointsConfig:
    """Model and supporting artifacts required by the QRF Kmesh advisor."""

    model: ModelSpec
    confidence: float
    correction: float
    scikit_learn_version: str
    sklearn_quantile_version: str
    joblib_version: str
    metallicity: ArtifactSpec
    metallicity_checkpoint_file: str
    metallicity_atom_init_file: str


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
        metallicity = kpoints["metallicity"]
    except (KeyError, TypeError) as error:
        raise ValueError(
            "Model registry must define defaults.kpoints and its metallicity table."
        ) from error

    _require_advisor(kpoints)
    model_source, model_revision = _require_source(kpoints, "defaults.kpoints")
    artifact_source, artifact_revision = _require_source(
        metallicity,
        "defaults.kpoints.metallicity",
    )
    confidence = _require_float(kpoints, "confidence")
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("defaults.kpoints.confidence must be between 0 and 1.")

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
        confidence=confidence,
        correction=_require_float(kpoints, "correction"),
        scikit_learn_version=_require_string(kpoints, "scikit_learn_version"),
        sklearn_quantile_version=_require_string(kpoints, "sklearn_quantile_version"),
        joblib_version=_require_string(kpoints, "joblib_version"),
        metallicity=ArtifactSpec(
            source=artifact_source,
            location=_require_string(metallicity, "location"),
            revision=artifact_revision,
        ),
        metallicity_checkpoint_file=_require_string(metallicity, "checkpoint_file"),
        metallicity_atom_init_file=_require_string(metallicity, "atom_init_file"),
    )


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
    """Return a required numeric value from a registry table."""
    value = table.get(key)
    if not isinstance(value, int | float):
        raise ValueError(f"Model registry field {key!r} must be numeric.")
    return float(value)
