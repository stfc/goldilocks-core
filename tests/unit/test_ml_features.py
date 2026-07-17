import numpy as np
from pymatgen.core import Lattice, Structure

from goldilocks_core.ml.features import (
    extract_c_features,
    extract_cslr_features,
    extract_l_features,
    extract_r_features,
    extract_s_features,
)


def test_extract_l_features_returns_lattice_features() -> None:
    """Extract the expected lattice-based feature vector."""
    structure = Structure(
        lattice=Lattice.cubic(3.5),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )

    features = extract_l_features(structure)

    assert features.feature_names == [
        "a",
        "b",
        "c",
        "alpha",
        "beta",
        "gamma",
        "volume",
    ]
    assert np.allclose(
        features.values,
        np.array([3.5, 3.5, 3.5, 90.0, 90.0, 90.0, 42.875]),
    )


def test_extract_cslr_features_combines_feature_blocks() -> None:
    """Combine C, S, L, and R feature blocks in a fixed order."""
    structure = Structure(
        lattice=Lattice.cubic(3.5),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )

    c_features = extract_c_features(structure)
    s_features = extract_s_features(structure)
    l_features = extract_l_features(structure)
    r_features = extract_r_features(structure)

    cslr_features = extract_cslr_features(structure)

    expected_names = (
        c_features.feature_names
        + s_features.feature_names
        + l_features.feature_names
        + r_features.feature_names
    )
    expected_values = np.concatenate(
        [
            c_features.values,
            s_features.values,
            l_features.values,
            r_features.values,
        ]
    )

    assert cslr_features.feature_names == expected_names
    assert np.allclose(cslr_features.values, expected_values)
