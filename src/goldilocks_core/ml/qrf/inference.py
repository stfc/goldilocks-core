from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
from pymatgen.core import Structure

from goldilocks_core.assets.store import AssetStore
from goldilocks_core.ml.model_registry import QrfKpointsConfig
from goldilocks_core.ml.models import StructureFeatureVector

__all__ = [
    "KDistancePrediction",
    "QrfResources",
    "load_qrf_resources",
    "predict_kdistance",
    "predict_kdistance_with_resources",
]


@dataclass(frozen=True, slots=True)
class KDistancePrediction:
    median: float
    lower: float
    upper: float
    data_source: str
    confidence: float


@dataclass(frozen=True, slots=True)
class QrfResources:
    model: object
    metal_model: object
    atom_init: str


def _resolve_metallicity_artifacts(
    config: QrfKpointsConfig,
    store: AssetStore,
    checkpoint: str | None,
    atom_init: str | None,
) -> tuple[str, str]:
    if checkpoint is not None and atom_init is not None:
        return checkpoint, atom_init
    if config.metallicity_asset is None:
        base = config.metallicity_model.location
        return (
            checkpoint or str(Path(base) / config.metallicity_checkpoint_file),
            atom_init or str(Path(base) / config.metallicity_atom_init_file),
        )
    installed = store.resolve_spec(config.metallicity_asset)
    return (
        checkpoint or str(installed.path(config.metallicity_checkpoint_file)),
        atom_init or str(installed.path(config.metallicity_atom_init_file)),
    )


def load_qrf_resources(
    config: QrfKpointsConfig,
    *,
    metallicity_checkpoint: str | None = None,
    metallicity_atom_init: str | None = None,
    asset_store: AssetStore | None = None,
) -> QrfResources:
    from goldilocks_core.ml.models import load_model
    from goldilocks_core.ml.qrf.metallicity import load_metallicity_model

    store = asset_store or AssetStore()
    checkpoint, atom_init = _resolve_metallicity_artifacts(
        config, store, metallicity_checkpoint, metallicity_atom_init
    )
    model = config.model
    if config.model_asset is not None:
        installed = store.resolve_spec(config.model_asset)
        model = replace(
            model, source="local", location=str(installed.path(config.model_file))
        )
    return QrfResources(
        model=load_model(model),
        metal_model=load_metallicity_model(checkpoint),
        atom_init=atom_init,
    )


def _predict_kdistance_quantiles(
    model: object,
    features: StructureFeatureVector,
    correction: float = 0.0,
) -> tuple[float, float, float]:
    raw = np.asarray(
        model.predict(np.asarray(features.values, dtype=float).reshape(1, -1)),
        dtype=float,
    )
    if raw.size != 3:
        raise ValueError(f"Expected 3 QRF quantiles; got {raw.size}.")

    lower, median, upper = raw.reshape(3, -1)[:, 0]
    result = (float(median), float(lower - correction), float(upper + correction))
    if not np.isfinite(result).all() or min(result) <= 0:
        raise ValueError("QRF k-distance prediction must be finite and positive.")
    if not result[1] <= result[0] <= result[2]:
        raise ValueError("QRF k-distance quantiles are not ordered.")
    return result


def predict_kdistance_with_resources(
    structure: Structure,
    config: QrfKpointsConfig,
    resources: QrfResources,
) -> KDistancePrediction:
    from goldilocks_core.ml.qrf.features import extract_qrf_features

    features = extract_qrf_features(
        structure,
        resources.metal_model,
        resources.atom_init,
        config.feature_settings,
    )
    median, lower, upper = _predict_kdistance_quantiles(
        resources.model, features, config.correction
    )
    identity = config.model.revision or config.model.version
    return KDistancePrediction(
        median=median,
        lower=lower,
        upper=upper,
        data_source=f"{config.model.name}@{identity}",
        confidence=config.confidence,
    )


def predict_kdistance(
    structure: Structure,
    config: QrfKpointsConfig,
    *,
    metallicity_checkpoint: str | None = None,
    metallicity_atom_init: str | None = None,
) -> KDistancePrediction:
    resources = load_qrf_resources(
        config,
        metallicity_checkpoint=metallicity_checkpoint,
        metallicity_atom_init=metallicity_atom_init,
    )
    return predict_kdistance_with_resources(structure, config, resources)
