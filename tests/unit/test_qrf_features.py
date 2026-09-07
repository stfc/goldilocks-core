import types
from dataclasses import replace

import pytest
from pymatgen.core import Lattice, Structure


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
