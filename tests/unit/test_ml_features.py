import types
from dataclasses import replace

import numpy as np
import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.ml.kindex.features import (
    extract_c_features,
    extract_cslr_features,
    extract_l_features,
    extract_r_features,
    extract_s_features,
)


def test_extract_l_features_returns_lattice_features() -> None:
    structure = Structure(
        lattice=Lattice.cubic(3.5),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )

    values, names = extract_l_features(structure)

    assert names == [
        "a",
        "b",
        "c",
        "alpha",
        "beta",
        "gamma",
        "volume",
    ]
    assert np.allclose(
        values,
        np.array([3.5, 3.5, 3.5, 90.0, 90.0, 90.0, 42.875]),
    )


def test_extract_cslr_features_combines_feature_blocks() -> None:
    structure = Structure(
        lattice=Lattice.cubic(3.5),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )

    c_values, c_names = extract_c_features(structure)
    s_values, s_names = extract_s_features(structure)
    l_values, l_names = extract_l_features(structure)
    r_values, r_names = extract_r_features(structure)

    cslr_values, cslr_names = extract_cslr_features(structure)

    expected_names = c_names + s_names + l_names + r_names
    expected_values = np.concatenate([c_values, s_values, l_values, r_values])

    assert cslr_names == expected_names
    assert np.allclose(cslr_values, expected_values)


def test_composition_featurizer_rejecting_impute_nan_propagates_type_error(
    monkeypatch,
) -> None:
    from goldilocks_core.ml.model_registry import load_default_qrf_config
    from goldilocks_core.ml.qrf.features import _composition_features

    class RejectImputeNan:
        def __init__(self, *, impute_nan: bool = False) -> None:
            if impute_nan:
                raise TypeError("RejectImputeNan does not accept impute_nan")

        def featurize(self, _obj: object) -> list[float]:
            return []

    fake_module = types.ModuleType("composition")
    fake_module.RejectImputeNan = RejectImputeNan
    monkeypatch.setattr(
        "matminer.featurizers.composition",
        fake_module,
    )

    config = load_default_qrf_config()
    settings = replace(
        config.feature_settings,
        composition_featurizers=("RejectImputeNan",),
    )
    structure = Structure(
        lattice=Lattice.cubic(3.5),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )

    with pytest.raises(TypeError, match="does not accept impute_nan"):
        _composition_features(structure, settings)
