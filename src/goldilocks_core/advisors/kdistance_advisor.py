"""Quantile Random Forest (QRF) k-distance advisor.

The registry defines the inference configuration. Successful model selections
carry a compact, reproducible identity record in provenance; unavailable or
incompatible inference falls back to advice.
"""

from __future__ import annotations

import os
from dataclasses import replace
from threading import Lock

import numpy as np
from pymatgen.core import Structure

from goldilocks_core.contracts import (
    CalculationHints,
    JsonDict,
    KMeshAdvisor,
    KPointAdvice,
    KPointSelection,
    PathLike,
    Provenance,
    StructureFeatureVector,
)
from goldilocks_core.kmesh import k_distance_to_mesh, resolve_kpoints_from_advice
from goldilocks_core.ml.model_registry import (
    MODEL_REGISTRY_ENV,
    QrfKpointsConfig,
    is_immutable_huggingface_revision,
    load_default_qrf_config,
)


def _validate_kdistance_interval(
    median: float,
    lower: float,
    upper: float,
) -> None:
    """Reject non-finite, non-positive, or misordered k-distance values."""
    values = np.asarray([lower, median, upper], dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("QRF k-distance prediction must contain only finite values.")
    if (values <= 0).any():
        raise ValueError("QRF k-distance prediction values must be positive.")
    if not lower <= median <= upper:
        raise ValueError(
            "QRF k-distance interval must satisfy lower <= median <= upper."
        )


def predict_kdistance_quantiles(
    model: object,
    features: StructureFeatureVector,
    correction: float = 0.0,
) -> tuple[float, float, float]:
    """Return (median, lower, upper) k-distance in Å⁻¹ from a QRF prediction."""
    if not hasattr(model, "predict"):
        raise AttributeError("QRF model does not provide a 'predict' method.")

    feature_values = np.asarray(features.values, dtype=float)
    if not np.isfinite(feature_values).all():
        raise ValueError("QRF features must contain only finite values.")

    raw = np.asarray(model.predict(feature_values.reshape(1, -1)), dtype=float)
    if raw.size != 3:
        raise ValueError(
            f"Expected 3 quantiles from the QRF prediction; got {raw.size}."
        )

    raw_lower, raw_median, raw_upper = raw.reshape(3, -1)[:, 0]
    median = float(raw_median)
    lower = float(raw_lower) - correction
    upper = float(raw_upper) + correction
    _validate_kdistance_interval(median, lower, upper)
    return median, lower, upper


def kdistance_to_selection(
    structure: Structure,
    median: float,
    lower: float,
    upper: float,
    *,
    data_source: str,
    confidence: float,
    details: JsonDict | None = None,
    mesh_type: str = "monkhorst-pack",
) -> KPointSelection:
    """Build a concrete k-point selection from a predicted interval."""
    _validate_kdistance_interval(median, lower, upper)
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
            details=details,
        ),
    )


def _heuristic_fallback(
    structure: Structure,
    hints: CalculationHints,
    advice: KPointAdvice,
    error: Exception,
    *,
    inference_details: JsonDict,
    failure_stage: str,
) -> KPointSelection:
    """Resolve heuristic k-points and record an attempted QRF inference."""
    error_message = str(error) or error.__class__.__name__
    selection = resolve_kpoints_from_advice(structure, hints, advice)
    warning = (
        "ML k-point model unavailable; used heuristic k-point advice "
        f"({error_message})."
    )
    return replace(
        selection,
        provenance=replace(
            selection.provenance,
            source="fallback",
            reason="Use heuristic k-point advice because QRF inference failed.",
            details={
                "qrf_inference": {
                    **inference_details.get("qrf_inference", {}),
                    "fallback": True,
                    "failure": {
                        "stage": failure_stage,
                        "type": error.__class__.__name__,
                        "message": error_message,
                    },
                }
            },
            warnings=(*selection.provenance.warnings, warning),
        ),
    )


def _unparsed_registry_details(registry_path: PathLike | None) -> JsonDict:
    """Describe a registry failure before a canonical QRF configuration exists."""
    registry: JsonDict = {"status": "unparsed"}
    if registry_path is not None:
        registry["path"] = str(registry_path)
    return {"qrf_inference": {"registry": registry}}


def _resolve_metallicity_artifacts(
    config: QrfKpointsConfig,
    checkpoint: str | None,
    atom_init: str | None,
) -> tuple[str, str]:
    """Resolve configured metallicity artifacts to local paths."""
    if checkpoint is not None and atom_init is not None:
        return checkpoint, atom_init

    from goldilocks_core.ml.models import resolve_artifact

    checkpoint = checkpoint or resolve_artifact(
        config.metallicity,
        config.metallicity_checkpoint_file,
    )
    atom_init = atom_init or resolve_artifact(
        config.metallicity,
        config.metallicity_atom_init_file,
    )
    return checkpoint, atom_init


