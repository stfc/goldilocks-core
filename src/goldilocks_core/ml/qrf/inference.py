"""QRF k-distance inference.

Encapsulates the QRF model, the metallicity model, feature extraction, and
quantile calibration behind :func:`predict_kdistance`.

Model resources are loaded by :func:`load_qrf_resources` and held as a
:data:`QrfResources` triple by the caller (typically a
:class:`~goldilocks_core.advisors.kdistance_advisor.QrfKDistanceBackend`).
No module-level cache is used — lifecycle ownership lives in the backend.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from pymatgen.core import Structure

from goldilocks_core.contracts import StructureFeatureVector
from goldilocks_core.ml.model_registry import QrfKpointsConfig

__all__ = [
    "KDistancePrediction",
    "QrfResources",
    "load_qrf_resources",
    "predict_kdistance",
    "predict_kdistance_with_resources",
]


@dataclass(frozen=True, slots=True)
class KDistancePrediction:
    """A predicted k-distance interval and its provenance."""

    median: float
    lower: float
    upper: float
    data_source: str
    confidence: float


@dataclass(frozen=True, slots=True)
class QrfResources:
    """Loaded QRF model, metallicity model, and atom-init path.

    Owned by the caller (e.g. a backend instance) so model lifecycle is
    explicit rather than hidden in a module global.

    Attributes:
        model: loaded QRF quantile model.
        metal_model: loaded CGCNN metallicity model.
        atom_init: resolved path to the atom-init feature table.
    """

    model: object
    metal_model: object
    atom_init: str


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


def load_qrf_resources(
    config: QrfKpointsConfig,
    *,
    metallicity_checkpoint: str | None = None,
    metallicity_atom_init: str | None = None,
) -> QrfResources:
    """Load the QRF model, metallicity model, and atom-init path.

    Resources are loaded fresh on each call. Callers that reuse the same
    config across multiple structures should hold the returned
    :class:`QrfResources` and call :func:`predict_kdistance_with_resources`
    per structure to avoid repeated loading.
    """
    from goldilocks_core.ml.models import load_model
    from goldilocks_core.ml.qrf.metallicity import load_metallicity_model

    checkpoint, atom_init = _resolve_metallicity_artifacts(
        config, metallicity_checkpoint, metallicity_atom_init
    )
    return QrfResources(
        model=load_model(config.model),
        metal_model=load_metallicity_model(checkpoint),
        atom_init=atom_init,
    )


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


def predict_kdistance_with_resources(
    structure: Structure,
    config: QrfKpointsConfig,
    resources: QrfResources,
) -> KDistancePrediction:
    """Predict a k-distance interval using pre-loaded ``resources``."""
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
    """Predict a k-distance interval for ``structure`` with the QRF model.

    Loads model resources fresh on each call. Callers that reuse the same
    config across multiple structures should hold a
    :class:`~goldilocks_core.advisors.kdistance_advisor.QrfKDistanceBackend`
    (or call :func:`load_qrf_resources` once and
    :func:`predict_kdistance_with_resources` per structure) to avoid
    repeated loading.
    """
    resources = load_qrf_resources(
        config,
        metallicity_checkpoint=metallicity_checkpoint,
        metallicity_atom_init=metallicity_atom_init,
    )
    return predict_kdistance_with_resources(structure, config, resources)
