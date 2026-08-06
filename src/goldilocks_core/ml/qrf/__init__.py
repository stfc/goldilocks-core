"""QRF k-distance inference boundary.

Advisors call :func:`predict_kdistance` and nothing else here. The QRF model,
the metallicity model, feature extraction, and quantile calibration are all
encapsulated behind that one entry point.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

import numpy as np
from pymatgen.core import Structure

from goldilocks_core.contracts import StructureFeatureVector
from goldilocks_core.ml.model_registry import QrfKpointsConfig

__all__ = ["KDistancePrediction", "predict_kdistance"]


@dataclass(frozen=True, slots=True)
class KDistancePrediction:
    """A predicted k-distance interval and its provenance."""

    median: float
    lower: float
    upper: float
    data_source: str
    confidence: float


# ``QrfKpointsConfig`` carries an intentionally mutable ``ModelSpec`` (see
# ``test_model_spec_remains_mutable_before_load_time_validation``), so the
# config is unhashable. Cache loaded models by the config's identity and pin
# the config so its id stays stable while it is cached. This mirrors the
# previous per-advisor ``@cache load_resources()`` closure: each advisor loads
# its models exactly once.
_config_pins: dict[int, QrfKpointsConfig] = {}


def _resolve_metallicity_artifacts(
    config: QrfKpointsConfig,
    checkpoint: str | None,
    atom_init: str | None,
) -> tuple[str, str]:
    """Resolve configured metallicity artifacts to local paths."""
    from goldilocks_core.ml.models import resolve_artifact

    return (
        checkpoint
        or resolve_artifact(config.metallicity, config.metallicity_checkpoint_file),
        atom_init
        or resolve_artifact(config.metallicity, config.metallicity_atom_init_file),
    )


@cache
def _load_resources(
    config_id: int,
    metallicity_checkpoint: str | None,
    metallicity_atom_init: str | None,
) -> tuple[object, object, str]:
    """Load and cache the QRF model, metallicity model, and atom-init path."""
    config = _config_pins[config_id]
    from goldilocks_core.ml.models import load_model
    from goldilocks_core.ml.qrf.metallicity import load_metallicity_model

    checkpoint, atom_init = _resolve_metallicity_artifacts(
        config, metallicity_checkpoint, metallicity_atom_init
    )
    return load_model(config.model), load_metallicity_model(checkpoint), atom_init


def _predict_kdistance_quantiles(
    model: object,
    features: StructureFeatureVector,
    correction: float = 0.0,
) -> tuple[float, float, float]:
    """Return median, lower, and upper k-distance in Å⁻¹."""
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


def predict_kdistance(
    structure: Structure,
    config: QrfKpointsConfig,
    *,
    metallicity_checkpoint: str | None = None,
    metallicity_atom_init: str | None = None,
) -> KDistancePrediction:
    """Predict a k-distance interval for ``structure`` with the QRF model."""
    from goldilocks_core.ml.qrf.features import extract_qrf_features

    _config_pins.setdefault(id(config), config)
    model, metal_model, atom_init = _load_resources(
        id(config),
        metallicity_checkpoint,
        metallicity_atom_init,
    )
    features = extract_qrf_features(
        structure,
        metal_model,
        atom_init,
        config.feature_settings,
    )
    median, lower, upper = _predict_kdistance_quantiles(
        model, features, config.correction
    )
    identity = config.model.revision or config.model.version
    return KDistancePrediction(
        median=median,
        lower=lower,
        upper=upper,
        data_source=f"{config.model.name}@{identity}",
        confidence=config.confidence,
    )
