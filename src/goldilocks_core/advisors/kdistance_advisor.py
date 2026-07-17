"""Quantile Random Forest (QRF) k-distance advisor.

The registry defines the complete inference configuration. Successful model
selections carry a structured, content-addressed reconstruction record in
provenance; unavailable or incompatible inference falls back to advice.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from importlib.metadata import version
from pathlib import Path
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
    """Return (median, lower, upper) k-distance in Å⁻¹ from a QRF prediction.

    Feature values are checked immediately before ``predict`` so mutation of a
    previously validated feature vector cannot send NaN or infinity to a model.
    """
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
    details = _fallback_provenance_details(
        inference_details,
        failure_stage,
        error,
        error_message,
    )
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
            details=details,
            warnings=(*selection.provenance.warnings, warning),
        ),
    )


def _fallback_provenance_details(
    inference_details: JsonDict,
    failure_stage: str,
    error: Exception,
    error_message: str,
) -> JsonDict:
    """Attach structured QRF identity and failure context to a fallback."""
    return {
        "qrf_inference": {
            **inference_details["qrf_inference"],
            "failure": {
                "stage": failure_stage,
                "type": error.__class__.__name__,
                "message": error_message,
            },
        }
    }


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
    *,
    resolved_artifacts: dict[str, str],
) -> tuple[str, str]:
    """Resolve configured metallicity artifacts to local paths."""
    if checkpoint is not None and atom_init is not None:
        resolved_artifacts["metallicity_checkpoint"] = checkpoint
        resolved_artifacts["metallicity_atom_table"] = atom_init
        return checkpoint, atom_init

    from goldilocks_core.ml.models import resolve_artifact

    checkpoint = checkpoint or resolve_artifact(
        config.metallicity,
        config.metallicity_checkpoint_file,
    )
    resolved_artifacts["metallicity_checkpoint"] = checkpoint
    atom_init = atom_init or resolve_artifact(
        config.metallicity,
        config.metallicity_atom_init_file,
    )
    resolved_artifacts["metallicity_atom_table"] = atom_init
    return checkpoint, atom_init


def _validate_qrf_contract(config: QrfKpointsConfig) -> None:
    """Validate QRF schema, immutable artifacts, and calibration semantics."""
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


def _validate_qrf_runtime(
    config: QrfKpointsConfig,
    runtime_versions: dict[str, str],
) -> None:
    """Validate exact runtime versions, retaining every observed version."""
    for requirement in config.runtime_requirements:
        installed_version = version(requirement.distribution)
        runtime_versions[requirement.distribution] = installed_version
        if installed_version != requirement.version:
            raise ValueError(
                f"QRF model requires {requirement.distribution} "
                f"{requirement.version}; found {installed_version}."
            )


def _sha256_file(path: str) -> str:
    """Return the SHA-256 content identity of one local inference artifact."""
    artifact_path = Path(path)
    if not artifact_path.is_file():
        raise FileNotFoundError(f"Inference artifact file not found: {artifact_path}")
    digest = hashlib.sha256()
    with artifact_path.open("rb") as artifact_file:
        for chunk in iter(lambda: artifact_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _model_artifact_identity(config: QrfKpointsConfig) -> JsonDict:
    """Return the remote commit or local content identity of the QRF artifact."""
    if config.model.source == "local":
        return {
            "role": "qrf_model",
            "source": "local",
            "path": config.model.location,
            "sha256": _sha256_file(config.model.location),
        }

    repository, separator, filename = config.model.location.partition("::")
    if not separator or not repository or not filename:
        raise ValueError(
            "HuggingFace model location must be '<repo_id>::<filename>'; "
            f"got {config.model.location!r}"
        )
    return {
        "role": "qrf_model",
        "source": "huggingface",
        "repository": repository,
        "filename": filename,
        "revision": config.model.revision,
    }


def _supporting_artifact_identity(
    *,
    role: str,
    config: QrfKpointsConfig,
    configured_filename: str,
    resolved_path: str,
    overridden: bool,
) -> JsonDict:
    """Return a remote commit identity or SHA-256 local content identity."""
    if overridden or config.metallicity.source == "local":
        return {
            "role": role,
            "source": "local",
            "path": resolved_path,
            "sha256": _sha256_file(resolved_path),
        }
    return {
        "role": role,
        "source": "huggingface",
        "repository": config.metallicity.location,
        "filename": configured_filename,
        "revision": config.metallicity.revision,
    }


def _qrf_contract_details(config: QrfKpointsConfig) -> JsonDict:
    """Build the configuration and extractor record available before loading."""
    from goldilocks_core.ml.kdistance_features import (
        QRF_EXTRACTOR_ID,
        QRF_FEATURE_COUNT,
        QRF_FEATURE_SCHEMA,
    )

    return {
        "qrf_inference": {
            "config_digest": {"algorithm": "sha256", "value": config.digest},
            "configuration": config.to_dict(),
            "extractor": {
                "identity": QRF_EXTRACTOR_ID,
                "feature_schema": QRF_FEATURE_SCHEMA,
                "feature_count": QRF_FEATURE_COUNT,
            },
        }
    }


def _with_runtime_details(
    details: JsonDict,
    config: QrfKpointsConfig,
    runtime_versions: dict[str, str],
) -> JsonDict:
    """Add required and observed runtime versions to QRF details."""
    inference = {
        **details["qrf_inference"],
        "runtime": [
            {
                "distribution": requirement.distribution,
                "required_version": requirement.version,
                **(
                    {"installed_version": runtime_versions[requirement.distribution]}
                    if requirement.distribution in runtime_versions
                    else {}
                ),
            }
            for requirement in config.runtime_requirements
        ],
    }
    if "goldilocks-core" in runtime_versions:
        inference["core"] = {
            "distribution": "goldilocks-core",
            "version": runtime_versions["goldilocks-core"],
        }
    return {"qrf_inference": inference}


def _with_resolved_artifact_details(
    details: JsonDict,
    resolved_artifacts: dict[str, str],
) -> JsonDict:
    """Add supporting artifact paths resolved before a later load failure."""
    if not resolved_artifacts:
        return details
    return {
        "qrf_inference": {
            **details["qrf_inference"],
            "resolved_artifacts": [
                {"role": role, "path": path}
                for role, path in resolved_artifacts.items()
            ],
        }
    }


def _qrf_provenance_details(
    config: QrfKpointsConfig,
    runtime_versions: dict[str, str],
    checkpoint_path: str,
    atom_init_path: str,
    checkpoint_overridden: bool,
    atom_init_overridden: bool,
) -> JsonDict:
    """Build the complete structured QRF inference reconstruction record."""
    details = _with_runtime_details(
        _qrf_contract_details(config), config, runtime_versions
    )
    details["qrf_inference"]["artifacts"] = [
        _model_artifact_identity(config),
        _supporting_artifact_identity(
            role="metallicity_checkpoint",
            config=config,
            configured_filename=config.metallicity_checkpoint_file,
            resolved_path=checkpoint_path,
            overridden=checkpoint_overridden,
        ),
        _supporting_artifact_identity(
            role="metallicity_atom_table",
            config=config,
            configured_filename=config.metallicity_atom_init_file,
            resolved_path=atom_init_path,
            overridden=atom_init_overridden,
        ),
    ]
    return details


def _validate_atom_table_identity(details: JsonDict, atom_init_path: str) -> None:
    """Reject mutation of a local atom table between hashing and extraction."""
    artifacts = details["qrf_inference"]["artifacts"]
    atom_table = next(
        artifact
        for artifact in artifacts
        if artifact["role"] == "metallicity_atom_table"
    )
    if atom_table["source"] == "local":
        current_hash = _sha256_file(atom_init_path)
        if current_hash != atom_table["sha256"]:
            raise ValueError(
                "Local metallicity atom table changed after QRF initialization."
            )


def qrf_kdistance_advisor(
    config: QrfKpointsConfig,
    metallicity_checkpoint: str | None = None,
    metallicity_atom_init: str | None = None,
) -> KMeshAdvisor:
    """Return a lazy Kmesh backend configured for one complete QRF contract.

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

                        runtime_versions: dict[str, str] = {}
                        load_failure_stage = "runtime"
                        try:
                            _validate_qrf_runtime(config, runtime_versions)
                        finally:
                            load_details = _with_runtime_details(
                                load_details,
                                config,
                                runtime_versions,
                            )

                        resolved_artifacts: dict[str, str] = {}
                        load_failure_stage = "artifact_resolution"
                        try:
                            checkpoint, atom_init = _resolve_metallicity_artifacts(
                                config,
                                metallicity_checkpoint,
                                metallicity_atom_init,
                                resolved_artifacts=resolved_artifacts,
                            )
                        finally:
                            load_details = _with_resolved_artifact_details(
                                load_details,
                                resolved_artifacts,
                            )
                        details = _qrf_provenance_details(
                            config,
                            runtime_versions,
                            checkpoint,
                            atom_init,
                            metallicity_checkpoint is not None,
                            metallicity_atom_init is not None,
                        )
                        load_details = details
                        load_failure_stage = "model_load"
                        qrf = load_model(config.model)
                        load_failure_stage = "model_contract"
                        _validate_loaded_qrf_quantiles(qrf, config)
                        metal_model = load_metallicity_model(checkpoint)
                        if details != _qrf_provenance_details(
                            config,
                            runtime_versions,
                            checkpoint,
                            atom_init,
                            metallicity_checkpoint is not None,
                            metallicity_atom_init is not None,
                        ):
                            raise ValueError(
                                "Local QRF inference artifact changed while loading."
                            )
                        data_source = (
                            f"{config.model.name}@"
                            f"{config.model.revision or config.model.version}; "
                            f"qrf_config_sha256={config.digest}"
                        )
                        loaded = (qrf, metal_model, atom_init, data_source, details)
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

            _validate_atom_table_identity(details, atom_init)
            features = extract_qrf_features(
                structure,
                metal_model,
                atom_init,
                config.feature_settings,
            )
            _validate_atom_table_identity(details, atom_init)
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
