"""Explicit compatibility validation for real QRF artifacts."""

from __future__ import annotations

from pymatgen.core import Lattice, Structure

from goldilocks_core.contracts import JsonDict, PathLike
from goldilocks_core.ml.model_registry import load_default_qrf_config


def validate_real_qrf_artifacts(
    *,
    allow_network: bool = False,
    registry_path: PathLike | None = None,
) -> JsonDict:
    """Load real artifacts and run one QRF prediction after explicit opt-in.

    The packaged registry uses remote Hugging Face artifacts. ``allow_network``
    must be true even when they are already cached, keeping this validation out
    of the normal network-free test path. Exceptions are propagated directly;
    compatibility validation never uses the heuristic fallback.
    """
    if not allow_network:
        raise RuntimeError(
            "Real QRF artifact validation requires explicit allow_network=True opt-in."
        )

    from goldilocks_core.advisors.kdistance_advisor import (
        _validate_loaded_qrf_quantiles,
        _validate_qrf_contract,
        predict_kdistance_quantiles,
    )
    from goldilocks_core.ml.kdistance_features import extract_qrf_features
    from goldilocks_core.ml.metallicity import load_metallicity_model
    from goldilocks_core.ml.models import load_model

    config = load_default_qrf_config(registry_path)
    _validate_qrf_contract(config)
    qrf = load_model(config.model)
    _validate_loaded_qrf_quantiles(qrf, config)
    checkpoint, atom_init = _resolve_metallicity_artifacts(config)
    metallicity_model = load_metallicity_model(checkpoint)
    structure = Structure(
        Lattice.cubic(5.43),
        ["Si", "Si"],
        [[0.0, 0.0, 0.0], [0.25, 0.25, 0.25]],
    )
    features = extract_qrf_features(
        structure,
        metallicity_model,
        atom_init,
        config.feature_settings,
    )
    median, lower, upper = predict_kdistance_quantiles(
        qrf,
        features,
        config.calibration.correction,
    )
    return {
        "config_digest": config.digest,
        "feature_schema": config.feature_schema,
        "feature_count": len(features.values),
        "prediction": {"median": median, "lower": lower, "upper": upper},
    }


def _resolve_metallicity_artifacts(config) -> tuple[str, str]:
    from goldilocks_core.ml.models import resolve_artifact

    checkpoint = resolve_artifact(
        config.metallicity,
        config.metallicity_checkpoint_file,
    )
    atom_init = resolve_artifact(
        config.metallicity,
        config.metallicity_atom_init_file,
    )
    return checkpoint, atom_init
