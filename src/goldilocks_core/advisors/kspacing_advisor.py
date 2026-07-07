"""Quantile Random Forest (QRF) k-spacing advisor.

The QRF model predicts a VASP-style k-point spacing (Å⁻¹) as three quantiles
(lower, median, upper). The median drives the concrete mesh; the interval and
the model's confidence level are recorded in provenance. This module holds the
model-agnostic post-prediction logic; feature extraction (which pulls heavy ML
dependencies) is supplied separately.
"""

from __future__ import annotations

import numpy as np
from pymatgen.core import Structure

from goldilocks_core.contracts import (
    KPointSelection,
    ModelSpec,
    Provenance,
    StructureFeatureVector,
)
from goldilocks_core.kmesh import k_distance_to_mesh

# Built-in default k-point model: the STFC QRF at 95% confidence, resolved from
# the Hugging Face Hub. Feature set names the extractor the model was trained on.
DEFAULT_KPOINTS_MODEL = ModelSpec(
    name="kpoints-goldilocks-QRF",
    version="QRF95",
    model_type="random_forest",
    target="k_spacing",
    feature_set="qrf_comp_struct_soap_lattice_metal",
    source="huggingface",
    location="STFC-SCD/kpoints-goldilocks-QRF::QRF95.pkl",
    revision=None,
)

# Confidence level of the default model and the calibrated interval correction
# (widens the interval), from the trained QRF at 0.95. See the goldilocks
# k-spacing reference implementation.
DEFAULT_KPOINTS_CONFIDENCE = 0.95
DEFAULT_KPOINTS_CORRECTION = -0.0016


def predict_kspacing_quantiles(
    model: object,
    features: StructureFeatureVector,
    correction: float = DEFAULT_KPOINTS_CORRECTION,
) -> tuple[float, float, float]:
    """Return (median, lower, upper) k-spacing in Å⁻¹ from a QRF prediction.

    The QRF returns three quantiles ``[lower, median, upper]`` for the single
    input row. ``correction`` calibrates (widens) the interval bounds.

    Raises:
        AttributeError: If the model has no ``predict`` method.
        ValueError: If the prediction does not yield three quantiles.
    """
    if not hasattr(model, "predict"):
        raise AttributeError("QRF model does not provide a 'predict' method.")

    raw = np.asarray(model.predict(features.values.reshape(1, -1)), dtype=float)
    if raw.size != 3:
        raise ValueError(
            f"Expected 3 quantiles from the QRF prediction; got {raw.size}."
        )

    lower, median, upper = raw.reshape(3, -1)[:, 0]
    return float(median), float(lower) - correction, float(upper) + correction


def kspacing_to_selection(
    structure: Structure,
    median: float,
    lower: float,
    upper: float,
    *,
    data_source: str,
    confidence: float = DEFAULT_KPOINTS_CONFIDENCE,
    mesh_type: str = "monkhorst-pack",
) -> KPointSelection:
    """Build a concrete k-point selection from a predicted k-spacing interval.

    The median spacing sets the mesh; the interval and confidence level are
    recorded in provenance so callers can judge the prediction.
    """
    return KPointSelection(
        grid=k_distance_to_mesh(structure, median),
        shift=(0, 0, 0),
        mesh_type=mesh_type,
        provenance=Provenance(
            source="model",
            reason=(
                f"ML-predicted k-point spacing {median:.4f} Å⁻¹ "
                f"(interval {lower:.4f}-{upper:.4f} Å⁻¹)."
            ),
            data_source=data_source,
            confidence=confidence,
        ),
    )
