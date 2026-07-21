"""Composition + structure + SOAP + lattice features for the QRF model.

The extractor owns the ordered 483-value schema. The model registry declares
that schema and owns the feature-producing settings used for one artifact.
Heavy dependencies are imported lazily so importing this module stays cheap.
"""

from __future__ import annotations

import numpy as np
from pymatgen.core import Structure

from goldilocks_core.contracts import StructureFeatureVector
from goldilocks_core.ml.model_registry import QrfFeatureSettings

QRF_EXTRACTOR_ID = "goldilocks_core.ml.kdistance_features:extract_qrf_features"
QRF_FEATURE_SET = "qrf_comp_struct_soap_lattice_metal"
QRF_FEATURE_SCHEMA = "qrf-483-v1"
QRF_FEATURE_COUNT = 483

_CRYSTAL_SYSTEM_ID = {
    "triclinic": 0,
    "monoclinic": 1,
    "orthorhombic": 2,
    "tetragonal": 3,
    "trigonal": 4,
    "hexagonal": 5,
    "cubic": 6,
}
_SYSTEM_ABBREVIATION = {
    "triclinic": "a",
    "monoclinic": "m",
    "orthorhombic": "o",
    "tetragonal": "t",
    "trigonal": "h",
    "hexagonal": "h",
    "cubic": "c",
}
_BRAVAIS_ID = {
    "aP": 0,
    "mP": 1,
    "mC": 2,
    "oP": 3,
    "oC": 4,
    "oI": 5,
    "oF": 6,
    "tP": 7,
    "tI": 8,
    "hP": 9,
    "hR": 10,
    "cP": 11,
    "cI": 12,
    "cF": 13,
}


def extract_structure_features(
    structure: Structure,
    settings: QrfFeatureSettings,
) -> np.ndarray:
    """Return the ordered composition, structure, SOAP, and lattice block."""
    return np.concatenate(
        [
            _composition_features(structure, settings),
            _structure_features(structure, settings),
            _soap_features(structure, settings),
            _lattice_features(structure, settings),
        ]
    )


def extract_qrf_features(
    structure: Structure,
    metal_model: object,
    atom_init_path: str,
    settings: QrfFeatureSettings,
) -> StructureFeatureVector:
    """Assemble the extractor-owned 483-value QRF feature schema."""
    from goldilocks_core.ml.metallicity import metal_features

    structure_block = extract_structure_features(structure, settings)
    metal_block = metal_features(
        structure,
        metal_model,
        atom_init_path,
        graph_radius=settings.metallicity_graph_radius,
        max_neighbors=settings.metallicity_max_neighbors,
    )
    values = _require_finite(
        np.concatenate([structure_block, metal_block]),
        "QRF feature vector",
    )
    if values.size != QRF_FEATURE_COUNT:
        raise ValueError(
            f"QRF feature extractor expected {QRF_FEATURE_COUNT} values; "
            f"got {values.size}."
        )
    return StructureFeatureVector(
        values=values,
        feature_names=[f"qrf_{index}" for index in range(values.size)],
    )


def _require_finite(values: object, block_name: str) -> np.ndarray:
    """Return a float array after rejecting NaN and both infinities."""
    converted = np.asarray(values, dtype=float)
    if not np.isfinite(converted).all():
        raise ValueError(f"{block_name} contains non-finite values.")
    return converted


def _composition_features(
    structure: Structure,
    settings: QrfFeatureSettings,
) -> np.ndarray:
    import matminer.featurizers.composition as composition_featurizers
    from matminer.featurizers.base import MultipleFeaturizer
    from pymatgen.core.composition import Composition

    integer_formula = Composition(structure.formula).get_integer_formula_and_factor()[0]
    composition = Composition(Composition(integer_formula).iupac_formula)

    methods = []
    for name in settings.composition_featurizers:
        featurizer_cls = getattr(composition_featurizers, name)
        if name == "ElementProperty":
            method = featurizer_cls.from_preset(
                settings.element_property_preset,
                impute_nan=settings.impute_nan,
            )
        else:
            try:
                method = featurizer_cls(impute_nan=settings.impute_nan)
            except TypeError:
                method = featurizer_cls()
        methods.append(method)

    featurizer = MultipleFeaturizer(methods)
    return _require_finite(featurizer.featurize(composition), "QRF composition block")


def _structure_features(
    structure: Structure,
    settings: QrfFeatureSettings,
) -> np.ndarray:
    import matminer.featurizers.structure as structure_featurizers
    from matminer.featurizers.base import MultipleFeaturizer

    methods = []
    for name in settings.structure_featurizers:
        if name == "GlobalSymmetryFeatures":
            method = structure_featurizers.GlobalSymmetryFeatures(
                list(settings.global_symmetry_features)
            )
        elif name == "DensityFeatures":
            method = structure_featurizers.DensityFeatures(
                list(settings.density_features)
            )
        else:
            raise ValueError(f"Unsupported QRF structure featurizer: {name!r}.")
        methods.append(method)
    featurizer = MultipleFeaturizer(methods)
    return _require_finite(featurizer.featurize(structure), "QRF structure block")


def _soap_features(
    structure: Structure,
    settings: QrfFeatureSettings,
) -> np.ndarray:
    from dscribe.descriptors import SOAP
    from pymatgen.io.ase import AseAtomsAdaptor

    soap = SOAP(
        species=[settings.soap_species],
        r_cut=settings.soap_r_cut,
        n_max=settings.soap_n_max,
        l_max=settings.soap_l_max,
        sigma=settings.soap_sigma,
        periodic=settings.soap_periodic,
        sparse=settings.soap_sparse,
    )
    atoms = AseAtomsAdaptor.get_atoms(structure)
    atoms.set_chemical_symbols([settings.soap_species] * len(atoms))
    values = soap.create(atoms)
    if settings.soap_reduction == "mean":
        values = values.mean(axis=0)
    return _require_finite(values, "QRF SOAP block")


def _lattice_features(
    structure: Structure,
    settings: QrfFeatureSettings,
) -> np.ndarray:
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    values: list[float] = []
    values.extend(structure.lattice.abc)
    values.extend(structure.lattice.angles)
    values.extend(structure.lattice.reciprocal_lattice.abc)
    values.extend(structure.lattice.reciprocal_lattice.angles)

    analyzer = SpacegroupAnalyzer(structure, symprec=settings.lattice_symprec)
    crystal_system = analyzer.get_crystal_system()
    space_group_symbol = analyzer.get_space_group_symbol()
    bravais = _SYSTEM_ABBREVIATION[crystal_system] + space_group_symbol[0]

    values.append(_CRYSTAL_SYSTEM_ID[crystal_system])
    values.append(_BRAVAIS_ID.get(bravais, -1))
    values.append(analyzer.get_space_group_number())

    return _require_finite(values, "QRF lattice block")
