"""Quantile Random Forest (QRF) k-distance advisor.

The QRF model predicts a VASP-style k-point distance (Å⁻¹) as three quantiles
(lower, median, upper). The median drives the concrete mesh; the interval and
the model's confidence level are recorded in provenance. Default model and
artifact locations are supplied by the configurable model registry.
"""

from __future__ import annotations

import os
from dataclasses import replace
from threading import Lock

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
from goldilocks_core.ml.model_registry import (
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
    """Return (median, lower, upper) k-distance in Å⁻¹ from a QRF prediction.

    The QRF returns three quantiles ``[lower, median, upper]`` for the single
    input row. ``correction`` adjusts the interval bounds using the calibrated
    reference formula.

    Raises:
        AttributeError: If the model has no ``predict`` method.
        ValueError: If the prediction does not yield three finite, positive,
            ordered quantiles.
    """
    if not hasattr(model, "predict"):
        raise AttributeError("QRF model does not provide a 'predict' method.")

    raw = np.asarray(model.predict(features.values.reshape(1, -1)), dtype=float)
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
    mesh_type: str = "monkhorst-pack",
) -> KPointSelection:
    """Build a concrete k-point selection from a predicted k-distance interval.

    The median distance sets the mesh; the interval and confidence level are
    recorded in provenance so callers can judge the prediction.

    Raises:
        ValueError: If the distances are non-finite, non-positive, or misordered.
    """
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
        ),
    )


def _heuristic_fallback(
    structure: Structure,
    hints: CalculationHints,
    advice: KPointAdvice,
    error: Exception,
) -> KPointSelection:
    """Resolve k-points from heuristic advice and record the model failure."""
    detail = str(error) or error.__class__.__name__
    selection = resolve_kpoints_from_advice(structure, hints, advice)
    warning = f"ML k-point model unavailable; used heuristic k-point advice ({detail})."
    return replace(
        selection,
        provenance=replace(
            selection.provenance,
            warnings=(*selection.provenance.warnings, warning),
        ),
    )


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


def _validate_qrf_config(config: QrfKpointsConfig) -> None:
    """Ensure a hot-swapped model matches this advisor's inference contract."""
    from importlib.metadata import version

    from goldilocks_core.ml.kdistance_features import QRF_FEATURE_SET

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
    required_runtime = {
        "scikit-learn": config.scikit_learn_version,
        "sklearn-quantile": config.sklearn_quantile_version,
        "joblib": config.joblib_version,
    }
    for package, required_version in required_runtime.items():
        installed_version = version(package)
        if installed_version != required_version:
            raise ValueError(
                f"QRF model requires {package} {required_version}; "
                f"found {installed_version}."
            )


def _model_data_source(
    config: QrfKpointsConfig,
    checkpoint_override: str | None,
    atom_init_override: str | None,
) -> str:
    """Identify every configured or overridden artifact used for inference."""
    model_revision = config.model.revision or "unversioned"
    artifact_revision = config.metallicity.revision or "unversioned"
    checkpoint_source = checkpoint_override or (
        f"{config.metallicity.source}:{config.metallicity.location}::"
        f"{config.metallicity_checkpoint_file}@{artifact_revision}"
    )
    atom_init_source = atom_init_override or (
        f"{config.metallicity.source}:{config.metallicity.location}::"
        f"{config.metallicity_atom_init_file}@{artifact_revision}"
    )
    return (
        f"model={config.model.source}:{config.model.location}@{model_revision}; "
        f"metallicity_checkpoint={checkpoint_source}; "
        f"metallicity_atom_init={atom_init_source}; "
        f"runtime=scikit-learn=={config.scikit_learn_version},"
        f"sklearn-quantile=={config.sklearn_quantile_version},"
        f"joblib=={config.joblib_version}"
    )


def qrf_kdistance_advisor(
    config: QrfKpointsConfig,
    metallicity_checkpoint: str | None = None,
    metallicity_atom_init: str | None = None,
) -> KMeshAdvisor:
    """Return a lazy Kmesh backend configured for one QRF model.

    Construction performs no model loading, remote access, or heavyweight ML
    imports. The first call without a k-point hint resolves and loads configured
    artifacts, then caches either the models or the load failure. Explicit
    ``k_grid`` and ``k_spacing`` hints always bypass loading and inference.

    Model loading and per-structure inference failures degrade to heuristic
    advice and are recorded in provenance warnings.
    """
    loaded: tuple[object, object, str, str] | None = None
    load_error: Exception | None = None
    load_lock = Lock()

    def advisor(structure, hints, kpoint_advice):
        nonlocal loaded, load_error

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

                        _validate_qrf_config(config)
                        qrf = load_model(config.model)
                        checkpoint, atom_init = _resolve_metallicity_artifacts(
                            config,
                            metallicity_checkpoint,
                            metallicity_atom_init,
                        )
                        metal_model = load_metallicity_model(checkpoint)
                        data_source = _model_data_source(
                            config,
                            metallicity_checkpoint,
                            metallicity_atom_init,
                        )
                        loaded = (qrf, metal_model, atom_init, data_source)
                    except Exception as error:
                        load_error = error

        if load_error is not None:
            return _heuristic_fallback(
                structure,
                hints,
                kpoint_advice,
                load_error,
            )

        if loaded is None:  # pragma: no cover - defensive closure invariant
            raise RuntimeError("QRF advisor reached an invalid unloaded state.")

        qrf, metal_model, atom_init, data_source = loaded
        try:
            from goldilocks_core.ml.kdistance_features import extract_qrf_features

            features = extract_qrf_features(structure, metal_model, atom_init)
            median, lower, upper = predict_kdistance_quantiles(
                qrf,
                features,
                config.correction,
            )
        except Exception as predict_error:
            return _heuristic_fallback(
                structure,
                hints,
                kpoint_advice,
                predict_error,
            )

        return kdistance_to_selection(
            structure,
            median,
            lower,
            upper,
            data_source=data_source,
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
    """Return the configured default QRF Kmesh backend with fallback.

    The packaged model registry is used unless ``registry_path`` or
    ``GOLDILOCKS_MODEL_REGISTRY`` selects another registry. Explicit local
    metallicity paths can be supplied through arguments or the
    ``GOLDILOCKS_METALLICITY_CHECKPOINT`` and
    ``GOLDILOCKS_METALLICITY_ATOM_INIT`` environment variables.
    """
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
    config_lock = Lock()

    def advisor(structure, hints, kpoint_advice):
        nonlocal configured_advisor, config_error

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

        if config_error is not None:
            return _heuristic_fallback(
                structure,
                hints,
                kpoint_advice,
                config_error,
            )
        if configured_advisor is None:  # pragma: no cover - closure invariant
            raise RuntimeError("Default Kmesh advisor failed to configure.")
        return configured_advisor(structure, hints, kpoint_advice)

    return advisor