def _validate_qrf_contract(config: QrfKpointsConfig) -> None:
    """Validate QRF schema and calibration semantics."""
    from goldilocks_core.ml.kdistance_features import (
        QRF_FEATURE_COUNT,
        QRF_FEATURE_SCHEMA,
        QRF_FEATURE_SET,
    )

    if config.model.source == "huggingface" and not (
        is_immutable_huggingface_revision(config.model.revision)
    ):
        raise ValueError(
            "QRF huggingface model requires a full immutable commit revision."
        )
    if config.metallicity.source == "huggingface" and not (
        is_immutable_huggingface_revision(config.metallicity.revision)
    ):
        raise ValueError(
            "QRF huggingface metallicity artifacts require a full immutable "
            "commit revision."
        )
    if config.model.model_type != "random_forest":
        raise ValueError("QRF advisor requires model_type='random_forest'.")
    if config.model.target != "k_distance":
        raise ValueError("QRF advisor requires target='k_distance'.")
    if config.model.feature_set != QRF_FEATURE_SET:
        raise ValueError(
            f"QRF advisor requires feature_set={QRF_FEATURE_SET!r}; "
            f"got {config.model.feature_set!r}."
        )
    if config.feature_schema != QRF_FEATURE_SCHEMA:
        raise ValueError(
            f"QRF extractor requires feature_schema={QRF_FEATURE_SCHEMA!r}; "
            f"got {config.feature_schema!r}."
        )
    if config.feature_count != QRF_FEATURE_COUNT:
        raise ValueError(
            f"QRF extractor requires feature_count={QRF_FEATURE_COUNT}; "
            f"got {config.feature_count}."
        )
    if config.calibration.method != "symmetric_additive_bounds-v1":
        raise ValueError(
            "QRF advisor requires calibration method 'symmetric_additive_bounds-v1'."
        )


def _validate_loaded_qrf_quantiles(
    model: object,
    config: QrfKpointsConfig,
) -> None:
    """Require the loaded model to implement the registry's quantile contract."""
    model_quantiles = getattr(model, "q", None)
    if model_quantiles is None and hasattr(model, "get_params"):
        parameters = model.get_params(deep=False)
        model_quantiles = parameters.get("q")
    if model_quantiles is None:
        raise ValueError(
            "Loaded QRF model does not expose its configured quantiles as 'q'."
        )

    try:
        quantiles = np.asarray(model_quantiles, dtype=float).reshape(-1)
    except (TypeError, ValueError) as error:
        raise ValueError(
            "Loaded QRF model has an invalid quantile configuration."
        ) from error
    expected = np.asarray(config.interval_quantiles, dtype=float)
    if quantiles.shape != expected.shape or not np.allclose(
        quantiles,
        expected,
        rtol=0.0,
        atol=1e-12,
    ):
        raise ValueError(
            "Loaded QRF model quantiles do not match the registry: "
            f"expected {config.interval_quantiles!r}, got {tuple(quantiles)!r}."
        )


def _qrf_contract_details(config: QrfKpointsConfig) -> JsonDict:
    """Build the compact QRF identity record available before loading."""
    return {
        "qrf_inference": {
            "config_digest": config.digest,
            "model": {
                "name": config.model.name,
                "version": config.model.version,
                "source": config.model.source,
                "location": config.model.location,
                "revision": config.model.revision,
            },
            "feature_schema": config.feature_schema,
            "feature_count": config.feature_count,
            "interval": {
                "confidence": config.interval_confidence,
                "quantiles": list(config.interval_quantiles),
            },
            "calibration": {
                "method": config.calibration.method,
                "correction": config.calibration.correction,
            },
            "metallicity": {
                "source": config.metallicity.source,
                "location": config.metallicity.location,
                "revision": config.metallicity.revision,
                "checkpoint_file": config.metallicity_checkpoint_file,
                "atom_init_file": config.metallicity_atom_init_file,
            },
        }
    }


