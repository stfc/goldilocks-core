"""Quantile Random Forest k-distance advisor."""

from __future__ import annotations

import os
from functools import cache

import numpy as np
from pymatgen.core import Structure

from goldilocks_core.contracts import (
    CalculationHints,
    KMeshAdvisor,
    KPointAdvice,
    KPointSelection,
    PathLike,
    Provenance,
    StructureFeatureVector,
)
from goldilocks_core.kmesh import k_distance_to_mesh, resolve_kpoints_from_advice
from goldilocks_core.ml.model_registry import QrfKpointsConfig, load_default_qrf_config


def predict_kdistance_quantiles(
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


def kdistance_to_selection(
    structure: Structure,
    median: float,
    lower: float,
    upper: float,
    *,
    data_source: str,
    confidence: float,
    mesh_type: str = "monkhorst-pack",
) -> KPointSelection:
    """Build a concrete k-point selection from a predicted interval."""
    return KPointSelection(
        grid=k_distance_to_mesh(structure, median),
        shift=(0, 0, 0),
        mesh_type=mesh_type,
        provenance=Provenance(
            source="model",
            reason=(
                f"ML-predicted k-point distance {median:.4f} Å⁻¹ "
                f"(interval {lower:.4f}-{upper:.4f} Å⁻¹)."
            ),
            data_source=data_source,
            confidence=confidence,
        ),
    )


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


def qrf_kdistance_advisor(
    config: QrfKpointsConfig,
    metallicity_checkpoint: str | None = None,
    metallicity_atom_init: str | None = None,
) -> KMeshAdvisor:
    """Return a lazy QRF k-point advisor."""

    @cache
    def load_resources() -> tuple[object, object, str]:
        from goldilocks_core.ml.metallicity import load_metallicity_model
        from goldilocks_core.ml.models import load_model

        checkpoint, atom_init = _resolve_metallicity_artifacts(
            config,
            metallicity_checkpoint,
            metallicity_atom_init,
        )
        return (
            load_model(config.model),
            load_metallicity_model(checkpoint),
            atom_init,
        )

    def advisor(
        structure: Structure,
        hints: CalculationHints,
        kpoint_advice: KPointAdvice,
    ) -> KPointSelection:
        if hints.k_grid is not None or hints.k_spacing is not None:
            return resolve_kpoints_from_advice(structure, hints, kpoint_advice)

        from goldilocks_core.ml.kdistance_features import extract_qrf_features

        qrf, metal_model, atom_init = load_resources()
        features = extract_qrf_features(
            structure,
            metal_model,
            atom_init,
            config.feature_settings,
        )
        median, lower, upper = predict_kdistance_quantiles(
            qrf,
            features,
            config.correction,
        )
        identity = config.model.revision or config.model.version
        return kdistance_to_selection(
            structure,
            median,
            lower,
            upper,
            data_source=f"{config.model.name}@{identity}",
            confidence=config.confidence,
        )

    return advisor


def default_kmesh_advisor(
    *,
    registry_path: PathLike | None = None,
    config: QrfKpointsConfig | None = None,
    metallicity_checkpoint: str | None = None,
    metallicity_atom_init: str | None = None,
) -> KMeshAdvisor:
    """Return the configured default QRF k-point advisor."""
    checkpoint = metallicity_checkpoint or os.environ.get(
        "GOLDILOCKS_METALLICITY_CHECKPOINT"
    )
    atom_init = metallicity_atom_init or os.environ.get(
        "GOLDILOCKS_METALLICITY_ATOM_INIT"
    )

    @cache
    def configured_advisor() -> KMeshAdvisor:
        active_config = config or load_default_qrf_config(registry_path)
        return qrf_kdistance_advisor(active_config, checkpoint, atom_init)

    def advisor(
        structure: Structure,
        hints: CalculationHints,
        kpoint_advice: KPointAdvice,
    ) -> KPointSelection:
        if hints.k_grid is not None or hints.k_spacing is not None:
            return resolve_kpoints_from_advice(structure, hints, kpoint_advice)
        return configured_advisor()(structure, hints, kpoint_advice)

    return advisor
