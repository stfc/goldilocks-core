import numpy as np
from pymatgen.core import Lattice, Structure

from goldilocks_core.ml.kdistance_features import extract_structure_features


def make_diamond_silicon() -> Structure:
    a = 5.43
    return Structure(
        lattice=Lattice([[0, a / 2, a / 2], [a / 2, 0, a / 2], [a / 2, a / 2, 0]]),
        species=["Si", "Si"],
        coords=[[0.0, 0.0, 0.0], [0.25, 0.25, 0.25]],
    )


def test_extract_structure_features_dimension_and_finiteness() -> None:
    """The comp+struct+soap+lattice block has the trained 419-dim length."""
    features = extract_structure_features(make_diamond_silicon())

    # composition(146) + structure(6) + soap(252) + lattice(15) = 419; the CGCNN
    # metallicity block (64) is appended by the caller to reach the QRF's 483.
    assert features.shape == (419,)
    assert np.isfinite(features).all()


def test_extract_structure_features_is_deterministic() -> None:
    """The same structure yields the same feature vector."""
    structure = make_diamond_silicon()

    first = extract_structure_features(structure)
    second = extract_structure_features(structure)

    assert np.array_equal(first, second)