def qrf_kdistance_advisor(
    config: QrfKpointsConfig,
    metallicity_checkpoint: str | None = None,
    metallicity_atom_init: str | None = None,
) -> KMeshAdvisor:
    """Return a lazy Kmesh backend configured for one QRF contract.

    Construction performs no model loading, hashing, remote access, or heavy ML
    imports. The first call without a k-point hint loads and validates once.
    """
    loaded: tuple[object, object, str, str, JsonDict] | None = None
    load_error: Exception | None = None
    load_details: JsonDict | None = None
    load_failure_stage = "schema"
    load_lock = Lock()

    def advisor(structure, hints, kpoint_advice):
        nonlocal loaded, load_error, load_details, load_failure_stage

        if hints.k_grid is not None or hints.k_spacing is not None:
            return resolve_kpoints_from_advice(structure, hints, kpoint_advice)

        if loaded is None and load_error is None:
            with load_lock:
                if loaded is None and load_error is None:
                    try:
                        from goldilocks_core.ml.metallicity import (
                            load_metallicity_model,
                        )
                        from goldilocks_core.ml.models import load_model

                        load_failure_stage = "schema"
                        load_details = _qrf_contract_details(config)
                        _validate_qrf_contract(config)

                        load_failure_stage = "artifact_resolution"
                        checkpoint, atom_init = _resolve_metallicity_artifacts(
                            config,
                            metallicity_checkpoint,
                            metallicity_atom_init,
                        )

                        load_failure_stage = "model_load"
                        qrf = load_model(config.model)
                        load_failure_stage = "model_contract"
                        _validate_loaded_qrf_quantiles(qrf, config)
                        metal_model = load_metallicity_model(checkpoint)
                        details = _qrf_contract_details(config)
                        data_source = (
                            f"{config.model.name}@"
                            f"{config.model.revision or config.model.version}; "
                            f"qrf_config_sha256={config.digest}"
                        )
                        loaded = (
                            qrf,
                            metal_model,
                            atom_init,
                            data_source,
                            details,
                        )
                    except Exception as error:
                        load_error = error

        if load_error is not None:
            return _heuristic_fallback(
                structure,
                hints,
                kpoint_advice,
                load_error,
                inference_details=load_details or _qrf_contract_details(config),
                failure_stage=load_failure_stage,
            )

        if loaded is None:  # pragma: no cover - defensive closure invariant
            raise RuntimeError("QRF advisor reached an invalid unloaded state.")

        qrf, metal_model, atom_init, data_source, details = loaded
        try:
            from goldilocks_core.ml.kdistance_features import extract_qrf_features

            features = extract_qrf_features(
                structure,
                metal_model,
                atom_init,
                config.feature_settings,
            )
            median, lower, upper = predict_kdistance_quantiles(
                qrf,
                features,
                config.calibration.correction,
            )
        except Exception as predict_error:
            return _heuristic_fallback(
                structure,
                hints,
                kpoint_advice,
                predict_error,
                inference_details=details,
                failure_stage="prediction",
            )

        return kdistance_to_selection(
            structure,
            median,
            lower,
            upper,
            data_source=data_source,
            confidence=config.interval_confidence,
            details=details,
        )

    return advisor


def default_kmesh_advisor(
    *,
    registry_path: PathLike | None = None,
    config: QrfKpointsConfig | None = None,
    metallicity_checkpoint: str | None = None,
    metallicity_atom_init: str | None = None,
) -> KMeshAdvisor:
    """Return the configured default QRF Kmesh backend with fallback."""
    if config is not None and registry_path is not None:
        raise ValueError("Pass config or registry_path, not both.")

    checkpoint = metallicity_checkpoint or os.environ.get(
        "GOLDILOCKS_METALLICITY_CHECKPOINT"
    )
    atom_init = metallicity_atom_init or os.environ.get(
        "GOLDILOCKS_METALLICITY_ATOM_INIT"
    )
    configured_advisor: KMeshAdvisor | None = None
    config_error: Exception | None = None
    config_details: JsonDict | None = None
    config_lock = Lock()

    def advisor(structure, hints, kpoint_advice):
        nonlocal configured_advisor, config_error, config_details

        if hints.k_grid is not None or hints.k_spacing is not None:
            return resolve_kpoints_from_advice(structure, hints, kpoint_advice)

        if configured_advisor is None and config_error is None:
            with config_lock:
                if configured_advisor is None and config_error is None:
                    try:
                        active_config = config or load_default_qrf_config(registry_path)
                        configured_advisor = qrf_kdistance_advisor(
                            active_config,
                            checkpoint,
                            atom_init,
                        )
                    except Exception as error:
                        config_error = error
                        config_details = _unparsed_registry_details(
                            registry_path or os.environ.get(MODEL_REGISTRY_ENV)
                        )

        if config_error is not None:
            return _heuristic_fallback(
                structure,
                hints,
                kpoint_advice,
                config_error,
                inference_details=config_details
                or _unparsed_registry_details(registry_path),
                failure_stage="registry",
            )
        if configured_advisor is None:  # pragma: no cover - closure invariant
            raise RuntimeError("Default Kmesh advisor failed to configure.")
        return configured_advisor(structure, hints, kpoint_advice)

    return advisor
