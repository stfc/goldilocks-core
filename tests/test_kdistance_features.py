import numpy as np
import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.ml.kdistance_features import (
    QRF_FEATURE_COUNT,
    QRF_FEATURE_SCHEMA,
    _require_finite,
    extract_qrf_features,
    extract_structure_features,
)
from goldilocks_core.ml.model_registry import load_default_qrf_config


def make_diamond_silicon() -> Structure:
    a = 5.43
    return Structure(
        lattice=Lattice([[0, a / 2, a / 2], [a / 2, 0, a / 2], [a / 2, a / 2, 0]]),
        species=["Si", "Si"],
        coords=[[0.0, 0.0, 0.0], [0.25, 0.25, 0.25]],
    )


def test_extractor_schema_matches_packaged_registry() -> None:
    """The extractor owns the schema declared by the packaged artifact."""
    config = load_default_qrf_config()

    assert config.feature_schema == QRF_FEATURE_SCHEMA
    assert config.feature_count == QRF_FEATURE_COUNT


def test_extract_structure_features_dimension_and_finiteness() -> None:
    """The configured non-metallicity block has the trained 419 dimensions."""
    config = load_default_qrf_config()
    features = extract_structure_features(
        make_diamond_silicon(),
        config.feature_settings,
    )

    assert features.shape == (419,)
    assert np.isfinite(features).all()


def test_extract_qrf_features_assembles_483_values_and_names(monkeypatch) -> None:
    config = load_default_qrf_config()
    monkeypatch.setattr(
        "goldilocks_core.ml.kdistance_features.extract_structure_features",
        lambda structure, settings: np.arange(419, dtype=float),
    )
    monkeypatch.setattr(
        "goldilocks_core.ml.metallicity.metal_features",
        lambda structure, model, atom_init_path, **settings: np.arange(64, dtype=float),
    )

    features = extract_qrf_features(
        make_diamond_silicon(),
        object(),
        "atom-init.json",
        config.feature_settings,
    )

    assert features.values.shape == (483,)
    assert features.feature_names == [f"qrf_{index}" for index in range(483)]


@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf])
def test_feature_cleaning_rejects_every_non_finite_value(value) -> None:
    """Extraction never replaces non-finite values with finite sentinels."""
    with pytest.raises(ValueError, match="non-finite"):
        _require_finite(np.array([0.0, value]), "test block")


def test_extract_structure_features_is_deterministic() -> None:
    structure = make_diamond_silicon()
    settings = load_default_qrf_config().feature_settings

    first = extract_structure_features(structure, settings)
    second = extract_structure_features(structure, settings)

    assert np.array_equal(first, second)
