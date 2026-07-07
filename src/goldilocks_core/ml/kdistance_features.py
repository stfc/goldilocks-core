"""Composition + structure + SOAP + lattice features for the QRF k-distance model.

Reproduces the non-metallicity half of the feature vector the STFC QRF was
trained on (matminer composition/structure descriptors, dscribe SOAP, and
lattice/symmetry values). The CGCNN metallicity block is appended separately.

Feature order within the block: composition, structure, SOAP, lattice. Heavy
dependencies (matminer, dscribe) are imported lazily so importing this module
stays cheap.
"""

from __future__ import annotations

import numpy as np
from pymatgen.core import Structure

from goldilocks_core.contracts import StructureFeatureVector

_COMPOSITION_FEATURES = ("ElementProperty", "Stoichiometry", "ValenceOrbital")
_STRUCTURE_FEATURES = ("GlobalSymmetryFeatures", "DensityFeatures")
_SOAP_PARAMS = {"r_cut": 10.0, "n_max": 8, "l_max": 6, "sigma": 1.0}

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


def extract_structure_features(structure: Structure) -> np.ndarray:
    """Return the composition+structure+SOAP+lattice feature block (1-D).

    Order matches the trained QRF: composition, structure, SOAP, lattice. The
    CGCNN metallicity block is concatenated by the caller.
    """
    return np.concatenate(
        [
            _composition_features(structure),
            _structure_features(structure),
            _soap_features(structure),
            _lattice_features(structure),
        ]
    )


def extract_qrf_features(
    structure: Structure,
    metal_model: object,
    atom_init_path: str,
) -> StructureFeatureVector:
    """Assemble the full 483-dim QRF feature vector for one structure.

    Concatenates the composition+structure+SOAP+lattice block (419) with the
    CGCNN metallicity crystal representation (64), in the trained order.
    """
    from goldilocks_core.ml.metallicity import metal_features

    structure_block = extract_structure_features(structure)
    metal_block = metal_features(structure, metal_model, atom_init_path)
    values = np.concatenate([structure_block, metal_block])
    return StructureFeatureVector(
        values=values,
        feature_names=[f"qrf_{index}" for index in range(values.size)],
    )


def _clean(values: np.ndarray) -> np.ndarray:
    """Return a finite float array (NaN/inf -> 0.0)."""
    return np.nan_to_num(np.asarray(values, dtype=float), nan=0.0)


def _composition_features(structure: Structure) -> np.ndarray:
    import matminer.featurizers.composition as composition_featurizers
    from matminer.featurizers.base import MultipleFeaturizer
    from pymatgen.core.composition import Composition

    integer_formula = Composition(structure.formula).get_integer_formula_and_factor()[0]
    composition = Composition(Composition(integer_formula).iupac_formula)

    methods = []
    for name in _COMPOSITION_FEATURES:
        featurizer_cls = getattr(composition_featurizers, name)
        if name == "ElementProperty":
            method = featurizer_cls.from_preset("magpie", impute_nan=True)
        else:
            try:
                method = featurizer_cls(impute_nan=True)
            except TypeError:
                method = featurizer_cls()
        methods.append(method)

    featurizer = MultipleFeaturizer(methods)
    return _clean(featurizer.featurize(composition))


def _structure_features(structure: Structure) -> np.ndarray:
    import matminer.featurizers.structure as structure_featurizers
    from matminer.featurizers.base import MultipleFeaturizer

    methods = [
        structure_featurizers.GlobalSymmetryFeatures(
            ["spacegroup_num", "crystal_system_int", "is_centrosymmetric"]
        ),
        structure_featurizers.DensityFeatures(["density", "vpa", "packing fraction"]),
    ]
    featurizer = MultipleFeaturizer(methods)
    return _clean(featurizer.featurize(structure))


def _soap_features(structure: Structure) -> np.ndarray:
    from dscribe.descriptors import SOAP
    from pymatgen.io.ase import AseAtomsAdaptor

    soap = SOAP(
        species=["X"],
        r_cut=_SOAP_PARAMS["r_cut"],
        n_max=_SOAP_PARAMS["n_max"],
        l_max=_SOAP_PARAMS["l_max"],
        sigma=_SOAP_PARAMS["sigma"],
        periodic=True,
        sparse=False,
    )
    atoms = AseAtomsAdaptor.get_atoms(structure)
    atoms.set_chemical_symbols(["X"] * len(atoms))
    return _clean(soap.create(atoms).mean(axis=0))


def _lattice_features(structure: Structure) -> np.ndarray:
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    values: list[float] = []
    values.extend(structure.lattice.abc)
    values.extend(structure.lattice.angles)
    values.extend(structure.lattice.reciprocal_lattice.abc)
    values.extend(structure.lattice.reciprocal_lattice.angles)

    analyzer = SpacegroupAnalyzer(structure, symprec=0.01)
    crystal_system = analyzer.get_crystal_system()
    space_group_symbol = analyzer.get_space_group_symbol()
    bravais = _SYSTEM_ABBREVIATION[crystal_system] + space_group_symbol[0]

    values.append(_CRYSTAL_SYSTEM_ID[crystal_system])
    values.append(_BRAVAIS_ID.get(bravais, -1))
    values.append(analyzer.get_space_group_number())

    return _clean(values)
